# Edge cases (sdlc-test)

How to handle unusual situations. When in doubt, prefer surfacing the issue to
the user and writing a `WRN-NNN` over silently guessing.

## A required upstream is missing or in draft

`PRD.yaml`, `DATA-MODEL.yaml`, and `ARCH.yaml` (plus the target
`ARCH__<container>.yaml` in container mode) are hard preconditions. If any is
absent or `metadata.status != complete`, **stop** in Phase 2 with a clear
message naming the file and the skill to run (`/sdlc:prd`, `/sdlc:data`,
`/sdlc:arch`). Do not attempt to seed a test strategy from a draft
architecture — the container/component ids it would reference aren't stable
yet.

## A testable container has no ARCH__<container>.yaml yet

Container mode requires the per-container architecture file (it supplies the
components, requirements, and risks that seed and gate the tests). If a user
runs `/sdlc:test <container>` before `/sdlc:arch <container>`, abort with:
"`<container>` has no `docs/ARCH__<container>.yaml` — run `/sdlc:arch <container>`
first." In `--next` mode, skip such a container, note it, and continue to the
next ready one (SKILL.md → dispatch rule 4).

## The system file doesn't exist when container mode is invoked

Container files inherit global policy (pyramid, coverage floor, mock/fixture
defaults) from `TEST-STRATEGY.yaml`. If it's absent, recommend running
`/sdlc:test` (system) first so there's something to inherit. If the user
insists on drilling a container first, proceed but: set the container's policy
fields explicitly (don't leave them null-meaning-inherit, since there's nothing
to inherit), and append a `WRN-NNN` noting the system file is missing. `--next`
avoids this by always resolving to system mode first.

## A container has no components

A testable container with an empty `components[]` in its ARCH file is unusual
(arch requires a non-empty component list). If it happens, you can't seed unit
tests by component. Seed integration/contract tests from the container's
`owns_api_resources` / `implements_requirements` instead, and add a `WRN-NNN`
noting the thin decomposition. Don't block — but flag it.

## A requirement genuinely warrants no automated test

This is the legitimate **defer** path, not a problem. Examples: a config-load
FR with no behaviour to assert, an operator-manual workflow, an NFR verified by
an external scanner rather than a `TST-NNN`. Defer it with a reasoned
`WRN-NNN` (see `coverage-and-defer.md`). The coverage gate counts it as
covered. Never leave it silently uncovered.

## A `covers` / target id references something that no longer exists

If PRD or ARCH was edited between sessions and a test references an id that's
gone, the Phase-2 upstream-change detection (CLAUDE.md §7) should catch it as a
**removed** id in the delta-review. Ask the user per stale ref: re-point it to
the renamed id, drop the test, or convert it to a deferral. Never silently
delete a `TST-NNN`.

## PRD/ARCH changed after the test strategy exists (re-invocation)

This is a **reconcile**, not a refine. Phase 2 compares each upstream's
`sha256` against `metadata.upstream_provenance`. For each changed upstream,
classify added / removed / modified ids and run the consolidated delta-review
before the interview, per
`sdlc/skills/ux/references/upstream-reconciliation.md`. A new FR in a container
will surface as a requirement-coverage gap (add a test or defer); a removed FR
as a stale ref; a modified FR body as a "the thing you tested changed — revisit
this test" prompt.

## Monorepo mode

If `PRD.metadata.monorepo: true` and `PRD.products` is non-empty, multi-product
mode is deferred for v1.0. Stop and warn; the user may proceed against one
product at a time in single-product mode, with a `WRN-NNN` recording the
limitation. (Mirrors `arch`.)

## Write-permission errors

If writing `docs/TEST-STRATEGY*.yaml`, the state file, or `CLAUDE.md` fails,
report the exact path and error, keep the in-memory answers, and tell the user
their progress is preserved in state once the permission issue is resolved.
Never lose confirmed answers to a failed write — state is written first and
often.

## Very large systems (many containers / many tests)

- In `--next` mode, do one container per invocation; don't try to specify ten
  containers in a single session — it defeats resumability.
- Within a container, if the suite grows past ~30 tests, group the per-item
  drill by tier and offer to batch-confirm the routine unit tests (those with
  unambiguous `✓ found` seeds and a single `covers`), reserving the full
  per-item flow for negative/integration/e2e tests where judgement matters.
- Keep `AskUserQuestion` batches at 2–4; never exceed 4.

## A test spans containers but is proposed in a container file

If a candidate genuinely exercises >1 container, it belongs in the system file
as an `e2e`/`contract` test, not the container file. Move it: add it to
`TEST-STRATEGY.yaml.tests` with `involves_containers`, and (if mid container
interview) note it for the system pass. The validator's `component_ref` /
single-container assumptions make cross-container tests awkward in a container
file by design.

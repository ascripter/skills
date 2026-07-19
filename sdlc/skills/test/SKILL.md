---
name: test
description: >
  Explicitly invoked skill. Two modes: (a) /sdlc:test — system test strategy
  (test-pyramid targets, global coverage thresholds, mock + fixture policy, and
  the cross-container end-to-end + contract suite) written to
  docs/TEST-STRATEGY.yaml; (b) /sdlc:test <container> — per-container test
  strategy (unit + integration tests, fixtures, mocks, coverage target,
  risk-driven negative cases) written to docs/TEST-STRATEGY__<container>.yaml.
  A third form, /sdlc:test --next, auto-advances: it resolves to system mode
  when no TEST-STRATEGY.yaml exists, to the next not-yet-specified drillable
  container otherwise, and reports completion once every drilled container has
  a test strategy. Trigger only on /sdlc:test or a direct natural-language
  request to start the test-strategy skill — never auto-trigger from generic
  chatter about testing. Reads docs/PRD.yaml, docs/DATA-MODEL.yaml,
  docs/ARCH.yaml (plus the target docs/ARCH__<container>.yaml in container
  mode) as required preconditions and refuses to run if any is missing or its
  metadata.status != complete. docs/API.yaml (+ API__*) and docs/UX.yaml
  (+ UX__*) are optional enrichers.
user-invocable: true
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read Write(CLAUDE.md) Write(docs/TEST-STRATEGY.yaml) Write(docs/TEST-STRATEGY__*.yaml) Write(.claude/skills-state/sdlc-test.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-test

Guides the user through a structured interview that produces a validated
**system** `docs/TEST-STRATEGY.yaml` (test-pyramid targets, global coverage
thresholds, mock + fixture policy, CI gating, and the cross-container
end-to-end + contract suite) plus one `docs/TEST-STRATEGY__<container>.yaml`
per drilled container (that container's unit + integration tests, fixtures,
mocks, coverage target, and risk-driven negative cases). Downstream agents —
`task` (turns each `TST-NNN` into a test task) and the code-generation /
verification stages — consume these artifacts as the **executable design
contract** for the tests they write and run.

The test strategy is not prose. Every test is a typed `TST-NNN` item with
`directives` (an arrange/act/assert sketch the codegen agent follows),
`covers` (the upstream ids it verifies), and a machine-checkable `acceptance`
line. The validator enforces a **trace-or-defer coverage contract** so no
requirement, acceptance criterion, or named risk silently goes untested.

## This skill is the *complete* test design — nothing downstream fans it out

`test` is the **terminal authority on which tests exist.** Downstream, `task`
maps **one `TST-NNN` → exactly one test task → one authored test** — a strict
1:1 expansion, never a fan-out. The Stage-14 codegen agent writes the single
test that a `TST-NNN` describes and nothing more. So **every individual test
you want the project to have must be enumerated here, each as its own
`TST-NNN`.** If a feature warrants a happy-path test plus three edge cases plus
an auth-rejection case, that is *five* `TST-NNN` items in this artifact — not
one "test FR-012" item that a later stage is trusted to split apart. There is
no later stage that splits it. (This is the exact trap to avoid: assuming
`/sdlc:task` will "fan out" a single test into many. It won't — it realizes one
task per `TST-NNN`.)

This reframes the coverage gate. The trace-or-defer contract
(`references/coverage-and-defer.md`) requires *at least one* test per upstream
item — that is a **floor, not a quota.** One test per FR turns the validator
green while leaving the actual behaviour barely exercised. The real job is to
ask, for each feature and each named risk, *how many tests does this behaviour
actually need* — then write them all. The mechanics:

- **Phase 3 seeding** (`references/test-discovery.md`) decomposes each feature
  into its full test cluster and mines the upstream sources a one-test-per-FR
  pass skips — including every upstream artifact's `*_warnings`/`WRN-NNN` and
  enumerated edge cases.
- **The per-item flow** (`references/interview-mechanics.md`) proposes that
  *cluster* of candidate tests for an item, not a single token test.
- **The sweep + per-feature sufficiency check** (`references/coverage-and-defer.md`)
  is the safety net before any suite closes.

## What this skill does (at a glance)

The skill runs in **one of two interview modes**, dispatched on the
invocation form — plus a `--next` resolver that picks the right mode for you:

| Invocation                  | Mode                       | Output                                       |
|-----------------------------|----------------------------|----------------------------------------------|
| `/sdlc:test`                | system interview           | `docs/TEST-STRATEGY.yaml`                    |
| `/sdlc:test <container>`    | container interview        | `docs/TEST-STRATEGY__<container>.yaml`       |
| `/sdlc:test --next`         | resolver → one of the above| (whatever the resolved form produces)        |

Both modes follow the canonical 8-phase flow (Phase 1 → Phase 8 below).
State is persisted **after every confirmed batch and after every per-item
test drill-down**, so the user can `EXIT` at any time without losing progress.

**System file vs. container file — what goes where.** Tests are scoped by how
many containers they touch:

- **System** (`TEST-STRATEGY.yaml`): tests whose scope spans more than one
  container or exercises a whole PRD workflow end to end — chiefly the `e2e`
  and `contract` tiers, plus any system-level `load` / `security` /
  `accessibility` test. Also the **global policy** every container inherits:
  `pyramid_targets`, `coverage_threshold`, `mock_policy`, `fixture_strategy`.
- **Container** (`TEST-STRATEGY__<container>.yaml`): tests scoped to one
  container — `unit`, `integration` (within the container), `property`, and
  any container-specific `load` / `security` / `accessibility` case. May
  override the inherited coverage target / mock / fixture policy.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `test-questions.yaml` | Question inventory; each theme tagged with `mode: system | container`. |
| `TEST-STRATEGY.schema.yaml` | Human-readable canonical schema for `docs/TEST-STRATEGY.yaml`. |
| `TEST-STRATEGY__CONTAINER.schema.yaml` | Human-readable canonical schema for `docs/TEST-STRATEGY__<container>.yaml`. |
| `validate_schema.py` | Pydantic v2 validator (system file + every container file + coverage cross-checks). |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector, called in Phase 8. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, EXIT semantics, importance-tier flows. Read on entering Phase 6. |
| `references/test-discovery.md` | How to seed the test suite from PRD + ARCH + DATA + API (system and container). Read in Phase 3. |
| `references/tiering-guidance.md` | General test-strategy guidance: the pyramid, tier selection, mock vs. real, fixtures, coverage-as-signal, AI-codegen-specific advice. Read in Phases 3–6. |
| `references/explaining-choices.md` | The explain-the-why presentation contract for conceptually-loaded decisions (test mix, mocking, coverage, fixtures, per-test tier), written for devs who aren't test engineers. Read on entering Phase 4; applies through Phase 6. |
| `references/coverage-and-defer.md` | The trace-or-defer coverage contract and the WRN-NNN deferral mechanism. Read in Phase 6 (closing each list) and Phase 7. |
| `references/merge-validate.md` | Merge logic for existing artifacts, the cross-check suite, CLAUDE.md pointer rules, the downstream-rejection rule. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations and their handling. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/TEST-STRATEGY.yaml` (project root) | System-level output artifact. |
| `docs/TEST-STRATEGY__<container>.yaml` (project root) | Per-container output artifact. |
| `.claude/skills-state/sdlc-test.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer bullet injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the free-text
field of any `AskUserQuestion` call to abort. State is *always* saved after
each confirmed batch — `EXIT` simply marks the active sub-session
`status: aborted` and stops. There is no `SAVE` command — saving is implicit.

## Invocation dispatch

After reading the `$ARGUMENTS` string, classify the invocation.

**`--next` resolver (runs before the classification below).** If the first
token is `--next` (no other positional args), resolve it to a concrete form,
then proceed exactly as that form:

1. **An in-progress sub-session exists** (any `sessions[*]` with
   `status: in_progress`) → resume it. `--next` means "continue the test
   work"; never skip past unfinished work. Phase 1 handles the resume prompt.
2. **No `docs/TEST-STRATEGY.yaml`** → resolve to **system mode** (as if
   `/sdlc:test`). The global policy must exist before any container can
   inherit it.
3. **`docs/TEST-STRATEGY.yaml` exists with a *testable* container still
   un-specified** → resolve to **container mode** for the next one (as if
   `/sdlc:test <container_id>`). A container is **testable** if it is a unit
   of behaviour worth its own unit/integration suite: `external: false` AND
   `archetype` NOT in the storage/infra set (`primary-database`,
   `secondary-database`, `cache`, `blob-store`, `search-index`,
   `message-bus`) AND not `external-service` — the same set `arch` refuses to
   drill (see `references/edge-cases.md`). A testable container is
   **un-specified** if it has no `docs/TEST-STRATEGY__<container_id>.yaml` on
   disk. It is **ready** only if `docs/ARCH__<container_id>.yaml` exists
   (container mode requires it). Pick the first un-specified, ready, testable
   container in **specification order** (below).
4. **A testable container is un-specified but NOT ready** (no
   `ARCH__<container>.yaml`) → name it and tell the user to run
   `/sdlc:arch <container>` first, then continue with the next ready one.
   If none are ready, abort with that message.
5. **Every testable, ready container already has its
   `TEST-STRATEGY__<container>.yaml`** → print and abort:
   > "All containers have a test strategy. To change one explicitly, invoke
   > `/sdlc:test <container-name>`. Otherwise testing is fully specified — go
   > on with `/sdlc:task`."

Before launching a resolved container interview, confirm the target with one
`AskUserQuestion` so `--next` never silently drops the user into a long
interview:
> "`<k>` of `<n>` testable containers specified. Next un-specified: `<id>`
> (`<archetype>`). Start it, pick a different container, or stop?"

Options: `"Start <id>"` / `"Pick another"` / `"Stop"`. On "Pick another", list
the remaining ready, un-specified containers and let the user choose. On
"Stop", exit cleanly without changing state.

**Specification order.** Test dependencies first so contract tests can name
real provider operations: order by ascending count of outgoing
`depends_on` + `calls` edges in `ARCH.yaml.edges` (providers before
consumers), tie-broken by `ARCH.yaml.containers[]` definition order. Reuse
`arch`'s `state.sessions.system.drill_order` when present; otherwise compute
it. On a cycle or no edges, fall back to definition order. This is a soft
quality heuristic, not a correctness requirement. Persist the resolved order
to `state.spec_order` so `--next` is deterministic across sessions; recompute
only when the container set changed.

Otherwise, classify a non-`--next` invocation:

1. **No arguments** → **system interview mode**. Output: `docs/TEST-STRATEGY.yaml`.
2. **One argument** → **container interview mode**. The argument is a
   `container_id`. It MUST exist in `ARCH.yaml.containers[].container_id`; if
   not, list valid container_ids and abort. It MUST be testable (not external,
   not a storage/infra archetype); if not, explain and abort. Its
   `docs/ARCH__<container>.yaml` MUST exist; if not, tell the user to run
   `/sdlc:arch <container>` first and abort. Output:
   `docs/TEST-STRATEGY__<container>.yaml`.
3. **More than one positional argument, or unknown flag** → print the three
   valid invocations and abort.

The skill **never** modifies a different mode's output. Container mode will
not touch `docs/TEST-STRATEGY.yaml` (except, on first completion of a
container, it may bump `TEST-STRATEGY.yaml.metadata.last_updated` and register
the new file under `container_strategies[]` — the only fields container mode
mutates in the system file). System mode will not touch any
`docs/TEST-STRATEGY__*.yaml`.

## Pre-flight checks (run before everything else)

Do filesystem lookups before the resume check (Phase 1):

```bash
ls docs/API.yaml 2>/dev/null
ls docs/UX.yaml 2>/dev/null
```

`docs/API.yaml` and `docs/UX.yaml` are **optional enrichers** (they sharpen
contract-test and accessibility-test seeding). Record `api_present` /
`ux_present` in the active sub-session state. Their absence is not an error —
note it in `test_strategy_warnings` (WRN-NNN) only if it leaves a gap you
would otherwise have filled (e.g. no contract tests because no API spec).

Required preconditions are checked in Phase 2.

## The 8-phase flow

The phases are the same for both modes; the themes differ. Mode-specific
themes are listed at the end of the relevant phase under **System themes** /
**Container themes**.

### Phase 1 — Resume check

Check for `.claude/skills-state/sdlc-test.state.yaml`:

- If it exists with `status: in_progress` for the **same mode** (and, for
  container mode, the same `container_id`), ask:
  > "I found an unfinished sdlc:test session (`<mode>` mode<, container=X>)
  > from `<last_updated>`. **Resume**, **restart** (discard previous
  > answers), or **discard** (delete state and exit)?"
- If `status: in_progress` but a *different* mode/container is requested, warn
  and offer to start a new sub-session alongside the existing one (the state
  file holds a `sessions:` map keyed by `mode|container_id` — see "Session
  state file").
- If `status: complete` or `aborted` and the target output yaml exists, treat
  this as an update flow — see `references/merge-validate.md`.
- If no state file, continue to Phase 2.

### Phase 2 — Scan inputs

Read upstream artifacts once at startup and validate each via its upstream
validator. **Slice large docs, don't slurp.** `PRD.yaml` and especially
`DATA-MODEL.yaml` are large; when `docs/INDEX.yaml` exists (the project ran
`/sdlc:setup`), look a symbol up in `INDEX.yaml` (or
`python .claude/sdlc/docs_index.py --show <symbol>`) and `Read` only its line
range. Fall back to whole-file reads only when `INDEX.yaml` is absent.
Protocol: `.claude/rules/sdlc-docs-access.md`.

Required upstream artifacts (all MUST exist with `metadata.status: complete`):

1. `docs/PRD.yaml` — validated via `python sdlc/skills/prd/validate_schema.py --path docs/PRD.yaml`.
2. `docs/DATA-MODEL.yaml` — validated via `python sdlc/skills/data/validate_schema.py --path docs/DATA-MODEL.yaml`.
3. `docs/ARCH.yaml` — validated via `python sdlc/skills/arch/validate_schema.py --path docs/ARCH.yaml`.
4. **Container mode only:** `docs/ARCH__<container>.yaml` for the target
   container (the arch validator above already validates every sibling). It
   supplies the components, `implements_requirements`, `acceptance_criteria`,
   `failure_modes`, and `security_concerns` that seed and gate this
   container's tests.

If any validator exits non-zero, or any artifact has
`metadata.status != complete`, **stop**. Print a clear message naming the
offending file and the upstream skill to run.

Optional enrichers (read only if present):

5. `docs/API.yaml` + `docs/API__*.yaml` — operation ids for contract tests.
6. `docs/UX.yaml` + `docs/UX__*.yaml` — surfaces for accessibility / e2e seeds.

**Read `PRD.conventions` (if present).** Honour the binding `conventions`
block before writing anything:

- `conventions.artifact_ids` — which ID families exist and what each prefix
  means. Consult it before emitting `TST-NNN` / `WRN-NNN` or referencing any
  `FR-NNN` / `NFR-NNN` / `ACR-NNN` / `WKF-NNN`. Never invent an id in an
  upstream family; never renumber one.
- `conventions.nfr_propagation` (or similar) — may map NFRs to the tests they
  must drive (a latency budget → a `load` test; a residency constraint → a
  `security` test). Treat such mappings as inputs to Phase 3, not free choices.
- Any other bucket whose `binding: true` — surface it and respect it.

**Monorepo handling (v1.0):** if `PRD.metadata.monorepo: true` AND
`PRD.products` is non-empty, stop and warn that multi-product mode is deferred;
the user may proceed against one product at a time in single-product mode (a
WRN-NNN is appended). See `references/edge-cases.md`.

**Upstream-change detection (re-runs).** If the active mode's output already
exists and carries `metadata.upstream_provenance`, this is a re-run: for each
upstream artifact, compare the recorded `sha256` to its current hash (from
`docs/INDEX.yaml.generated_from[<file>]`, else `sha256(bytes)[:16]`). For
every changed upstream, classify the delta (added / removed / modified ids)
and run the **delta-review pass before the theme interview** per
`sdlc/skills/ux/references/upstream-reconciliation.md` (CLAUDE.md §7). System
mode reconciles against `TEST-STRATEGY.yaml`'s provenance; container mode
against the specific container file's. If every upstream is unchanged, proceed
to the merge flow without a delta-review. Fresh outputs skip this step.

**ARCH `implements_requirements` staleness check (every re-entry, even when
provenance is absent or "unchanged" classification would skip it).** The
highest-impact drift for this skill is an FR promoted into a container's /
component's `implements_requirements` *after* its tests were authored — the
shipped behaviour then has zero tests while every file still says `complete`.
Provenance hashing catches it only when the artifact carries provenance
(legacy or hand-authored files may not), so ALSO run the direct diff on every
invocation, including `--next`:

1. For each existing `TEST-STRATEGY__<cid>.yaml`, collect the current
   `ARCH__<cid>.yaml` requirement set (container + component
   `implements_requirements`) and diff it against the ids the test file
   `covers` or defers.
2. Any requirement in ARCH but neither covered nor deferred is **stale
   coverage** — name it to the user ("`ARCH__backend-api` now claims FR-031,
   FR-044; no test covers them") and offer: author tests now (enter that
   container's flow) / defer with a `WRN-NNN` / skip (leaves the file
   failing validation).
3. The validator's requirement-coverage gate enforces the same set, so a
   skipped stale file will fail `complete` on the next run — the check here
   exists to surface it as a *prompt* at re-entry instead of a late
   validation surprise.

For *what* to seed from which upstream field, see `references/test-discovery.md`.

### Phase 3 — Suite seeding (mode-specific)

A test strategy is fundamentally a coverage problem: enumerate what must be
verified, then choose the cheapest tier that verifies it. Both modes start by
proposing a **draft test suite** from upstream so the user corrects early
rather than inventing from a blank page. Load `references/test-discovery.md`
and `references/tiering-guidance.md` here.

**System mode — cross-container suite + global policy:**

Source candidates, in priority order:

1. **PRD `use_cases.core_workflows` (WKF-NNN)** — each workflow that crosses
   containers (per `ARCH.yaml.edges`) seeds one `e2e` test. Tag `✓ found`.
2. **`ARCH.yaml.edges` of type `calls`** — each cross-container synchronous
   call seeds a `contract` test pinning the provider's response shape (pull
   `via_resource_id` / `via_operation_id` when set). Tag `✓ found`.
3. **PRD `non_functional_requirements`** — latency/throughput targets seed
   `load` tests; auth/PII/residency NFRs seed system-level `security` tests;
   `accessibility` NFRs (+ UX surfaces) seed `accessibility` tests. Tag
   `⚠ inferred`.
4. **Upstream warnings + enumerated edge cases** — scan every upstream
   artifact's `*_warnings`/`WRN-NNN` (PRD, DATA-MODEL, ARCH, API, UX) and PRD
   `use_cases.edge_cases` / `success_metrics.acceptance_criteria` /
   `risks_assumptions` for behaviour a test should pin (a cross-container edge
   case → an e2e/contract test). Tag `⚠ inferred`. See
   `references/test-discovery.md` → "Upstream warnings & enumerated edge cases".
5. **Global policy** — pre-fill `pyramid_targets` (default `~70/20/10`
   unit/integration/e2e, adjusted by `references/tiering-guidance.md` for the
   architecture pattern), `coverage_threshold`, `mock_policy`,
   `fixture_strategy`. Tag `⚠ inferred`.

**Container mode — unit + integration suite:**

Source candidates, in priority order:

1. **`ARCH__<container>.components[]`** — each component seeds `unit` tests
   for its `responsibilities` and `acceptance_criteria`. Tag `✓ found`.
2. **`ARCH__<container>.internal_edges`** — `calls` edges between components
   seed `integration` tests. Tag `✓ found`.
3. **`implements_requirements` (FR/NFR)** on the container + its components —
   each requirement must be covered by at least one test (the coverage gate).
   Tag `✓ found`.
4. **`failure_modes` + `security_concerns`** (container + component) — each
   seeds a negative / abuse-case test (`covers` or `targets_*`). Tag `✓ found`.
5. **DATA entities the components trace** — repository/serializer components
   seed round-trip and (de)serialization tests; DATA invariants/constraints
   seed `property` and validation tests. Tag `⚠ inferred`.
6. **Upstream warnings + enumerated edge cases** — scan the relevant
   `*_warnings`/`WRN-NNN` and DATA invariants/constraints for behaviour scoped
   to this container that a test should pin. Tag `⚠ inferred`. See
   `references/test-discovery.md` → "Upstream warnings & enumerated edge cases".

**Seed the full cluster, not one test per item.** Each component/requirement
usually warrants several tests (happy path, one per acceptance criterion,
boundary/edge, invalid-input/error, each failure mode and security concern) —
`references/test-discovery.md` → "How many tests does a feature need?" is the
decomposition. Remember nothing downstream multiplies these for you.

Present the draft. Each `⚠ inferred` candidate gets its own AskUserQuestion
call. Persist confirmations to `state.sessions[<key>].defined_tests`. The test
suite is a `critical synthesis: true` theme: **after the per-item loop closes
in Phase 6, run the scope-completeness sweep** (seed from ALL upstream ID
families — including `*_warnings` and edge cases — + project-type heuristics),
per `references/coverage-and-defer.md`.

### Phase 4 — Structural questions

**Load `references/explaining-choices.md` now.** Several decisions in this and
the next phases are *conceptually loaded* — they carry a jargon term the user
may not know AND silently hurt the project if defaulted wrong (the test mix,
mocking policy, coverage floor, fixtures, and each test's tier). Every question
carrying an `explainer:` block in `test-questions.yaml` is one of these. For
those, do **not** present a bare label list or a terse draft→approve: present
the explain-the-why contract — a plain-language frame, a recommendation tied to
*this* project's upstream facts, a plain-language gloss on every option, and a
"not sure — explain" escape hatch. Assume the user may be a capable developer
who is **not** a test engineer; teach the choice in a sentence or two, but let
an expert one-click the recommendation and move on. This is the fix for "it
recommended pyramid percentages but never said why."

Mode-specific scalars that determine the *shape* of the output, asked before
any theme batch:

**System mode:**

1. `test_approach.pyramid_targets` — proportions per tier (e.g.
   `{unit:'~70%', integration:'~20%', e2e:'~10%'}`). Pre-fill from
   architecture pattern (microservices/event-driven lean heavier on
   contract/integration; a monolith leans on unit). Present as `⚠ inferred`.
2. `coverage_threshold.line_pct` (+ optional `branch_pct`) — the global floor
   the verification stage must meet. Pre-fill a sane default (e.g. 80) and let
   the user adjust.

**Container mode:**

1. `coverage_target` — inherits the system threshold unless the user
   overrides for this container (e.g. a thin adapter may warrant less; a
   money-handling service more).
2. `mock_policy` / `fixture_strategy` — inherit unless the container needs a
   refinement (e.g. "use testcontainers Postgres instead of the global
   in-memory default").

Persist all structural answers to state before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme**:

- `✓ found` items can be batch-accepted with `ok`.
- `⚠ inferred` items must be confirmed or corrected **one by one** in their
  own AskUserQuestion call. No batch-acceptance — this is the hallucination
  guard.

Write confirmed values with `<field>_confidence: confirmed` (explicit pick) or
`inferred` (`⚠` accepted as-is) where the schema declares a confidence sibling.

### Phase 6 — Theme interview

Walk the themes in `test-questions.yaml` order. Themes are tagged
`mode: system | container`; load only the active mode's themes.

#### System themes (when `/sdlc:test` was invoked)

1. `test_approach` — `high` (pyramid targets + rationale + ai-builder notes).
2. `coverage_threshold` — `high` (global line/branch floor + per-container
   overrides + rationale).
3. `global_policy` — `high` (`mock_policy`, `fixture_strategy`,
   `test_data_strategy`, `shared_infrastructure` — the named deliverables the
   policy prose implies (conftest/factories; the `task` skill builds them as
   one test-infrastructure task per container), `test_file_convention` — the
   path template test-task `target_files` derive from, optional
   `ci_integration` + `environments`).
4. `system_suite` — `critical` per item, `synthesis: true`. For each test:
   `tst_id`, `name`, `tier` (∈ e2e / contract / load / security /
   accessibility), `description`, `directives`, `covers` (FR/NFR/ACR/WKF),
   `involves_containers`, `setup`, `acceptance` (+ `gating: false` with its
   marker directive for an out-of-band eval; `priority` is retired — D2).
   Each test's status walks `draft → confirmed`. After the per-item loop, run the
   scope-completeness sweep. Every cross-container PRD `WKF-NNN` must be
   exercised by some e2e test or deferred — Phase 7's workflow-coverage check
   enforces this.

#### Container themes (when `/sdlc:test <container>` was invoked)

1. `coverage_target` — `high` (line/branch goal; inherits system unless
   overridden).
2. `container_policy` — `med` (`mock_policy` / `fixture_strategy` /
   `test_environment` overrides; null ⇒ inherit system).
3. `container_suite` — `critical` per item, `synthesis: true`. For each test:
   `tst_id`, `name`, `tier` (∈ unit / integration / property / contract /
   load / security / accessibility), `description`, `component_ref` (a
   `components[].component_id` from `ARCH__<container>.yaml`, when the test
   targets one), `targets_work_units` (the component `work_units[].name`
   entries this test exercises — THE SUBJECT SEAM, usually one; work units are
   name-addressed and unique only within their component, so `component_ref` is
   required alongside; seed one unit test per work unit, mirroring `task`'s
   per-work_unit slicing, and carry the subject from birth — for unit-tier
   tests it is require-or-defer at `complete`), `directives`, `covers`
   (FR/NFR/ACR), `targets_failure_mode` / `targets_security_concern` (the ARCH
   risk id this negative case exercises), `setup`, `fixtures`,
   `mocks`, `acceptance` (+ `gating: false` for an out-of-band eval;
   `priority` is retired — D2). Run the scope-completeness sweep after the per-item
   loop. The coverage gate (Phase 7) requires every container/component
   requirement, acceptance criterion, failure mode, and security concern to be
   covered or deferred; component work units are an **advisory** coverage layer
   (seed one test per work unit; a gap warns but never blocks — a trivial getter
   may go untested or be deferred with a `WRN-NNN`). A pre-1.2 artifact's
   `targets_operation` (retired `OPN-NNN` family) is parsed as a deprecated
   alias — the validator warns but never blocks.

#### Tier mechanics

Each question carries an `importance: med | high | critical` field. Tier flows
are identical to `sdlc:arch` / `sdlc:api` / `sdlc:data` — see
`references/interview-mechanics.md` (which points at the canonical spec in
`sdlc/skills/prd/references/importance-flows.md`).

The three non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended option** in
   their `AskUserQuestion` call. They cannot be silently accepted.
2. State is written after **every confirmed batch, mini-section, and per-item
   test completion** — not at theme boundaries.
3. **Loaded decisions get the explain-the-why treatment.** Any question with an
   `explainer:` block (`mock_policy`, `fixture_strategy`, each suite's per-test
   `tier`, plus the Phase-4 `pyramid_targets` / coverage floors) is presented
   per `references/explaining-choices.md`: plain-language frame, project-tailored
   recommendation, glossed options, and a "not sure — explain" escape hatch.
   In the per-test `tier` challenge (the "push-down" step), state *why* the
   cheaper tier gives the same confidence in concrete terms (speed, and how
   clearly a failure points at the cause) — never just the tier label.

### Phase 7 — Write & validate

Write or merge the active mode's output yaml:

- System mode → `docs/TEST-STRATEGY.yaml`. Per-container files are NOT created
  here.
- Container mode → `docs/TEST-STRATEGY__<container>.yaml`. On first completion
  of a container, register it under `TEST-STRATEGY.yaml.container_strategies[]`
  (`{container_id, file_path}`) and bump `TEST-STRATEGY.yaml.metadata.last_updated`
  — the only fields container mode mutates in the system file.

When writing, (re)write the active output's `metadata.upstream_provenance`:
one entry per upstream artifact consumed this run, each
`{file, session_id, last_updated, sha256}` (`sha256` from
`docs/INDEX.yaml.generated_from`, else `sha256(bytes)[:16]`). Replace-on-write.
See CLAUDE.md §7.

**Derived-count refresh (CLAUDE.md §8).** Don't write test counts ("181
tests", "14 unit / 5 integration") into prose fields (`overview`, notes) or
YAML header comments — the `tests` list is the source of truth and prose
counts go stale on the next merge. When updating a file that already carries
such counts, re-derive or delete them in the same write; a merge/propagation
pass that changes the `tests` list but not the prose describing it is
incomplete.

Then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/TEST-STRATEGY.yaml
```

The validator validates `docs/TEST-STRATEGY.yaml` plus every sibling
`docs/TEST-STRATEGY__*.yaml` and runs the cross-check suite. Coverage, trace,
and ID-format failures force `metadata.status: draft`; upstream-status issues
emit warnings only. The full check list (and the merge logic + recovery flow
on `[FAIL]`) lives in `references/merge-validate.md`; in summary:

**Coverage** (block complete — trace-or-defer, see `references/coverage-and-defer.md`).
The validator enforces the *floor*: ≥1 test (or a deferral) per gated item.
Passing it is necessary, not sufficient — run the per-feature sufficiency check
in `references/coverage-and-defer.md` so a green gate doesn't hide a feature
tested only on its happy path.

- **System workflow coverage** — every cross-container PRD `WKF-NNN` is in
  some system test's `covers` OR deferred via a `test_strategy_warnings`
  WRN-NNN.
- **Container requirement coverage** — every `FR-NNN`/`NFR-NNN` in the
  container's (+ components') `implements_requirements` is in some test's
  `covers` OR deferred.
- **Container acceptance coverage** — every component that declares
  `acceptance_criteria` (and the container itself) is targeted by ≥1 test
  (`component_ref`) OR deferred.
- **Container risk coverage** — every container/component `failure_modes[].id`
  and `security_concerns[].id` is targeted by some test
  (`targets_failure_mode` / `targets_security_concern` / `covers`) OR deferred.

**Paired deferral** (CLAUDE.md §6a) — deferring a behaviour's test that has real
code obliges the matching impl-task deferral downstream: name the behaviour
(work_unit / FR), not just a `TST-NNN`, in the WRN so `task`'s symmetry check can
force the impl task post-MVP. Don't defer a test just because the code is hard to
exercise and let it ship untested (see `references/coverage-and-defer.md`).

**ID-prefix formats** (block complete):

- `TST-NNN` on every test's `tst_id` — unique within the artifact AND
  **globally unique across the system file + every container file** (one
  continuous counter, `state.last_ids_global.TST`; downstream
  `Task.test_refs` assumes a single TST namespace).
- `WRN-NNN` on every `test_strategy_warnings` entry (per-artifact space).
- `FR-NNN`/`NFR-NNN`/`ACR-NNN`/`WKF-NNN` on `covers` entries, each resolving
  to an upstream PRD id (FR→functional_requirements, NFR→non_functional_requirements,
  ACR/WKF→PRD token scan).

**Trace integrity** (block complete):

- Every `component_ref` resolves to a `components[].component_id` in the
  matching `ARCH__<container>.yaml`.
- Every `targets_failure_mode` / `targets_security_concern` resolves to an id
  in that `ARCH__<container>.yaml`.
- Every `involves_containers` entry (system tests) resolves to an
  `ARCH.yaml.containers[].container_id`.

**Non-blocking warnings**: missing optional enrichers; upstream
`metadata.status != complete` seen by a standalone validator run.

Set `metadata.status`:

- `"complete"` — only when all required fields are filled, the validator
  passes `[OK]`, AND every coverage / trace / ID-format check passes.
- `"draft"` — on early EXIT, when any required field is null, or when any
  check fails.

### Phase 8 — CLAUDE.md pointer & close

Call `set_claude_md_pointer.py` to inject or update this skill's bullet in the
shared `## SDLC Documents` section of the project-root `CLAUDE.md` (create the
section if missing). For bullet detection and append behavior, see
`references/merge-validate.md`.

**Refresh the navigation index.** If `.claude/sdlc/docs_index.py` exists, run
`python .claude/sdlc/docs_index.py` after writing so `docs/INDEX.yaml`
reflects the new content right away (the setup hook also does this, but a hook
added mid-session only activates next session). Harmless no-op if not installed.

After the CLAUDE.md write succeeds: set the active sub-session's
`status: complete` in the state file (keep the file as audit trail), tell
the user where the artifacts live and what `--next` would do, and point at
what comes next:

> This container's test strategy is complete. Run `/sdlc:test --next` for the
> next container, or `/sdlc:task` once every container has a strategy (it
> consumes `docs/ARCH.yaml` + `docs/TEST-STRATEGY.yaml` and the per-container
> files).

## Test tiers — the typed vocabulary

The tier is the single most consequential field on a test: it tells the
downstream codegen agent *what kind of harness* to write and the verification
stage *how to run it*. Eight tiers (the same enum the DATA-MODEL `TestTier`
uses):

| Tier            | Scope & codegen implication                                              |
|-----------------|--------------------------------------------------------------------------|
| `unit`          | One component/function in isolation; collaborators mocked. Fast, many.   |
| `integration`   | Two+ components inside one container, real wiring; external deps faked.  |
| `e2e`           | Whole workflow across containers, real or near-real environment.         |
| `contract`      | Pins a provider/consumer interface shape (API operation, event schema).  |
| `property`      | Generative/invariant testing over a space of inputs.                     |
| `load`          | Throughput/latency under volume — verifies an NFR performance target.    |
| `security`      | Abuse/negative case — authz, injection, PII leakage, a named threat.     |
| `accessibility` | a11y conformance for a UX surface (WCAG, keyboard, screen-reader).       |

Choosing the tier is a cost/confidence trade-off — push verification to the
cheapest tier that still proves the requirement. `references/tiering-guidance.md`
is the canonical guidance.

## Session state file

Path: `.claude/skills-state/sdlc-test.state.yaml`

Like `arch`, `test` keeps **per-mode sub-sessions** in one file:

```yaml
session_file_version: "1"
skill_version: "1.1"
last_updated: <iso8601>
spec_order: []                  # container_ids in --next order (providers first)
last_ids_global: {}             # ONE continuous TST space across ALL artifacts,
                                # e.g. {TST: 181}. Whichever sub-session mints the
                                # next test increments THIS counter. Reconcile to
                                # max(all on-disk TEST-STRATEGY*.yaml, state) on
                                # every invocation. TST-001 must exist at most
                                # once across system + all container files.

sessions:
  system:                       # /sdlc:test
    session_id: <uuid4>
    started_at: <iso8601>
    last_updated: <iso8601>
    status: in_progress         # in_progress | complete | aborted
    mode: system
    pre_fill_confirmed: false
    last_ids: {}                # writer-managed PER-ARTIFACT counters — {WRN: 2}.
                                # TST is NOT here: it lives in last_ids_global.
                                # Increment, format <PREFIX>-{:03d}, persist.
    completed_themes: []
    skipped_themes: []
    todo_themes: []
    pending_themes: []
    current_theme: null
    current_test: null          # during the system_suite drill-down
    defined_tests: []           # [{tst_id, tier, status: draft|confirmed, source}]
    partial_answers: {}         # mirrors docs/TEST-STRATEGY.yaml structure

  "container|backend-api":      # /sdlc:test backend-api
    session_id: <uuid4>
    started_at: <iso8601>
    last_updated: <iso8601>
    status: in_progress
    mode: container
    container_id: backend-api
    pre_fill_confirmed: false
    last_ids: {}                # this container file's WRN space only;
                                # TST comes from top-level last_ids_global
    completed_themes: []
    skipped_themes: []
    todo_themes: []
    pending_themes: []
    current_theme: null
    current_test: null
    defined_tests: []
    partial_answers: {}         # mirrors docs/TEST-STRATEGY__backend-api.yaml
```

Rules:

- Generate `session_id` (UUID4) on first creation of each sub-session.
- Update top-level `last_updated` and the sub-session `last_updated` on every
  write.
- Write the file **after every confirmed batch, mini-section, and per-item
  step**, including pre-fill confirmations and Phase 3 suite confirmation.
- On `EXIT`: set the *active* sub-session `status: aborted`, write
  `partial_answers`, confirm, stop. Other sub-sessions untouched.
- On Phase 8 completion: set the active sub-session `status: complete`; keep
  the file.
- **`TST-NNN` is ONE GLOBAL id space** across the system file and every
  container file — downstream `Task.test_refs` (and every other TST
  consumer) assumes a single namespace, so per-file restarts at `TST-001`
  produce colliding ids that only surface when a task references the wrong
  test. The counter is writer-managed at the **top level** of the state file
  (`last_ids_global.TST`), shared by all sub-sessions: whichever sub-session
  mints the next test increments the same counter. **Reconcile on every
  invocation:** scan ALL on-disk `TEST-STRATEGY*.yaml` files and sync
  `last_ids_global.TST` to `max(all on-disk, state)` before minting — a file
  may have been hand-edited or authored by an older skill version. The
  validator enforces global uniqueness (blocking).
- **`WRN-NNN` stays per-artifact** (the universal warnings convention),
  writer-managed in the active sub-session's `last_ids.WRN`. There is no
  interview question for warnings; append them at write time and bump the
  counter. Reconcile on resume: if the on-disk file has a higher `WRN-NNN`
  than `last_ids.WRN`, sync to `max(on_disk, state)` before appending, so
  EXIT/resume never produces gaps or duplicates.
- **`metadata.changelog`** is append-only, most-recent first; one line per
  write. The validator only type-checks it.
- The validator ignores this file — it validates only the output yamls.

**Source of truth on resume:** the on-disk yaml is authoritative for
*answers* (it may have been hand-edited); the state file is authoritative for
*interview progress*. On resume, load the on-disk yaml first as baseline, then
layer the sub-session's `partial_answers` on top. If they conflict on the same
key, ask the user — never silently overwrite.

## Edge cases

For unusual situations (a required upstream missing or in draft; a testable
container whose `ARCH__<container>.yaml` doesn't exist yet; a container with no
components; a requirement that genuinely warrants no automated test; PRD/ARCH
edited between sessions; monorepo mode; write-permission errors; a very large
system) → `references/edge-cases.md`.

## Style of conversation

The test interview can be long. Keep it humane:

- **Assume the user may not be a test engineer.** For the conceptually-loaded
  decisions (test mix, mocking, coverage, fixtures, per-test tier), teach the
  choice in one or two plain sentences and say *why you recommend what you do
  for this project* — don't hand over jargon labels and hope. The depth lives
  behind a "not sure — explain" option; an expert can one-click past it. Full
  contract: `references/explaining-choices.md`.
- Lead with the draft suite — the user edits a list, they don't invent one.
- Keep `AskUserQuestion` batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme and test boundary ("That's the
  `backend-api` suite — 14 unit, 5 integration, 3 negative. Coverage gate:
  green. Next: `web-frontend`.").
- Always call out that candidate tests were synthesized from PRD + ARCH +
  DATA + API (including upstream warnings and enumerated edge cases) — don't
  pretend they came from nowhere.
- When a feature gets only one test, say so and ask whether its edge/error
  cases need their own tests — one test per feature is a floor, not the goal,
  and no downstream stage will add the rest.
- For each negative test, name the failure mode / security concern it
  exercises so the user sees the risk→test link.
- After all themes, congratulate briefly and move to write & validate.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 draft suite as-is. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs a `WRN-NNN` to `test_strategy_warnings`. |
| `defer <id>` | Mark an upstream id (FR/NFR/ACR/WKF/failure-mode/concern) intentionally untested; logs the WRN-NNN deferral that satisfies the coverage gate. |

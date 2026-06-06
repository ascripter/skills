# Task discovery — seeding the task graph from upstream (sdlc-task)

Read this in Phase 3. A task graph should never be invented from a blank page:
almost every work unit is *implied* by an upstream artifact. Your job is to
enumerate those implications, pick the right `kind`, and let the user correct a
draft list — not to brainstorm tasks freehand.

The governing model is the demo PRD's **FR-013 (Task Breakdown)**: per-container
subgraphs whose tasks are each "scoped to one CMP-### or contract, with explicit
inputs/outputs/acceptance" and where "test tasks (implementing TST-###) are
first-class alongside implementation tasks." Seed exactly that.

---

## Container mode — `docs/TASKS__<container>.json`

Source candidates, in priority order. Tag `✓ found` (direct from an upstream id)
or `⚠ inferred` (derived).

| Upstream signal | Seeds | kind | Scope field |
|---|---|---|---|
| `ARCH__<cid>.components[]` (each component) | one impl task (coarse) or one per responsibility/endpoint (fine) | `implementation` | `component_ref` = component_id |
| `TEST-STRATEGY__<cid>.tests[]` (each `TST-NNN`) | one first-class test task | `test` | `implements_tests` = [TST-NNN] |
| `ARCH__<cid>.internal_edges` (`calls`/`reads`/`writes`) | a wiring task (or fold into the consumer's impl task) | `integration` | `depends_on` the two components' tasks |
| container package skeleton | one skeleton task | `scaffold` | — (usually the root dep) |
| components tracing DATA entities (`traces_data_entities`) | a repository/migration task | `migration` | `touches_entities` |
| components tracing API operations (`traces_api_operations`) | an endpoint/contract task | `implementation` | `touches_operations` |
| `CFG-###`/`SCT-###` the container needs | a config-wiring task | `config` | — |

Each component is the unit of implementation work. At **coarse** granularity,
one `implementation` task per component; at **fine**, split by the component's
`responsibilities` / owned endpoints / methods (see `granularity-and-ordering.md`).

`implements` (FR/NFR) on an impl task = the subset of that component's
`implements_requirements` the task realizes. Keep it a subset — the validator
rejects an `implements` outside the component/container's declared requirements.

## System mode — `docs/TASKS.json`

| Upstream signal | Seeds | kind | Scope field |
|---|---|---|---|
| repo/monorepo shape (PRD `conventions`, ARCH containers) | workspace + root tooling + CI skeleton | `scaffold` | `involves_containers: []` |
| `ARCH.yaml.edges` cross-container `calls`/`depends_on` | one wiring task per edge | `integration` | `involves_containers` = both endpoints |
| `TEST-STRATEGY.yaml.tests[]` (e2e/contract `TST-NNN`) | one first-class test task each | `test` | `implements_tests` = [TST-NNN] |
| shared library / shared contract used by ≥2 containers | a shared-build task | `scaffold` or `migration` | `involves_containers` = consumers |
| deploy handoff | a scaffolding task for `/sdlc:deploy` | `deploy-prep` | — |
| repo-level docs/readme | a docs task | `docs` | — |

`build_order` is seeded from the specification order (providers before
consumers) — see `granularity-and-ordering.md`.

---

## Seeding rules that keep the graph honest

- **One scope per task.** An implementation task targets exactly one component or
  one contract. If a candidate spans two components, it is two tasks (or an
  `integration` task between them). This is what makes the codegen fan-out clean
  — each sub-agent sees only its task plus the contracts it touches.
- **Test tasks are peers, not riders.** Do not bury "write the tests" inside an
  implementation task. Every `TST-NNN` gets its own `test` task so the coverage
  gate can see it and the codegen heal-loop can run it independently. (A `test`
  task typically `depends_on` the implementation task whose code it exercises.)
- **Name provenance.** When you propose a candidate, say which upstream id it
  came from. A task seeded from nowhere is a hallucination; surface it as
  `⚠ inferred` and make the user confirm.
- **`⚠ inferred` never auto-accepts.** Scaffold tasks, build_order, and
  DATA/API-derived tasks are inferences — each surfaces as the position-1 option
  in its own AskUserQuestion call.
- **Don't pad.** If a container has three components, three impl tasks is
  correct — do not manufacture a fourth to look thorough. The anti-padding rule
  from the scope-completeness sweep applies to the initial draft too.

After the draft is confirmed and the per-item loop closes, the
scope-completeness sweep (`coverage-and-defer.md`) is your safety net for work
implied by an upstream id that the direct seeding missed.

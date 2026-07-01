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

| Upstream signal | Seeds | kind | Scope / ref field |
|---|---|---|---|
| `ARCH__<cid>.components[].work_units[]` (each `work_units[].name`) | **one impl task per work_unit** (always atomic) | `implementation` | `component_ref` = component_id + `target_symbol` = the work_unit name + one `target_files` |
| `ARCH__<cid>.components[]` with **no** work_units | **no impl task** (pure plumbing; no coarse whole-component fallback) | — | — |
| `TEST-STRATEGY__<cid>.tests[]` (each `TST-NNN`) | **one first-class test task per `TST-NNN`** (never grouped) | `test` | `implements_tests` = [TST-NNN] |
| `ARCH__<cid>.internal_edges` (`calls`/`reads`/`writes`) | a wiring task (or fold into the consumer's impl task) | `integration` | `depends_on` the two components' tasks |
| container package skeleton | one skeleton task | `scaffold` | — (usually the root dep) |
| DATA entities the container persists (a `repository` component's `traces_data_entities`) | the schema/DDL + migration task — the **entity realization** unit, distinct from the repository code that queries it | `migration` | `touches_entities` = [EntityName] |
| API operations of an owned resource (`traces_api_operations`, or all ops of a `traces_api_resources`) | the endpoint/contract work (often folded into the controller's impl task) | `implementation` | `touches_operations` = [operation_id] |
| UX surfaces the container renders (`owns_ux_surfaces` / a component's `traces_ux_surfaces`) — frontend containers | the screen/command impl task | `implementation` | `implements_surfaces` = [SCR-NNN] |
| `DESIGN__tokens.yaml` (token_based_ui) — frontend containers | the theme/token wiring task | `design` | `target_files` = theme/token files |
| `DESIGN__assets.yaml` (asset_pipeline) — frontend containers | asset-folder scaffold + one generation-brief sidecar per asset | `design` | `touches_assets` = [AST-NNN] |
| `config_loader` component / env settings the container needs | a config-wiring task (secrets backends are owned by `/sdlc:deploy`) | `config` | — |

The **work_unit** is the unit of implementation work: one `implementation` task
per `work_units[].name`, scoped `component_ref` + `target_symbol: <that name>` +
a single `target_files` entry, with the unit's own traces
(`traces_api_operation` → `touches_operations`, `implements_requirements` →
`implements`, `touches_entities`) copied onto the task. A component that declares
no work_units yields no implementation task — there is no coarse whole-component
fallback. The work-unit coverage gate holds you to realizing every
`work_units[].name` by exactly one task's `target_symbol` (or deferring it) — see
`coverage-and-defer.md`. See `granularity-and-ordering.md` for the full model.

When ARCH declares no work_units on a non-trivial component, that is an upstream
gap: the right fix is `/sdlc:arch <container>` to add `work_units[]`, not to
invent a method breakdown here (inventing structure at the task stage is the
hallucination the provenance guard exists to prevent). Note it in a `WRN-NNN`.

`implements` (FR/NFR) on an impl task = the subset of that component's
`implements_requirements` the task realizes. Keep it a subset — the validator
rejects an `implements` outside the component/container's declared requirements.

**Name every contract a task realizes.** The Stage-14 code agent sees only a
task's TSK + the contracts it touches, so put the upstream ids on the task:
`touches_operations` (operation_ids — NOT the resource_id; the validator rejects
a bare resource), `touches_entities` (DATA entity names), `implements_surfaces`
(SCR-NNN), `implements` (FR/NFR), `implements_tests` (TST-NNN). These are the
sdlc-typed equivalent of the demo `Task.implements_refs` flat list — kept per
family so each gets a validated prefix (CLAUDE.md §4). A task that realizes a
component covers everything that component traces **transitively** (surfaces /
operations / entities / requirements), so you do not have to re-list every one on
every task — but the coverage gate (`coverage-and-defer.md`) will hold you to
realizing every owned surface / operation / entity / requirement **or deferring
it**. Work_units are the exception: they get **no** transitive credit — each is
realized only by a task naming it in `target_symbol` (that is the atomicity gate).

**Seed `acceptance` from the component.** `ARCH__<cid>` components (and the
container) carry `acceptance_criteria` — the done-conditions ARCH declared for
the downstream task/test agents. Seed each component-scoped task's `acceptance`
from its component's `acceptance_criteria` rather than re-inventing them, so the
ARCH-declared contract isn't silently lost.

### Ground `target_files` in the component's `code_location`

`ARCH__<container>.yaml` gives every component a `code_location` — the
repo-relative directory(ies) its source lives in (the component → code-module
seam). **Seed each component-scoped task's `target_files` from it** rather than
inventing paths:

- An `implementation` task for a work_unit on component `C` → **exactly one**
  `target_files` entry: the file under `C.code_location` that houses its
  `target_symbol` (e.g. `code_location: ["src/auth/"]` +
  `target_symbol: "AuthService.authenticate"` → `target_files:
  ["src/auth/service.py"]`).
- A `test` task → the test file(s), typically mirroring the component's location
  under the project's test root (`tests/auth/test_service.py`).

The validator emits an advisory WARNING when a component-scoped task's
`target_files` fall outside the owning component's `code_location` (directory-
level) — that warning is the signal that codegen would write outside the
component's declared home. If a task genuinely needs to write outside (a
cross-cutting file), either widen the component's `code_location` in ARCH or make
it an `integration`/system task. **`target_files` is the raw write-target list;
`outputs` stays the contract-level result** (an exported symbol, an applied
migration, a passing suite) that downstream tasks depend on — fill both.

A component with no `code_location` (ARCH left it blank) means you have nothing
to ground against — note it (`WRN-NNN`) and either ask the user for the path or
fall back to the conventional location for the component's archetype, so a
target path is still chosen deliberately rather than invented at codegen time.

### DESIGN realization (frontend containers)

`DESIGN.yaml` + its sub-files are how the generated app gets its look — the
Stage-14 code agent consumes DesignSystemSpec for "theme/token/asset
scaffolding" (demo FR-014). `task` is where that work becomes concrete tasks.
Read DESIGN only for a container that **owns UX surfaces** (a frontend); skip it
for headless / backend containers.

- `functional_structure` includes `token_based_ui` → seed one `design` task that
  writes the theme/token files (e.g. `tailwind.config`, CSS custom-properties,
  a DTCG token export). This is the **hard** design gate for a token-based
  frontend: ship the task or defer it with a reasoned `WRN-NNN`.
- `functional_structure` includes `asset_pipeline` (or `aesthetic_direction.
  requires_custom_assets`) → seed a `design`/`scaffold` task for the asset folder
  layout + manifest, and one generation-brief sidecar task per `AST-NNN` in
  `DESIGN__assets.yaml` (`touches_assets`). AICF does NOT generate the binary
  assets (post-MVP); the brief sidecar is the actionable deliverable, so asset
  realization is **advisory** — surface it, don't block on it.
- `headless` → no-op (mirrors headless UX).

A shared design-token package consumed by **≥2** frontends in a monorepo is
homeless cross-container work — author it as a system `design` task in
`docs/TASKS.json`, leaving each frontend's theme *wiring* a container `design`
task that depends on it.

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

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
| DATA entities the container persists (a `repository` component's `traces_data_entities`) | the schema/DDL + migration task — the **entity realization** unit, distinct from the repository code that queries it. **Non-DDL paradigms** (file_native, document without migrations): entity realization is the `schema_model` component's `implementation` task(s) with `touches_entities` instead — seed NO migration task; the entity-coverage gate accepts either | `migration` | `touches_entities` = [EntityName] |
| an ARCH component with `work_units: []` + a **derivation-rule `work_units_waiver`** (e.g. "one authoring task per template file under templates/") | **expand the rule**: one authoring task per file it yields — the waiver is a promise addressed to this skill, not a deferral (see `coverage-and-defer.md`) | `implementation` (`unit_kind: content`) | `component_ref` = component_id; one `target_files` per task under its `code_location` |
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

**Every work_unit kind maps to `kind: implementation`.** A unit may carry a
`kind` (`callable` default, or `module` / `content` / `tooling` — demo FR-013
v1.30 deliverable classes). The task derivation is identical for all four —
same `component_ref`/`target_symbol`/one-`target_files` shape, same coverage
gates — because a non-callable unit is still exactly one deliverable in one
file. Copy the unit's `kind` onto the task as `unit_kind` (omit for
`callable`): it is the codegen agent's rendering-mode switch (render a method
vs. emit the module/content/tool file), nothing more. Do NOT map content →
`chore` or tooling → some other kind — that would strip the atomicity pins.

### Embed the per-task specifics (schema v1.3/v1.4 — the self-sufficiency contract)

The codegen agent works from **the task alone**: per-task specifics are
embedded on the task at seeding/write time; only container-general facts (tech
stack, coverage targets) stay upstream. This deliberately diverges from the
demo's "inherit the contract live" — a per-task lookup in a huge ARCH file is
the wrong cost model, and the §7 upstream-provenance re-run reconciles the
embedded copies when ARCH/TEST-STRATEGY move (the validator's drift advisory,
check 20, names exactly which tasks to re-confirm).

- **`interface_contract`** (every `implementation` task; non-callable
  `unit_kind` exempt — the file IS the contract):
  - unit **declares** `inputs`/`output`/`raises` (explicit empties count) →
    copy them verbatim, `source: work_unit`; copy `signature` only when set.
  - unit **defers** via `traces_api_operation` → resolve the operation in
    `API__*.yaml` and render its request/response/exception shape into
    `inputs`/`output`/`raises`, with `source: api_operation` +
    `operation_id`. When no `API__*.yaml` is readable, render the best
    contract the UX/DATA slices support and note a `WRN-NNN`.
  - Also copy the unit's `summary` → `unit_summary`.
- **`test_spec`** (every `test` task): copy the TST entry's `tier`,
  `directives`, `acceptance`, and `covers` from
  `TEST-STRATEGY__<cid>.yaml` — the test-authoring agent must not need to
  open it.
- **`operation_contract`** (v1.4; every `integration` task naming
  `touches_operations`): one entry per operation — copy its
  `operation_id`/method/path and the request/response DTO slices + error
  responses from the owning `API__*.yaml`.
- **`entity_slice`** (v1.4; every `migration` task naming `touches_entities`):
  one entry per entity — copy its field defs, table-level constraints, and the
  relationships it participates in from `DATA-MODEL.yaml`.
- **`design_spec`** (v1.4; every `design` task): copy the token groups the
  theme/token file must encode from `DESIGN__tokens.yaml`, and/or the full
  `generation_brief` of every `touches_assets` AST from `DESIGN__assets.yaml`.
- **`config_keys`** (v1.4; every `config` task): enumerate every settings key
  (name / source / default / secret flag / one-line description). Ground them
  in ARCH (`persistence_bindings`, external edges, `deployment`), API auth
  schemes, and the PRD's integration list — the codegen agent must not invent
  keys.

The validator blocks `complete` on an artifact missing an embed its version
requires (check 18: v1.3 for `interface_contract`/`test_spec`, v1.4 for the
four kind embeds).

When ARCH declares no work_units on a non-trivial component, that is an upstream
gap: the right fix is `/sdlc:arch <container>` to add `work_units[]`, not to
invent a method breakdown here (inventing structure at the task stage is the
hallucination the provenance guard exists to prevent). Note it in a `WRN-NNN`.

**Count work_units by PARSE, never by grep.** Before you conclude a component has
no work_units — a claim that gates seeding, readiness, or a refusal — derive the
count from a real YAML parse. `work_units[]` items are legitimately block-style
(`- name: x`) or flow-style (`- {name: x, ...}`); a `grep '- name:'` matches only
the block ones and undercounts a fully-backfilled ARCH. Run
`python "${CLAUDE_SKILL_DIR}/count_work_units.py" docs/ARCH__<cid>.yaml`, which is
plumbing- and waiver-aware, and quote its output. A "non-trivial gap" (its exit 1)
is the only signal that warrants "fix upstream in `/sdlc:arch`"; a plumbing or
waived zero-unit component is expected, not a gap. See SKILL.md Phase 2 →
"Deterministic work_unit counting".

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

**Draft `target_files` for every file-producing task, not just implementation.**
`scaffold` (the skeleton files), `test` (the spec file), `migration` (schema +
migration files), `config` (settings/env files), `design` (token/theme files)
all produce files at known paths — name them in `target_files` so the codegen
agent never derives a path the graph could have pinned. Don't smuggle the paths
into `outputs` instead (the gold fixtures once modeled that weaker style);
`outputs` says what dependents rely on ("TST-003 green"), `target_files` says
where the bytes go. The validator's check 21 warns on a file-producing task
with neither.

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
- `surface_overrides` present → each entry is a per-surface deviation from the
  global system (a denser grid, a bespoke hero, an inverted modal) the user
  declared deliberately, so it is **concrete design work**. For every
  `SCR-NNN` key whose surface this container owns, seed one `design` task that
  applies the override (density / `token_overrides` / `component_variants` /
  bespoke notes), naming that `SCR-NNN` in `implements_surfaces` and embedding
  the entry as its `design_spec`. This is *in addition to* the global
  theme/token task. Advisory (trace-or-defer via `WRN-NNN`), not blocking.
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

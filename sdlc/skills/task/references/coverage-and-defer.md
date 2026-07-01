# Coverage & defer — the trace-or-defer contract (sdlc-task)

This is the heart of what makes a `task` artifact trustworthy: **nothing the
upstream declared buildable goes silently unbuilt.** Every gated item is either
realized by a `TSK-NNN` task or explicitly, reviewably deferred. Read this when
closing each list in Phase 6 and at Phase 7.

It implements CLAUDE.md §6 ("Coverage contract: trace every upstream item OR
defer it"). The validator enforces both halves — a task graph that omits an item
without deferring it cannot reach `status: complete`.

---

## Transitive credit (the rule that keeps the gates humane)

An upstream item counts as **realized** if *either*:

1. a task **names it directly** (`component_ref`, `implements_tests`,
   `touches_operations`, `touches_entities`, `implements_surfaces`,
   `implements`), OR
2. a task **realizes a component that traces it** — the codegen sub-agent
   building that component reads its `ARCH__<cid>` trace, so the operation /
   surface / entity / requirement is reachable for it.

So you do **not** have to re-list every API operation on every controller task, nor
every entity on the repository task. Realize the component and the things it
traces ride along. The gate only forces an explicit choice for items that *no*
realized component traces — the genuinely orphaned ones, which are exactly the
silent-drop risks. Everything not realized must be **deferred** (named in a
`WRN-NNN`).

**The one exception is component work_units.** There, transitive credit is
deliberately switched OFF: a bare `component_ref` does not cover the component's
work_units — each must be named by **exactly one** task's `target_symbol` (or
deferred), and no two tasks may share a `target_symbol`. That is what forces the
one-task-per-method slicing this skill exists to produce. (Everything else —
surfaces, API operations, entities, requirements — still gets transitive credit
as above.)

## What is gated (all block `complete` — trace-or-defer)

### Container file (`TASKS__<container>.json`)

- **Components** — every `components[].component_id` in `ARCH__<cid>.yaml`.
- **Component work_units (the atomicity gate — always blocking)** — every
  `work_units[].name` in any `components[].work_units[]` of `ARCH__<cid>.yaml`.
  A work_unit is realized only when **exactly one** task **names it** in
  `target_symbol`; a bare `component_ref` does **not** transitively cover it, and
  no two tasks may share a `target_symbol`. Softens to a no-op only for a
  component that declares no work_units (pure plumbing — no coarse fallback). This
  is distinct from the API **Operations** gate below (component callables vs API
  endpoint operation_ids).
- **Tests** — every `tests[].tst_id` in `TEST-STRATEGY__<cid>.yaml` (first-class).
- **Surfaces** — every `SCR` in the container's `owns_ux_surfaces` (ARCH.yaml,
  resolved slug→SCR via `UX.yaml`). Backend containers own none ⇒ trivially met.
  Softens to advisory when `UX.yaml` is absent (slug↔SCR can't be resolved).
- **Operations** — every `operation_id` of a resource the container
  `owns_api_resources` (from `API__*.yaml`). Softens to advisory when no
  `API__*.yaml` is present. A bare resource_id in `touches_operations` is a
  hard error (list the operations).
- **Entities** — every entity the container's components trace
  (`traces_data_entities`). Realize via a `migration`/repository task
  (`touches_entities`) or a realized repository component.
- **Requirements** — every `FR`/`NFR` in the container's + components'
  `implements_requirements` (promoted from advisory: the contract is "convert all
  FRs/NFRs"). Usually satisfied transitively by realized components; only
  genuinely orphaned reqs force an explicit defer.
- **Design** (token_based_ui frontends that own surfaces) — a `design` task wiring
  the tokens/theme, or a defer. Per-asset (`AST-NNN`) tasks are advisory.

### System file (`TASKS.json`)

- **System tests** — every `tests[].tst_id` in `TEST-STRATEGY.yaml` (e2e/contract).

### Union (across all task files)

- **Global FR coverage** — every PRD `must_have_features` `FR-NNN` is realized by
  some task somewhere (directly or transitively) OR deferred OR an
  `ARCH.non_container_features`. Hard **only once the whole graph is stitched**
  (system file `complete` AND every buildable container has a `TASKS__*.json`);
  advisory before then, so an FR owned by a not-yet-built container does not
  wrongly fail an early file.

### Advisory (warns, never blocks)

- **Cross-container edges** — an `ARCH.yaml` `calls`/`depends_on` edge with no
  integration task spanning both endpoints.
- **Orphaned entities** — a DATA entity traced by no component in any built
  container (a likely ARCH gap — it would get no migration task).
- **Workflows (WKF)** — end-to-end coverage rides on the system e2e test tasks;
  `implements_workflows` on a task is an optional explicit link, not a gate.

---

## How to TRACE (the normal path)

Realize the item from a task (or rely on a realized component that traces it):

- a component → a task with `component_ref: <that component>` (kind:implementation).
- a component work_unit (`work_units[].name`) → a task with `component_ref` set AND
  `target_symbol: <that name>` + a single `target_files` (the atomic unit).
- a test → a task with `implements_tests: [<TST-NNN>]` (kind:test).
- a surface → a frontend task with `implements_surfaces: [<SCR-NNN>]`.
- an operation → a task with `touches_operations: [<operation_id>]` (or a realized
  component tracing the operation's resource).
- an entity → a `migration`/repository task with `touches_entities: [<EntityName>]`.
- a requirement → name it in some task's `implements` (or rely on the component).
- design tokens → a `design` task (token_based_ui frontends).

The validator counts the item as covered.

## How to DEFER (the escape hatch)

Some items genuinely warrant no task in *this* artifact:

- a component realized entirely by a system-level/shared task (its work lives in
  `TASKS.json`, not the container file);
- a `TST-NNN` that is a system e2e test whose task belongs in `TASKS.json`, not
  the container file;
- a component that is a pure interface/marker with no code to generate;
- a test deferred to a post-MVP hardening pass by explicit user decision.

Record the deferral by **naming the id in a `task_warnings` entry**:

```json
"task_warnings": [
  "WRN-014: TST-019 is a cross-container e2e test; its task lives in docs/TASKS.json, deferred here.",
  "WRN-015: component health-probe is generated by the shared deploy-prep task (TASKS/TSK-008); no separate task here."
]
```

The validator scans warnings for the id token (the literal `TST-NNN` or the
kebab-case `component_id`) and counts a named id as realized. **Always give a
reason** — a bare "WRN-016: TST-019" is valid to the regex but useless to a
reviewer. Don't defer to dodge work; defer when a separate task would be noise or
when the work genuinely lives elsewhere.

The user can trigger a deferral mid-interview by typing `defer <id>` — log the
WRN-NNN with the reason they give.

---

## The scope-completeness sweep (before closing each list)

`system_tasks` and `container_tasks` are `critical synthesis: true`. After the
per-item loop closes, run the **dynamic scope-completeness sweep** exactly as
specified in `sdlc/skills/prd/references/importance-flows.md` (§ "The `critical`
flow → dynamic scope-completeness sweep"). For `task`, reflect on:

- the **draft list** itself (is a whole kind missing — e.g. zero `migration`
  tasks for a container that has repository components and DATA entities? no
  `scaffold` task at all? a token_based_ui frontend with no `design` task?);
- **every upstream ID family**, not just the most direct one — ARCH components
  AND their `work_units[]` (is every work_unit sliced into its own task with a
  matching `target_symbol`?) AND internal edges, TEST `TST-NNN`, PRD FR/NFR, PRD
  `WKF`, DATA entities
  (migrations), API operations (endpoint tasks), UX `SCR` surfaces (frontend impl
  tasks), DESIGN tokens/`AST` assets (design tasks), `config_loader` components
  (config tasks);
- **project-type heuristics** — a CLI needs an entrypoint/arg-parsing task; a
  web service needs a server-bootstrap task; a frontend needs a routing/theme
  task; a monorepo needs a workspace scaffold; anything with persistence needs a
  migration/bootstrap task.

Surface concrete candidate tasks (not category labels) via one multi-select
`AskUserQuestion`. Caps: at most 2 sweep passes per list; honour the anti-padding
rule (surface 0 candidates rather than manufacture filler); defer any leftover
gaps to a `WRN-NNN`.

The sweep is the safety net for synthesis gaps — the case where a unit of work
implied by an upstream id (a repository component that obviously needs a
migration task) never made it into the draft because seeding only looked at the
most obvious signal. **Skip it at your peril.**

---

## At Phase 7

Run `validate_schema.py`. If a coverage gate fails while `status: complete`, the
validator prints the exact unrealized ids and forces a FAIL. Either add the
missing task or defer the id with a reasoned WRN-NNN, then re-validate. A
`status: draft` artifact lists the same gaps as advisory notes but still exits 0
— so you can always save partial progress.

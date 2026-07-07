# Slicing & ordering — the slice and the stitch (sdlc-task)

Read this in Phases 3–6. Two things shape every task graph: how work is **sliced**
into tasks (always atomic — one task per work_unit) and how those tasks are
**ordered** into a dependency graph that the codegen factory can execute (the
stitch). Both come straight from the demo PRD's FR-013.

---

## Atomic slicing — always one task per work_unit

There is no granularity knob and no coarse fallback. The whole point of this skill
is to feed the codegen factory *method-level* work units, because it fans one
sub-agent out per task: atomic tasks mean tight per-task context, cheaper +
higher-quality generation, and a clean 1:1 between a task and the test that
verifies it.

Slice to the finest unit the *architecture declares*:

- **one `implementation` task per component work_unit** — each `work_units[].name`
  in the component's `work_units[]` (ARCH__<container>.yaml) becomes its own task,
  scoped `component_ref` + `target_symbol: <the work_unit name>` + a **single**
  `target_files` entry (the file housing that callable). The unit's traces ride up
  onto the task (`touches_operations` ← the unit's `traces_api_operation`,
  `implements` ← its `implements_requirements`, `touches_entities` ← its
  `touches_entities`), and — schema v1.3 — the unit's interface contract is
  **embedded on the task** as `interface_contract` (copied from the unit's
  declared `inputs`/`output`/`raises`/`signature`, or resolved from the API
  operation it defers to), plus `unit_kind`/`unit_summary`. The codegen agent
  works from the task alone; see `task-discovery.md` → "Embed the per-task
  specifics" for the mechanics and the rationale for diverging from the demo's
  inherit-live model.
- **one `test` task per `TST-NNN`** — never grouped (see below).
- **one `migration` task per entity**.
- A component that declares **no** `work_units[]` yields **no implementation
  task** — it is pure plumbing (or an ARCH gap to fix at the source, not papered
  over with a coarse whole-component task). There is no whole-component fallback.

The trade-off, worth stating to the user: atomic = more, cheaper-context tasks but
more `depends_on` edges to order and more total orchestration. That's the deal the
codegen factory wants.

**The work-unit coverage gate is what makes atomic stick.** The validator *blocks*
`complete` until every `work_units[].name` across the container's components is
realized by **exactly one** task naming it in `target_symbol` OR deferred with a
`WRN-NNN`. A bare `component_ref` does **not** transitively cover the component's
work_units — that is the point — and no two tasks may share a `target_symbol`
(each callable is built once). See `coverage-and-defer.md`. The per-archetype
guide to *what counts as a work_unit* (one per API operation / entity CRUD verb /
service behaviour — contract-bearing callables, not private helpers) lives in
`sdlc/skills/arch/references/component-discovery.md` → "Deriving work_units".

Whatever the choice, **a test task is always its own task — one per `TST-NNN`,
never grouped.** Granularity only slices implementation work; a `TST-NNN` is
already an atomic behaviour, so bundling two into one `test` task hides a test
from the coverage gate and the codegen heal-loop. One `test` task realizes
exactly one `TST-NNN` (occasionally a tight cluster only when they share a single
fixture and assertion target — prefer one-per-TST).

---

## Dependency ordering (the `depends_on` graph)

Each task carries `depends_on`: the tasks that must complete before it. This is
what turns a flat list into the dependency-ordered TaskGraph FR-013 requires.

Default edges to propose (the user can override):

- every container task `depends_on` that container's `scaffold` task;
- every container `scaffold` `depends_on` the system repo `scaffold`
  (`TASKS/TSK-NNN`) — cross-file;
- a `test` task `depends_on` the `implementation` task whose code it exercises;
- an `integration` task `depends_on` both components/containers it wires;
- a consumer's task `depends_on` the provider's contract/implementation task —
  cross-container, expressed as `<provider-cid>/TSK-NNN`.

### Reference syntax

| Form | Meaning |
|---|---|
| `TSK-007` | a task in the **same** file |
| `backend-api/TSK-009` | task `TSK-009` in `docs/TASKS__backend-api.json` |
| `TASKS/TSK-002` | task `TSK-002` in the system `docs/TASKS.json` |

The validator resolves every `depends_on` against the **union** of all task
files and rejects any ref that doesn't land on a real task.

---

## The stitch (system mode)

FR-013: per-container subgraphs are "deterministically STITCHED into one global
dependency-ordered TaskGraph using the Stage 08 typed inter-container edges (a
calls/depends_on edge B→A orders A's contract tasks before B's consumer tasks)."

In this skill the stitch lives in `docs/TASKS.json`:

1. **`build_order`** — the topologically-ordered list of buildable container_ids,
   providers before consumers. Seed it from the specification order: ascending
   count of outgoing `depends_on` + `calls` edges in `ARCH.yaml.edges`, tie-broken
   by container definition order; on a cycle or no edges, definition order. This
   is the same order `--next` walks and the codegen orchestrator follows.
2. **Cross-file `depends_on`** — system integration tasks and consumer tasks
   point at provider tasks via `<cid>/TSK-NNN`, encoding the precise ordering the
   build_order summarizes.
3. **`container_task_graphs`** — the registry mapping each container to its
   subgraph file, so the orchestrator can locate every node.

### Acyclicity is the correctness gate

A dependency-ordered graph must be a DAG — if it has a cycle, no build order
exists and the codegen factory cannot start. The validator builds the union graph
across the system file + every container file and runs a topological check; a
cycle is a **blocking** error that prints the offending path
(`A -> B -> A`). When the user requests a dependency that would close a cycle,
refuse and show the path: one of the edges is wrong (often a test task and its
implementation task each declared to depend on the other — the test depends on
the impl, never the reverse).

`build_order` consistency with ARCH edges (provider before consumer) is a **soft**
warning, not a block — the explicit `depends_on` edges are the source of truth;
`build_order` is a convenience summary.

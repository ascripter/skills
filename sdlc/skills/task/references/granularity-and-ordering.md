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
  (`TASKS/TSK-NNN`) — cross-file (validator check #29 warns when missing);
- a `test` task `depends_on` the impl task(s) whose `target_symbol` appears in
  its TST's `targets_work_units` — the test→subject seam, read STRUCTURALLY
  from TEST-STRATEGY (v2.0 carries it per unit-tier test), never guessed from
  prose. These must be DIRECT edges: the code skill pairs each impl task with
  "the test task(s) whose depends_on reaches it" in one worker, so routing the
  edge through a per-component absorber validates green but pairs every test
  with the wrong worker (the corpus needed a 191-row hand rewire — PLAN4).
  Validator check #27 warns on the miss. Plus the container's
  `test_infrastructure` task (below);
- when TEST-STRATEGY declares `shared_infrastructure`, emit **ONE
  `kind: test_infrastructure` task per container**: `target_files` = the
  common directory pin (e.g. `["tests/"]`), description embeds the
  mock_policy + fixture_strategy texts **verbatim** (both levels: system +
  container override) and enumerates the declared file set; `depends_on` = the
  container scaffold + every schema/module-kind impl task (factories construct
  every artifact type — corpus worked example TSK-414: deps = scaffold + all
  26 schema modules, giving every test transitive schema reach); every
  `kind: test` task depends on it (check #28 warns otherwise). No
  component_ref/target_symbol — the kind is scaffold-like;
- a `test` (and `test_infrastructure`) task's `target_files` derive from the
  TEST-STRATEGY `test_file_convention` template (default
  `tests/<container>/<component_snake>/test_<tst_id_snake>.py`; the placement
  advisory validates against its root, not the component's code_location);
- for each `gating: false` TST, the test task carries the apply-the-marker
  directive (via its embedded test_spec) and the SYSTEM scaffold task owns
  marker registration + `addopts` exclusion in the repo-root test config —
  single-homed; the conftest registers nothing (check #30 warns on either
  half missing);
- an `integration` task `depends_on` both components/containers it wires — AND
  the impl task of every work_unit its description/`outputs` NAMES as a callee.
  Naming a callable you don't depend on is a scheduling lie: the integration
  task can be scheduled before the callee exists;
- a consumer's task `depends_on` the provider's contract/implementation task —
  cross-container, expressed as `<provider-cid>/TSK-NNN`.

### Schema-module → consumer edges (data-shape dependencies)

ARCH `calls`/`depends_on` edges never carry *data-shape* dependencies, so derive
them explicitly when the container has module-kind work units that OWN
entity/schema definitions:

1. Build an **entity→owning-module map**: each entity is owned by the module
   task whose work_unit creates its definition file; when several modules
   re-export it, the EARLIEST module in the file ladder owns it.
2. Every implementation/integration task naming entity E in `touches_entities`
   gains `depends_on` E's owning module task (skip self-edges). Module→module
   edges follow the same ladder, so the result is acyclic by construction.

Without this rule, schema modules land before their consumers only by tsk-id
tie-break, not by edge (corpus instance: 24 of 26 schema-module tasks had ZERO
dependents). The validator's zero-dependent-module advisory (artifact v1.5)
flags the smell.

### Wiring invariants (aggregators and integration tasks stay lean)

(The former invariant (a) — priority-monotonic edges — was deleted with
decision D2: the priority paradigm is retired pipeline-wide, so no priority
exists for an edge to invert. The letters (b)/(c) are kept stable because
downstream docs reference them.)

- **(b) An aggregator depends only on the predecessors it actually consumes.**
  A task that captures/collects the results of sibling branches (a
  `capture_and_exit`, a roll-up) must not fan-in *every* sibling — depend only
  on its REQUIRED predecessors. Blanket fan-in hides the real data flow and
  needlessly serializes the codegen waves downstream.
- **(c) An integration/bake task depends on the SET of tasks it exercises,
  never the tail.** The task that validates a container/seam depends on the
  tasks it actually exercises — **not** on the last-scheduled ("tail") task as
  a proxy for "all of them". Depending on the tail hides the real predecessors
  and silently breaks when the schedule reorders.

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

Dependency resolution and acyclicity are the ONLY hard edge gates — exactly the
rules `topo_order.py` enforces when it schedules (the validator↔scheduler
contract: the two tools must always agree on what makes a graph schedulable).
The lean-edge invariants (b)/(c) above are generation guidance, not blocks.

# Granularity & ordering — the slice and the stitch (sdlc-task)

Read this in Phases 3–6. Two decisions shape every task graph: how finely work
is **sliced** into tasks (granularity), and how those tasks are **ordered** into
a dependency graph that the codegen factory can execute (the stitch). Both come
straight from the demo PRD's FR-013.

---

## Granularity (atomic vs component) — DEFAULT atomic

The one required structural decision. **Default to `atomic`** — the whole point
of this skill is to feed the codegen factory *method-level* work units, because
it fans one sub-agent out per task: atomic tasks mean tight per-task context,
cheaper + higher-quality generation, and a clean 1:1 between a task and the test
that verifies it.

- **atomic** — slice to the finest unit the *architecture declares*:
  - **one `implementation` task per component operation** — each `OPN-NNN` in the
    component's `operations[]` (ARCH__<container>.yaml) becomes its own task,
    scoped `component_ref` + `implements_operations: [OPN-NNN]`. The op's traces
    ride up onto the task (`touches_operations` ← the op's `traces_api_operation`,
    `implements` ← its `implements_requirements`, `touches_entities` ← its
    `touches_entities`).
  - **one `test` task per `TST-NNN`** — never grouped (see below).
  - **one `migration` task per entity**.
  - A component that declares **no** `operations[]` falls back to **one task for
    the whole component** (graceful degradation — the validator warns, and ARCH
    should be enriched with operations to fix it at the source, not papered over
    here). The atomicity gate only bites for components that *do* declare ops.
- **component** — the old coarse mode: one `implementation` task per component,
  regardless of how many operations it has. Reserve for tiny apps / components
  where per-method tasks would be noise.

The trade-off, worth stating to the user: atomic = more, cheaper-context tasks
but more `depends_on` edges to order and more total orchestration; `component` =
fewer, larger tasks each carrying a whole component's context. Container
interviews inherit the system-mode default unless overridden. Legacy files
written `coarse`/`fine` are read as `component`/`atomic`.

**The operation-coverage gate is what makes atomic stick.** Under `atomic`, the
validator *blocks* `complete` until every `OPN-NNN` across the container's
components is realized by a task naming it in `implements_operations` OR deferred
with a `WRN-NNN`. A bare `component_ref` does **not** transitively cover the
component's operations under atomic — that is the point. (Under `component` the
same check is advisory and transitive.) See `coverage-and-defer.md`.

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

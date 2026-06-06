# Granularity & ordering — the slice and the stitch (sdlc-task)

Read this in Phases 3–6. Two decisions shape every task graph: how finely work
is **sliced** into tasks (granularity), and how those tasks are **ordered** into
a dependency graph that the codegen factory can execute (the stitch). Both come
straight from the demo PRD's FR-013.

---

## Granularity (coarse vs fine)

FR-013's only required structural decision (`requires_user_decision`).

- **coarse** — one `implementation` task per component. Fewer, larger tasks. Each
  codegen sub-agent gets a whole component's worth of context. Right for
  small/medium apps and components with a single cohesive responsibility.
- **fine** — split a component's implementation across its `responsibilities` /
  owned endpoints / public methods. More, smaller tasks. Right for large
  components, endpoint-heavy services, or when you want tighter per-task context
  to raise codegen quality and cut cost (FR-014's "primary cost/quality lever").

The trade-off is real and worth stating to the user: the codegen agent emits
files per task, so finer slicing means more, cheaper-per-unit tasks but more
edges to order and more total orchestration. Pre-fill `coarse` for ≤3-component
containers, suggest `fine` when a component owns many endpoints. Container
interviews inherit the system-mode default unless overridden.

Whatever the choice, **a test task is always its own task** regardless of
granularity — granularity only slices implementation work.

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

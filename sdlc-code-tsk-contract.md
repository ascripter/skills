# TSK contract — what a task entity actually contains (step-1 summary for the `code` skill)

Status: analysis deliverable, 2026-07-07. Sources ranked by authority:

1. **`sdlc/skills/task/TASKS__CONTAINER.schema.yaml` + `TASKS.schema.yaml`** — the
   contract the `task` skill *actually emits*. Authoritative.
2. **`sdlc/skills/task/references/*.md` + `validate_schema.py`** — enforcement
   semantics (coverage gates, stitch, acyclicity, downstream-rejection rule).
3. **Demo docs (`docs/PRD.yaml` FR-013/FR-014, `docs/DATA-MODEL.yaml` `Task`/
   `TaskGraph`/`CodeBundle`/`GeneratedFile`)** — the AICF *product spec* the task
   skill was modeled on. Aspirational for this repo: `arch` ran on the demo,
   `task` did **not**, so no TASKS*.json exists there and the demo's Task model
   diverges from the skill's in several fields (see `sdlc-code-audit.md`).

## The two artifacts

| File | Produced by | Holds |
|---|---|---|
| `docs/TASKS.json` | `/sdlc:task` (system mode) | Repo scaffold, cross-container `integration` tasks, system e2e/contract `test` tasks, `deploy-prep`, **`build_order`** (topological container sequence, providers first), **`container_task_graphs`** registry (`{container_id, file_path}`). |
| `docs/TASKS__<cid>.json` | `/sdlc:task <container>` | One container's subgraph: `scaffold`, one `implementation` task **per ARCH work_unit**, one `test` task **per TST-NNN**, `integration`/`migration`/`config`/`design`/`chore` tasks. |

Both are **JSON** (the one deliberate JSON artifact in the pipeline — machine-
generated, machine-consumed, programmatically stitched/topo-sorted).
`TSK-NNN` id spaces are **independent per file**: `TSK-001` in
`TASKS__backend-api.json` is unrelated to `TSK-001` in `TASKS.json`. The global
address of a task is therefore the qualified form used by `depends_on`:

| Form | Meaning |
|---|---|
| `TSK-007` | same file |
| `backend-api/TSK-009` | task in `docs/TASKS__backend-api.json` |
| `TASKS/TSK-002` | task in the system `docs/TASKS.json` |

## Task fields (container file — the richer superset)

| Field | Req? | Type / meaning for `code` |
|---|---|---|
| `tsk_id` | ✔ | `TSK-NNN`, unique per file. |
| `title` | ✔ | short imperative phrase. |
| `kind` | ✔ | `scaffold \| implementation \| test \| integration \| migration \| config \| design \| chore` (system file swaps `implementation`/`design`-container semantics for `deploy-prep`/`docs`; no `implementation` in system mode's list). Drives what `code` emits. |
| `description` | ✔ | self-contained statement of the work (FR-013: each codegen prompt is self-contained). |
| `component_ref` | impl: one of two | `ARCH__<cid>.yaml components[].component_id`. Scope anchor; also where `code_location` and the work_unit contract live. |
| `target_symbol` | ✔ for `implementation` | the ONE callable this task builds; **must equal exactly one `work_units[].name`** on `component_ref`; unique across the file's tasks. The task **inherits the work_unit's interface contract live from ARCH** (`inputs`/`output`/`raises`/optional `signature`) — deliberately NOT duplicated on the task. `code` MUST read ARCH to get the contract. |
| `target_files` | ✔ **exactly one** for `implementation`; encouraged otherwise | repo-relative write target(s). For implementation: the single file housing `target_symbol` (the atomic codegen pin), advisory-checked ⊆ the component's `code_location`. |
| `implements` | opt | `FR-NNN`/`NFR-NNN` (⊆ component's/container's `implements_requirements`). |
| `implements_tests` | ✔ for `test` | `TST-NNN` from `TEST-STRATEGY__<cid>.yaml` — the test spec `code` must realize. One task per TST, never grouped. |
| `touches_entities` | opt | DATA-MODEL entity names (PascalCase). |
| `touches_operations` | opt | API `operation_id`s (the alternative scope anchor for contract-scoped tasks). |
| `implements_surfaces` | opt | UX `SCR-NNN` (frontend). |
| `implements_workflows` | opt | PRD `WKF-NNN` (advisory). |
| `touches_assets` | opt | DESIGN `AST-NNN` (design tasks: brief sidecars). |
| `depends_on` | opt | qualified TSK refs (see table above). Union graph across ALL files is validated acyclic — a topological execution order always exists on a `complete` artifact. |
| `inputs` | opt | upstream artifact refs, e.g. `"ARCH__backend-api.yaml#auth-service"` — the context slice for the task. |
| `outputs` | ✔ non-empty | **contract-level** result dependents rely on ("exports createTask()", "TST-003 green"). NOT necessarily file paths — but the gold fixture legally uses file paths here when the file is the deliverable. |
| `acceptance` | ✔ non-empty | machine-checkable done conditions. `code`'s per-task verification target. |
| `priority` | ✔ | `must \| should \| could` (must ⇒ MVP exit gate). |
| `estimate` | opt | xs–xl. Low value post-atomicity; ignore. |
| `status` | ✔ | `draft \| confirmed` — *interview* progress. NOTE: the validator does **not** require all-confirmed for `metadata.status: complete` (flagged below). |

System-file tasks additionally carry `involves_containers` (validated against
ARCH) and omit `component_ref`/`target_symbol`/the per-family trace fields other
than `implements`/`implements_tests`.

## Granularity & relationships

- **Atomic by construction**: exactly one `implementation` task per ARCH
  `work_units[].name` (work-unit coverage gate 14a, always blocking, no
  transitive credit, no duplicate `target_symbol`). One `test` task per
  `TST-NNN`. One `migration` task per entity (convention).
- Several tasks routinely target the **same file** (gold: `TSK-004/005/006` all
  pin `src/controllers/tasks.ts`, one exported function each) — `code` must
  write incrementally, not overwrite.
- Default dependency shape: container task → container `scaffold` → system repo
  scaffold (`TASKS/TSK-NNN`); `test` → the impl it exercises; `integration` →
  both endpoints; consumer → provider contract task (cross-container).
- `build_order` = provider-before-consumer container sequence; the codegen
  orchestrator's coarse walk order. Explicit `depends_on` edges are the fine
  truth; `build_order` is the summary.

## Provenance chain for path/contract resolution

```
TSK.target_files[0]        → the file to write (repo-relative, consumer project root)
TSK.target_symbol          → the callable to create in it
TSK.component_ref ──ARCH──→ component.code_location   (placement seam, advisory)
                          → component.work_units[name==target_symbol]
                               .inputs/.output/.raises/.signature   (frozen interface)
TSK.touches_operations ─API→ request/response schemas (when the unit defers its contract)
TSK.implements_tests ──TEST→ the TST-NNN spec a test task realizes
TSK.touches_entities ──DATA→ entity field definitions
metadata.upstream_provenance → {file, session_id, last_updated, sha256} per upstream
```

## Consumption gates `code` must honor

- **Downstream-rejection rule** (task's `merge-validate.md`): reject any task
  file with `metadata.status != "complete"` OR task's `validate_schema.py`
  exiting non-zero.
- Never renumber/invent TSK ids; the state ledger references them by qualified
  id.
- The union graph on a complete artifact is guaranteed acyclic — `code` can
  topo-sort without a cycle-recovery path (but should still error clearly if
  hand-edits broke it).

## Flagged ambiguities (resolved defaults proposed; ★ = surfaced to user)

1. **`target_files` absent on non-implementation tasks.** Schema says
   "encouraged"; the gold `scaffold`/`test` tasks omit it and put file paths in
   `outputs`. Default resolution ladder for `code`: `target_files` → path-shaped
   `outputs` entries → component `code_location` + stack conventions → ask.
2. **Task-level `status: draft` inside a `complete` artifact** is not blocked by
   the validator. Default: `code` executes `confirmed` tasks; a `draft` task in
   a complete file triggers a per-task confirmation prompt.
3. **`priority: should/could`** — nothing upstream says whether codegen runs
   them. Default: execute everything in the graph; report per-priority counts;
   no filter flag in v1.
4. **★ Verification depth** — FR-084 (demo) wants a per-unit test-and-heal
   inner loop (≤3 attempts); the task artifact only gives `acceptance` strings.
   How deep `code` verifies per task is a scope decision → user question.
5. **WorkUnit `kind` (callable/module/content/tooling)** — exists in the demo
   ARCH (`kind: module` ×40 in `ARCH__aicf-cli.yaml`, per demo FR-013 v1.30 /
   DATA-MODEL v2.21) but NOT in this repo's `ARCH__CONTAINER.schema.yaml`, and
   `task` doesn't branch on it. For `code`: when present, a non-callable kind
   means "emit the file, not a function" — handled by treating `target_symbol`
   as the module/content deliverable name. Audit recommends schema alignment
   (see `sdlc-code-audit.md`).
6. **No SIG/CFG/SCT/INT trace fields** on the skill's Task (demo
   `implements_refs` carries them). The sdlc pipeline simply has no
   observability/config-schema stages — `config` tasks + ARCH cover what
   exists. No `code` impact; noted in the audit.
7. **Interface contract may be legitimately deferred** — a work_unit with
   `traces_api_operation` may omit `inputs`/`output`/`raises` (the API schema IS
   the contract). `code` must fall back to the API operation's request/response
   schemas in that case.

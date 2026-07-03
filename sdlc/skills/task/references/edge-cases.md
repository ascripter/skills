# Edge cases (sdlc-task)

Unusual situations and how to handle them. Most reduce to one of three reflexes:
**stop with a clear message** (broken precondition), **defer with a WRN-NNN**
(legitimately-empty coverage), or **ask the user** (ambiguous intent). Never
silently guess.

---

## Missing or draft upstream

- **`docs/ARCH.yaml` missing or `status: draft`.** Both modes need it. Stop:
  "Run `/sdlc:arch` to a complete system architecture first." Container mode also
  needs `ARCH__<cid>.yaml`; system mode needs `TEST-STRATEGY.yaml`.
- **Container mode, `ARCH__<cid>.yaml` or `TEST-STRATEGY__<cid>.yaml` missing.**
  Stop and name the exact upstream: "Run `/sdlc:arch <cid>` and/or
  `/sdlc:test <cid>` first — container task breakdown needs both (components to
  implement, tests to realize)." In `--next`, skip this container and try the
  next ready one; if none are ready, abort with the message.
- **`docs/PRD.yaml` missing.** PRD is read only for FR/NFR resolution. Don't hard
  stop — soften `implements` checks to format-only and append a WRN-NNN noting
  requirement-resolution was skipped.
- **Optional enrichers absent (`DATA-MODEL.yaml`, `API.yaml`).** Not an error.
  Skip entity/operation-derived tasks; note a WRN-NNN only if it leaves a real
  gap (e.g. a repository component with no DATA-MODEL to seed its migration task).

## Buildability & container shape

- **Non-buildable container requested** (external, or a storage/infra archetype:
  `primary-database`, `cache`, `blob-store`, `message-bus`, …). These have no
  code to generate. Explain and abort — they are provisioned by `/sdlc:deploy`,
  not built by tasks. `--next` skips them by construction.
- **Container with no components.** `ARCH__<cid>.yaml` should always have ≥1
  component (the arch validator requires it). If somehow empty, the component
  coverage gate is vacuously satisfied; still propose a `scaffold` task so the
  container isn't empty, and append a WRN-NNN.
- **A component that genuinely needs no task** (a pure interface/marker, or work
  that lives in a shared system task). `defer <component_id>` with a reason — the
  coverage gate accepts the named deferral.

## Work_unit counting & the closed preflight set

- **Don't miscount work_units with a grep.** `work_units[]` items are legitimately
  block-style (`- name: x`) or flow-style (`- {name: x, ...}`). A `grep '- name:'`
  matches only the block ones — it once reported "16 of 24 components have zero
  work_units" against a fully-backfilled 178-unit ARCH and wrongly REFUSED the run
  (37 counted, 141 missed). Always run
  `python "${CLAUDE_SKILL_DIR}/count_work_units.py" docs/ARCH__<cid>.yaml` (a real
  parse) and ground any readiness/refusal in its output. Exit 0 = proceed; exit 1
  = a genuine non-trivial gap → "fix upstream in `/sdlc:arch <cid>`".
- **Zero-work_unit components that are NOT gaps.** A plumbing component
  (`config_loader`/`serializer`/`observability_bootstrap`/`error_handler`) or one
  with an explicit `work_units_waiver` is legitimately unit-free — the counter
  marks it as such. Only a non-trivial, unwaived, zero-unit component is an
  upstream gap; do not lump the plumbing/waived ones into a refusal.
- **Don't invent preconditions.** The gates are exactly: `ARCH.yaml` complete;
  `ARCH__<cid>.yaml` + `TEST-STRATEGY__<cid>.yaml` present and complete; validators
  pass. A dirty git working tree, an "uncommitted-modified file", changelog-entry
  counts, or commit history are **not** gates this skill defines and must never be
  refusal grounds. Mention them, if at all, as a separate non-blocking FYI after
  you've decided to proceed.

## The dependency graph

- **User requests a dependency that closes a cycle.** Refuse and print the path
  (`A -> B -> A`). One edge is wrong — most often a `test` task and its
  `implementation` task each declared to depend on the other (the test depends on
  the impl, never the reverse). The validator would block `complete` anyway.
- **Cross-file dep to a not-yet-built container.** A consumer task may
  `depends_on: <provider-cid>/TSK-NNN` before the provider file exists. This is
  why `--next` builds providers first. If you author it early, the validator
  reports the ref as unresolved (blocking) until the provider file lands — that's
  expected; it self-heals once the provider is built. Save as `draft` meanwhile.
- **System mode run before any container exists.** Allowed but warned (SKILL.md
  dispatch §1). Author repo-scaffold + system test tasks; seed `build_order` from
  ARCH regardless; leave `container_task_graphs` empty (it fills in as containers
  are built). Offer `--next` instead so containers come first.

## Re-invocation & drift

- **ARCH/TEST edited between sessions.** On re-run, the provenance hash mismatch
  triggers the delta-review pass (CLAUDE.md §7). A removed component whose impl
  task still exists → ask per item (incorporate the removal / keep + WRN / defer).
  A new component → it surfaces in coverage as a gap to add. A new `TST-NNN` →
  surfaces as a missing test task.
- **Stale `depends_on` after an upstream rename.** ARCH ids are stable; a renamed
  *slug* doesn't change a `component_id`. If a `component_ref` no longer resolves,
  surface it per-ref — never silently drop the task.

## Mode boundaries

- **Container mode must not edit `TASKS.json`** except registering itself in
  `container_task_graphs[]` and bumping `last_updated` on first completion.
- **System mode must not edit any `TASKS__*.json`.** If the stitch reveals a
  container subgraph is wrong, tell the user to re-run `/sdlc:task <cid>`.

## Operational

- **Monorepo PRD (`metadata.monorepo: true` + non-empty `products`).** v1.0
  defers multi-product; proceed one product at a time in single-product mode and
  append a WRN-NNN. (Counters live under `state.last_ids_by_product[<slug>]` if
  you do split by product later.)
- **Write-permission error on `docs/`.** Report the path and the OS error; do not
  lose interview state — it is already persisted in the state file. Suggest the
  user fix permissions and re-run (resume will pick up).
- **Very large system (many containers → hundreds of tasks).** Atomic slicing
  multiplies task count (one per work_unit), so this is the common case, not the
  exception. Keep per-container files small and let the system file hold only the
  stitch + cross-container work. The union-graph check scales linearly; the
  interview is the bottleneck — lean hard on the Phase 3 draft (it is seeded one
  task per ARCH work_unit) so the user edits rather than dictates, and use
  `priority` (must/should/could) so the codegen orchestrator can stage the long
  tail. If the graph is genuinely too large, trim scope upstream (fewer work_units
  in ARCH, or defer components) rather than reaching for a coarser slice — there
  is none.
- **Invalid JSON on disk (hand-edit gone wrong).** The validator returns exit 2
  ("cannot read/parse"). Show the user the parse error location; offer to
  reconstruct from the state file's `partial_answers`.

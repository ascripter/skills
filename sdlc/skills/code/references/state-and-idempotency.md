# State & idempotency — the execution ledger (sdlc-code)

Read this in Phases 1–2. The ledger is what makes `/sdlc:code` re-runnable:
every invocation is "finish what's left", and nothing already on disk is ever
silently overwritten.

---

## Ledger schema

Path: `.claude/skills-state/sdlc-code.state.yaml`

```yaml
session_file_version: "1"
skill_version: "0.1"
last_updated: <iso8601>

build_order: [shared-contracts, backend-api, web-frontend]  # snapshot from TASKS.json

session:                        # the active / most recent invocation
  session_id: <uuid4>
  started_at: <iso8601>
  scope: all | TASKS | <container_id>
  status: in_progress | complete | aborted

containers:                     # per-container execution facts
  backend-api:
    test_command: "pnpm --filter backend-api test"   # established at first ring run
    ring_container_done: null | <iso8601>            # container ring passed

components_done: {}             # "<cid>/<component_id>": <iso8601> — component ring passed

tasks:                          # THE LEDGER — keyed by qualified task id
  "TASKS/TSK-001":
    status: done                # done | in_progress | failed | skipped | blocked*
    completed_at: <iso8601>
    task_fingerprint: "a3f09c2e11d4b7a0"   # sha256(canonical JSON of the task object)[:16]
    path_source: target_files   # target_files | outputs | code_location | user
    files_written:
      - {path: "pnpm-workspace.yaml", sha256: "<64-hex>"}
    heal_attempts: 0
    escalated: false
    verified: static_only       # unit_ring | static_only | none
  "backend-api/TSK-007":
    status: failed
    failure: "TST-006 red after 3 attempts: <last assertion error, one line>"
    ...
```

\* `blocked` is **derived** at scheduling time (a dependency is
`failed`/`skipped`), shown in reports, and only *persisted* when the user
explicitly skips something — don't store the transitive cascade.

Rules:

- **Write after every task** — step 6 of the Phase-4 protocol. Also after
  every ring closure and every gate decision. An interruption loses at most
  the task in flight.
- `task_fingerprint` = sha256 over the task's JSON object serialized with
  sorted keys and no whitespace (`json.dumps(task, sort_keys=True,
  separators=(",", ":"))`), first 16 hex chars. `topo_order.py --fingerprints`
  prints them — use it rather than hand-hashing.
- Qualified ids follow `depends_on` syntax: `TASKS/TSK-NNN` for the system
  file, `<container_id>/TSK-NNN` for container files.
- On EXIT: set `session.status: aborted`, keep everything else. On full
  completion of the requested scope: `session.status: complete`. Keep the file
  forever (audit trail).
- The manifest validator ignores this file; nothing downstream reads it.
  It is private execution state.

## The re-run decision matrix (Phase 1 reconcile + Phase 4 skip-check)

For each task in scope, compare three facts: the ledger entry, the **current
task JSON** (fingerprint), and the **current file content** (hashes of
`files_written`).

| Ledger | Task JSON | Files on disk | Action |
|---|---|---|---|
| `done`, fingerprint match | unchanged | hashes match | **skip silently** — the idempotent path |
| `done`, fingerprint match | unchanged | hash differs | **hand-edited** → gate: keep (default; re-hash and adopt) / regenerate / show diff. Never overwrite silently. |
| `done` | fingerprint differs | — | **stale** (task edited upstream) → gate: regenerate / keep as-is (re-fingerprint) |
| `done` | — | file deleted | treat as not-executed; confirm regenerate |
| `in_progress` (crashed session) | — | verify from disk | writes landed + static ring green → demote to `done`; else requeue |
| `failed` / `skipped` | — | — | keep; surface at the plan gate (`retry` / leave) |
| absent | — | target file exists, symbol absent | execute normally — Edit-insert (emit-rules) |
| absent | — | symbol exists **with** our marker | orphaned write (ledger lost?) → adopt: record as `done` with current hashes, tell the user |
| absent | — | symbol exists **without** marker | pre-existing user code → gate: adopt / replace / skip |

"Adopt" always means: record reality in the ledger, don't touch the file.

## Resume semantics

There is no separate resume flow. Phase 1 reconciles, Phase 3 shows the
deltas (stale / hand-edited / failed / orphaned) at the plan gate, Phase 4
executes whatever the matrix left pending. First run, interrupted-run
continuation, and post-upstream-change reconciliation are all the same path
with different matrix outcomes.

When `TASKS__*.json` gained **new** tasks since the last run (task-graph
extended), they appear as plain pending work — no special handling. When a
task was **removed** upstream but its ledger entry and code exist, list it in
the close report as orphaned provenance (code whose producing task no longer
exists); removal of code is always the user's call, never automatic.

## Ledger vs. manifest vs. disk

Three sources of truth with a strict priority:

- **Disk (the code)** wins conflicts — it may have been hand-edited, and
  hand-edits are legitimate (that's why the matrix gates instead of
  overwriting).
- **Ledger** is the execution truth: what ran, when, how many heals, what was
  written *at the time*.
- **Manifest** (`docs/CODE-MANIFEST.json`) is the publishable projection of
  the ledger for downstream consumers — regenerate its entries from the
  ledger + fresh disk hashes at every Phase 5; never treat it as input for
  scheduling decisions.

# State & idempotency — ledger, breadcrumbs, findings (sdlc-code)

Read this in Phases 1–2. Three files make `/sdlc:code` re-runnable: every
invocation is "finish what's left", nothing already on disk is ever silently
overwritten, and an interrupted unit resumes where it stopped rather than
starting over.

| File | Written by | Purpose |
|---|---|---|
| `.claude/skills-state/sdlc-code.state.yaml` | **manager only** | the execution ledger — what ran, when, how it verified |
| `.claude/skills-state/sdlc-code/inflight/<cid>__TSK-NNN.json` | **worker** | per-unit breadcrumb — how far this unit got |
| `.claude/skills-state/sdlc-findings.yaml` | manager (append) | cross-skill `FND-NNN` queue, resolved by `/sdlc:repair` |

Also under `.claude/skills-state/sdlc-code/`: `packets/` (worker packets from
`topo_order.py --emit --out-dir`) and `stack/` (per-container tech-stack
slices). Both are regenerable caches — safe to delete, never read as truth.

---

## Ledger schema

Path: `.claude/skills-state/sdlc-code.state.yaml`

```yaml
session_file_version: "1"
skill_version: "0.2"
last_updated: <iso8601>

build_order: [shared-contracts, backend-api, web-frontend]  # snapshot from TASKS.json

session:                        # the active / most recent invocation
  session_id: <uuid4>
  started_at: <iso8601>         # also the clock for the "session NhNNm" line
  scope: all | TASKS | <container_id>
  status: in_progress | complete | aborted
  concurrency: 1                # 1 = serial (default); N = --parallel N
  in_flight: []                 # qualified ids dispatched but not yet ledgered;
                                #   a breadcrumb for each should exist on disk
  checkpoint_policy: adaptive   # adaptive | every_component | containers_only
  budget:                       # chosen at the plan gate (session-and-limits.md)
    mode: next_component        # next_component | next_container | units | unbounded
    value: null | <int>         # units remaining when mode == units
    units_done: 0               # units completed THIS session (reset per session)

containers:                     # per-container execution facts
  backend-api:
    test_command: "pnpm --filter backend-api test"   # established at first ring run
    ring_container_done: null | <iso8601>            # container ring passed
    ring_container_exit: null | <int>                # captured numeric exit code of the
                                                     #   last container-ring run — measured
                                                     #   BARE, never after a pipe
                                                     #   (execution-loop.md measurement rule)

components_done:                # "<cid>/<component_id>" -> the checkpoint record
  "backend-api/task-api":
    at: <iso8601>
    ring_exit: 0                # captured numeric exit code of the component ring
    tasks: 10                   # tasks completed in this component
    heals: 2
    escalations: 0
    findings: []                # FND ids raised while this component ran

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
    ring_exit: 0                # captured numeric exit code of this task's last
                                #   ring run (unit ring for test tasks, static
                                #   ring otherwise) — measured BARE, never after
                                #   a pipe (execution-loop.md measurement rule)
    verified: static_only       # unit_ring | static_only | static_format | none
                                #   static_format = a non-code deliverable
                                #   (JSON/YAML/CSS/SVG/MD/content) that passed
                                #   its format checks — the floor for text
                                #   assets; `none` is reserved for "not even a
                                #   static check exists". Projected per-file
                                #   into CODE-MANIFEST.json files[].verified.
  "backend-api/TSK-007":
    status: failed
    failure: "exit 1: TST-006 red after 3 attempts: <last assertion error, one line>"
    ...                         # failure strings LEAD with the captured exit
                                #   code ("exit N: …") — prose paraphrase alone
                                #   is how a false-green hides
```

\* `blocked` is **derived** at scheduling time (a dependency is
`failed`/`skipped`), shown in reports, and only *persisted* when the user
explicitly skips something — don't store the transitive cascade.

Rules:

- **Write after every unit, by the MANAGER only** — step 4 of the Phase-4
  dispatch protocol (workers report; the manager verifies hashes and records).
  Also after every ring closure, every checkpoint, and every gate decision.
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

## Breadcrumb schema

Path: `.claude/skills-state/sdlc-code/inflight/<cid>__TSK-NNN.json`
(the qualified id with `/` replaced by `__` — the same filename shape
`topo_order.py --emit --out-dir` uses for packets).

Written by the **worker**, after every phase. This does not violate the
sole-ledger-writer rule: it is a separate namespace, and the manager only reads
it — then deletes it the moment that unit is ledgered.

```json
{
  "qualified_id": "aicf-cli/TSK-118",
  "worker_started_at": "2026-08-17T14:02:11Z",
  "phase": "unit_ring_run",
  "files_written": [{"path": "src/registry/load.py", "sha256": "<64-hex>"}],
  "ring": {"static_exit": 0, "unit_exit": 1},
  "failure_tail": "…at most 20 lines, verbatim…",
  "heals": [
    {"attempt": 1, "summary": "widened the None guard in load_prompt", "moved_failure": true}
  ]
}
```

`phase` advances through:
`packet_read → impl_written → static_green → test_written → unit_ring_run →
heal_1 → heal_2 → reported`.

Cost discipline: the breadcrumb is a few hundred bytes and one Write per phase.
That is the whole price of turning "regenerate a ~100k-token unit" into
"re-run its ring for ~5k".

## The re-run decision matrix (Phase 1 reconcile + Phase 4 skip-check)

For each task in scope, compare four facts: the ledger entry, any **breadcrumb**,
the **current task JSON** (fingerprint), and the **current file content**
(hashes of `files_written`).

| Ledger | Breadcrumb | Task JSON | Files on disk | Action |
|---|---|---|---|---|
| `done`, fingerprint match | — | unchanged | hashes match | **skip silently** — the idempotent path |
| `done`, fingerprint match | — | unchanged | hash differs | **hand-edited** → gate: keep (default; re-hash and adopt) / regenerate / show diff. Never overwrite silently. |
| `done` | — | fingerprint differs | — | **stale** (task edited upstream) → gate: regenerate / keep as-is (re-fingerprint) |
| `done` | — | — | file deleted | treat as not-executed; confirm regenerate |
| absent / `in_progress` | `impl_written` or `static_green` | unchanged | hashes match | **resume**: dispatch a resume brief — skip generation, run the rings from here |
| absent / `in_progress` | `test_written` / `unit_ring_run` | unchanged | hashes match | **resume**: re-run the unit ring; heal counter continues from `heals` |
| absent / `in_progress` | `heal_1` / `heal_2` | unchanged | hashes match | **resume at the next heal attempt**, with the recorded diffs+outcomes in the brief so it doesn't repeat them |
| absent / `in_progress` | any | fingerprint differs | — | breadcrumb is **stale** — the task changed under it. Discard it and regenerate. |
| absent / `in_progress` | any | unchanged | hashes differ / files missing | breadcrumb **unverifiable** — discard it and regenerate; say so at the gate |
| `in_progress` (crashed session) | none | — | verify from disk | writes landed + static ring green → demote to `done`; else requeue |
| `failed` / `skipped` | — | — | — | keep; surface at the plan gate (`retry` / leave) |
| absent | none | — | target file exists, symbol absent | execute normally — Edit-insert (emit-rules) |
| absent | none | — | symbol exists **with** our marker | orphaned write (ledger lost?) → adopt: record as `done` with current hashes, tell the user |
| absent | none | — | symbol exists **without** marker | pre-existing user code → gate: adopt / replace / skip |

"Adopt" always means: record reality in the ledger, don't touch the file.

Two rules the breadcrumb rows depend on:

- **A breadcrumb is evidence, not authority.** Always re-verify its
  `files_written` hashes against disk before trusting it. A breadcrumb whose
  hashes don't match reality is discarded, not reconciled.
- **A resumed unit is still a unit.** It gets a normal ledger entry when it
  finishes, its `heal_attempts` counts the whole history (pre- and
  post-interruption), and its breadcrumb is deleted at the same moment.

The plan gate lists recovered units explicitly and offers
*resume-at-phase (default) / regenerate from scratch* — resuming is right
almost always, but a user who suspects a half-written file should be able to
say so.

## Resume semantics

There is no separate resume flow. Phase 1 reconciles ledger + breadcrumbs,
Phase 3 shows the deltas (stale / hand-edited / failed / orphaned / recovered)
at the plan gate, Phase 4 executes whatever the matrix left pending. First run,
interrupted-run continuation, and post-upstream-change reconciliation are all
the same path with different matrix outcomes. This is why a fresh session is
always the right way back in after an interruption — see
`session-and-limits.md`.

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

Breadcrumbs sit outside this hierarchy: they are transient evidence about work
in flight, authoritative about nothing, and gone once the ledger records the
unit.

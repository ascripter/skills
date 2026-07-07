---
name: code
description: >
  Explicitly invoked EXECUTION skill — the SDLC factory's Stage-14 code
  generation. Consumes the dependency-ordered task graph (docs/TASKS.json +
  docs/TASKS__<container>.json produced by /sdlc:task) and WRITES THE ACTUAL
  SOURCE FILES each task's provenance pins (target_files / target_symbol),
  interleaving implementation tasks with their test tasks and running a
  test-and-heal loop per unit. Three forms: /sdlc:code (execute the whole
  remaining stitched graph), /sdlc:code <container> (one container's subgraph),
  /sdlc:code --next (the next incomplete unit in build_order). Re-running is
  always safe: an execution ledger in .claude/skills-state/sdlc-code.state.yaml
  tracks every executed TSK, so plain /sdlc:code means "do whatever remains".
  Trigger only on /sdlc:code or a direct natural-language request to run the
  codegen stage of the sdlc pipeline — never auto-trigger from generic requests
  to write code.
user-invocable: true
disable-model-invocation: true
model: sonnet
effort: high
allowed-tools: Read Write Edit Bash Bash(ls *) Glob Grep Agent AskUserQuestion
---

# sdlc-code

Executes the task graph. Where every upstream skill produces a *spec*, this
skill produces **code**: for each `TSK-NNN` it writes the file(s) the task's
provenance names, renders the callable the task's `target_symbol` pins from the
frozen ARCH work_unit contract, authors the tests each `test` task realizes,
and runs an incremental **test-and-heal loop** so broken units are fixed (or
flagged) before the factory advances.

This is the sdlc analogue of the demo PRD's FR-014 (Stage 14 — Code
Generation) with the FR-084 inner loop, adapted to Claude Code: no intra-stage
interview — HITL is a plan-approval gate up front, conflict/failure gates
during the run, and a report at the end.

**Outputs:**

- Source files at the paths each task's `target_files` names (the consumer
  project's repo, repo-relative) — the actual deliverable.
- `docs/CODE-MANIFEST.json` — the machine-readable ledger of every generated
  file (`path`, `sha256`, `producing_task`, `heal_attempts`,
  `generated_by_model`), the CodeBundle-analogue downstream verify/deploy
  stages consume.
- `.claude/skills-state/sdlc-code.state.yaml` — the execution ledger that
  makes every invocation resumable and idempotent.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — dispatch, the execution flow, the gates. |
| `CODE-MANIFEST.schema.yaml` | Human-readable canonical schema for `docs/CODE-MANIFEST.json`. |
| `validate_schema.py` | Pydantic v2 validator for the manifest (+ advisory disk cross-checks). |
| `topo_order.py` | Deterministic scheduler: loads all TASKS files + the ledger, topo-sorts with the test-first policy, prints ready/blocked/stale tasks and ring boundaries. Run it — never hand-compute the order. |
| `set_claude_md_pointer.py` | CLAUDE.md pointer injector, called at close. |
| `references/execution-loop.md` | Scheduling policy, the four verification rings, the heal loop, opus escalation. Read on entering Phase 4. |
| `references/emit-rules.md` | Kind → write behavior, provenance markers, same-file merging, the path ladder + path safety. Read on entering Phase 4. |
| `references/state-and-idempotency.md` | Ledger schema, fingerprints, the re-run decision matrix, resume semantics. Read in Phases 1–2. |
| `references/edge-cases.md` | Unusual situations (missing target_files, draft tasks, hand-broken graphs, …). |

Runtime files (NOT in this skill directory): `docs/CODE-MANIFEST.json`,
`.claude/skills-state/sdlc-code.state.yaml`, the generated source tree.

## Invocation dispatch

Classify `$ARGUMENTS`:

1. **No arguments** → **full run**: execute every remaining task across the
   union of `docs/TASKS.json` + every `docs/TASKS__*.json`, in scheduler
   order. Because the ledger persists, this is always "finish what's left" —
   first run and resume are the same code path.
2. **One positional argument** → **container run**: the argument is a
   `container_id`; `docs/TASKS__<cid>.json` MUST exist (else list the
   available task files and abort). Execute only that subgraph. Tasks blocked
   by unexecuted **cross-file** deps (system scaffold, a provider container)
   are surfaced up front with one AskUserQuestion: *execute the blocking
   tasks first (recommended) / skip the blocked tasks / abort*.
3. **`--next`** → resolve to the next incomplete **unit** in `build_order`
   and execute exactly that unit, then report what `--next` would do next.
   Unit order: (a) ready system tasks with no container deps (repo scaffold
   etc.), (b) each container in `build_order` that still has unexecuted
   tasks, (c) the system integration/e2e tail (cross-container `integration`
   + system `test` tasks). If everything is executed, print the completion
   message and point at `/sdlc:deploy`.
4. Anything else → print the three valid forms and abort.

Confirm the resolved target before executing (one AskUserQuestion): scope,
pending-task counts by kind, and any leftover `failed`/`stale` items from
previous runs. This is the **plan-approval gate** — the codegen equivalent of
the demo's Stage-14 HITL gate.

## Preconditions (a CLOSED set — do not invent gates)

- The in-scope task file(s) exist, carry `metadata.status: "complete"`, and
  `python sdlc/skills/task/validate_schema.py --path docs/TASKS.json` exits 0
  (the **downstream-rejection rule** — a draft or invalid graph must not be
  executed). In container mode the union validation still runs (the stitch
  needs all files), but only the target container's tasks execute.
- For every container in scope: `docs/ARCH__<cid>.yaml` and
  `docs/TEST-STRATEGY__<cid>.yaml` are readable (the work_unit interface
  contracts and TST specs live there, not on the tasks).
- Nothing else. Git cleanliness, changelog counts, upstream `status` fields
  beyond the task files' own — none of these are preconditions. Mention
  observations as non-blocking FYI *after* deciding to proceed, never as
  grounds for refusal.

A task-level `status: "draft"` inside a complete artifact does not block the
run; it triggers a per-task confirmation before that task executes
(`references/edge-cases.md`).

## The execution flow

### Phase 1 — Ledger & resume

Read `.claude/skills-state/sdlc-code.state.yaml` if present (schema:
`references/state-and-idempotency.md`). Reconcile it against disk: recompute
each `done` task's fingerprint against the current task JSON and its written
files' hashes; classify mismatches (`stale` / hand-edited) for Phase 3. A task
left `in_progress` by an interrupted session is re-verified from disk (its
writes may or may not have landed) and demoted to pending or done accordingly.
No state file → empty ledger, fresh start.

### Phase 2 — Scan & gate

Run the preconditions above. Then load the graph the deterministic way:

```bash
python "${CLAUDE_SKILL_DIR}/topo_order.py" --scope <all|TASKS|cid> [--state .claude/skills-state/sdlc-code.state.yaml]
```

It prints the schedule (ready → blocked → done/failed/stale/skipped), the ring
boundaries, and the `--next` resolution. Quote its output in the plan-approval
gate; never hand-compute topological order.

**Slice upstream docs, don't slurp.** Per-task context is deliberately tiny:
the task object + its ARCH work_unit + `code_location` + whatever its trace
fields name (`touches_operations` → the API operation schema,
`touches_entities` → the DATA entity slice, `implements_tests` → the TST
entry). Use `docs/INDEX.yaml` line ranges (`.claude/rules/sdlc-docs-access.md`)
for the big YAMLs; read whole files only when INDEX is absent or the doc is
small.

### Phase 3 — Plan & approval

Present the plan-approval gate (dispatch section above), including:

- pending counts by kind and by container;
- `stale` tasks (upstream task JSON changed since execution) → confirm
  regenerate / keep;
- hand-edited files (written hash ≠ current hash) → keep / regenerate / show
  diff, **never overwrite silently**;
- previously `failed` tasks → retry (with escalation) / skip.

On approval, enter the loop.

### Phase 4 — The execution loop

Load `references/execution-loop.md` and `references/emit-rules.md` now. Per
task, the protocol is:

1. **Pick** the next ready task from `topo_order.py` (test-first ready-queue
   policy — a test task runs the moment the implementation it exercises is
   done).
2. **Skip-check** against the ledger (idempotency matrix in
   `references/state-and-idempotency.md`).
3. **Gather the context slice** (Phase 2 rules) — task + contracts, nothing
   else.
4. **Emit** per the kind table below and `references/emit-rules.md`, with the
   provenance marker on every generated symbol.
5. **Static ring**: cheapest machine check the stack affords (compile /
   import / syntax / typecheck of the touched file).
6. **Ledger write** — after EVERY task, before moving on. An interruption
   never loses more than the task in flight.
7. **Unit ring** (test tasks only): run the just-authored tests against the
   implementation they exercise; on failure **heal ≤3 attempts** — attempts
   1–2 inline, attempt 3 escalates to a fresh **opus subagent** with a
   self-contained heal brief (`references/execution-loop.md`). Unresolved →
   mark `failed`, mark dependents `blocked`, continue with independent work.
8. **Ring closures**: when the last task of a component / container / the
   system graph completes, run that ring's suite (component unit tests
   together → container integration + full container suite → system
   e2e/contract), heal ≤3 with the same escalation.

Progress notes at component and container boundaries ("`auth-middleware`
done: 3 impl, 2 test, unit ring green. Next: `tasks-controller`."). The user
can type `EXIT` into any gate's free-text to stop; the ledger already holds
everything confirmed so far.

### Phase 5 — Manifest write & validate

Write or merge `docs/CODE-MANIFEST.json` (schema:
`CODE-MANIFEST.schema.yaml`): one `files[]` entry per file written this run
plus the carried-forward entries of prior runs; `metadata.upstream_provenance`
snapshots each consumed task file's `{file, session_id, last_updated, sha256}`
(hash from `docs/INDEX.yaml.generated_from` or `sha256(bytes)[:16]`). Then:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/CODE-MANIFEST.json
```

Fix field-level errors before declaring anything. `metadata.status:
"complete"` only when every task in the stitched graph is `done` or
`skipped`-with-reason and the validator passes; otherwise `"draft"` (a
partially-executed factory is the normal intermediate state).

### Phase 6 — Pointer & close

Call `set_claude_md_pointer.py` (injects/updates the `sdlc-code` bullet in
`## SDLC Documents`). Refresh `docs/INDEX.yaml` if `.claude/sdlc/docs_index.py`
exists (no-op otherwise). Set the session's ledger entry `status: complete`.
Close with the report: counts (done/failed/skipped/blocked), heal + escalation
stats, unresolved failures with their errors, and what `--next` would do.

## Task kind → what gets written

Full rules with examples: `references/emit-rules.md`.

| Kind | Emit |
|---|---|
| `scaffold` | Package/repo skeleton: the files in `target_files` (or path-shaped `outputs`) — manifest, entrypoint, workspace config. |
| `implementation` | **One callable** (`target_symbol`) in **one file** (`target_files[0]`), rendered from the ARCH work_unit contract (`inputs`/`output`/`raises`/`signature`; falls back to the API operation schema when the unit defers via `traces_api_operation`). First task on a file creates it; later tasks Edit-insert. |
| `test` | The runnable test(s) realizing each `implements_tests` TST — tier, directives, fixtures and covered requirements from `TEST-STRATEGY__<cid>.yaml`. |
| `integration` | Wiring: route registration, DI, the consumer-side client against the provider's contract. |
| `migration` | Schema/DDL/persistence setup for `touches_entities`, per the DATA-MODEL slice. |
| `config` | Env/settings wiring (the `config_loader` seam); secrets *backends* belong to deploy. |
| `design` | Theme/token files, or the asset-folder scaffold + one `assets/<name>.brief.md` sidecar per `touches_assets` AST. |
| `chore` / `docs` / `deploy-prep` | Per `description` + `target_files`; `deploy-prep` stops at handoff stubs for `/sdlc:deploy`. |

Every generated symbol carries the greppable provenance marker (comment syntax
per language):

```
// sdlc-code: backend-api/TSK-005 (createTask)
```

and every file this skill *creates* opens with a one-line header naming the
producing task(s). The marker is the reverse-lookup anchor (code → task → FR)
and the idempotency probe.

## The state ledger (summary)

Path: `.claude/skills-state/sdlc-code.state.yaml` — full schema and the re-run
decision matrix in `references/state-and-idempotency.md`. Keyed by **qualified
task id** (`TASKS/TSK-001`, `backend-api/TSK-003` — the same syntax
`depends_on` uses). Per task: `status` (`done | in_progress | failed | skipped
| blocked`), `task_fingerprint` (sha256[:16] of the task's JSON object),
`files_written` (`{path, sha256}`), `heal_attempts`, `escalated`, `verified`.
Written after every task. The ledger is the *execution* truth; the manifest is
the *artifact* truth; the code on disk always wins a conflict — surface, never
silently overwrite.

## Model policy

The session runs on **sonnet / high** (frontmatter): atomic tasks render one
callable from a frozen contract, which is exactly the regime a balanced model
handles well, and it keeps a 100+-task run affordable. Reasoning-heavy moments
get more: heal attempt 3 always goes to a **fresh opus subagent** (Agent tool,
`model: "opus"`) with a self-contained brief — a deliberately un-anchored
second opinion. If subagents are unavailable in the session, attempt 3 runs
inline with the reset-assumptions protocol and the report says so
(`references/execution-loop.md`).

## Quick reference: user inputs at gates

| Input | Effect |
|---|---|
| `EXIT` | Stop after the task in flight; ledger keeps everything done so far. |
| `skip <qualified-id>` | Mark a task `skipped` (with reason) — its dependents become `blocked`. |
| `retry <qualified-id>` | Re-queue a `failed` task (escalation counter resets). |
| approve / pick at the plan gate | Start / rescope the run. |

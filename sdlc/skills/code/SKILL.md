---
name: code
description: >
  Explicitly invoked EXECUTION skill — the SDLC factory's Stage-14 code
  generation. Consumes the dependency-ordered task graph (docs/TASKS.json +
  docs/TASKS__<container>.json produced by /sdlc:task) and WRITES THE ACTUAL
  SOURCE FILES each task's provenance pins (target_files / target_symbol).
  The session acts as a MANAGER dispatching worker subagents — one work unit
  (implementation task + its test task, with a test-and-heal loop) per worker,
  SERIALLY by default; --parallel N (N<=3) opts into rolling concurrent
  dispatch over units with disjoint target_files. Checkpoints at every
  COMPONENT boundary (summary + doctor check + adaptive gate) and every
  container boundary. Three forms: /sdlc:code (container-by-container through
  build_order), /sdlc:code <container> (one container's subgraph, then stop),
  /sdlc:code --next (the next incomplete unit in build_order). Re-running is
  always safe: an execution ledger in .claude/skills-state/sdlc-code.state.yaml
  plus per-unit worker breadcrumbs track every executed TSK, so plain
  /sdlc:code means "do whatever remains".
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
provenance names, renders the deliverable the task's `target_symbol` pins from
the task's embedded `interface_contract` (frozen at task-graph write time),
authors the tests each `test` task realizes from its embedded `test_spec`,
and runs an incremental **test-and-heal loop** so broken units are fixed (or
flagged) before the factory advances.

The session is a **manager, not the coder**: it dispatches worker subagents,
each executing one self-contained work unit (the v1.4 task embeds make the task
packet the whole context). Dispatch is **serial by default** — one worker at a
time — because under a per-window token cap concurrency buys no throughput and
only multiplies what an interrupted run loses; `--parallel N` opts back in when
the cap is not the binding constraint. The manager owns every HITL gate, is the
**sole ledger writer**, serializes the higher test rings, and checkpoints at
every **component** and **container** boundary — so a long factory run stays
bounded, cheap to interrupt, and resumable.

This is the sdlc analogue of the demo PRD's FR-014 (Stage 14 — Code
Generation) with the FR-084 inner loop, adapted to Claude Code: no intra-stage
interview — HITL is a plan-approval gate up front, conflict/failure gates
during the run, and a report at the end.

**Outputs:**

- Source files at the paths each task's `target_files` names (the consumer
  project's repo, repo-relative) — the actual deliverable.
- `docs/CODE-MANIFEST.json` — the machine-readable ledger of every generated
  file (`path`, `sha256`, `producing_task`, `heal_attempts`,
  `generated_by_model`, `verified` — the verification level the file
  reached), the CodeBundle-analogue downstream verify/deploy
  stages consume.
- `.claude/skills-state/sdlc-code.state.yaml` — the execution ledger that
  makes every invocation resumable and idempotent.
- `.claude/skills-state/sdlc-findings.yaml` — append-only `FND-NNN` findings
  queue: spec defects this run discovered but must NOT fix here (this skill
  never edits `docs/`). `/sdlc:repair` triages and resolves them.
- Working state under `.claude/skills-state/sdlc-code/`: `packets/` (worker
  packets), `stack/` (per-container tech-stack slices), `inflight/` (worker
  breadcrumbs — deleted as each unit is ledgered).

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — dispatch, the execution flow, the gates. |
| `CODE-MANIFEST.schema.yaml` | Human-readable canonical schema for `docs/CODE-MANIFEST.json`. |
| `validate_schema.py` | Pydantic v2 validator for the manifest (+ advisory disk cross-checks). |
| `topo_order.py` | Deterministic scheduler AND worker-packet builder: loads all TASKS files + the ledger, topo-sorts with the test-first policy, prints ready/blocked/stale tasks and ring boundaries; `--emit <qualified-id>…` prints the verbatim task object(s) + a `requirement_context` slice from PRD (`implements` / `implements_workflows` / `test_spec.covers` ids resolved to FR/NFR/WKF/ACR statements) for the worker brief. Run it — never hand-compute the order or `Read` a TASKS shard to slice a task. |
| `set_claude_md_pointer.py` | CLAUDE.md pointer injector, called at close. |
| `references/execution-loop.md` | Scheduling policy, the four verification rings, the heal loop, opus escalation. Read on entering Phase 4. |
| `references/emit-rules.md` | Kind → write behavior, provenance markers, same-file merging, the path ladder + path safety. Its **Worker digest** section is the one named block every worker brief includes verbatim. Read on entering Phase 4. |
| `references/state-and-idempotency.md` | Ledger schema, fingerprints, the re-run decision matrix, resume semantics. Read in Phases 1–2. |
| `references/session-and-limits.md` | Session budget, drain triggers, interruption recovery, the resume card. Read in Phase 3 and at every stop. |
| `references/edge-cases.md` | Unusual situations (missing target_files, draft tasks, hand-broken graphs, …). |

Runtime files (NOT in this skill directory): `docs/CODE-MANIFEST.json`,
`.claude/skills-state/sdlc-code.state.yaml`,
`.claude/skills-state/sdlc-findings.yaml`, `.claude/skills-state/sdlc-code/**`,
the generated source tree.

## Invocation dispatch

Classify `$ARGUMENTS`. One **modifier** may accompany any form:

- `--parallel <N>` (1–3, default **1**) — how many workers may be in flight at
  once. See "Why serial by default" below before raising it.

The positional forms:

1. **No arguments** → **gated run**: work container-by-container through
   `build_order` — ready system tasks with no container deps first (repo
   scaffold etc.), then each container's remaining subgraph, then the system
   integration/e2e tail. Checkpoint at every **component boundary** and every
   **container boundary** (Phase 4). Because
   the ledger persists, this is always "finish what's left" — first run and
   resume are the same code path; stopping at a gate and re-invoking later
   are equivalent.
2. **One positional argument** → **container run**: the argument is a
   `container_id`; `docs/TASKS__<cid>.json` MUST exist (else list the
   available task files and abort). Execute only that subgraph, then stop
   (no *container* boundary gate — the scope was explicit; component
   checkpoints still run). Tasks blocked
   by unexecuted **cross-file** deps (system scaffold, a provider container)
   are surfaced up front with one AskUserQuestion: *execute the blocking
   tasks first (recommended) / skip the blocked tasks / abort*.
3. **`--next`** → resolve to the next incomplete **unit** in `build_order`
   and execute exactly that unit, then report what `--next` would do next.
   Unit order: (a) ready system tasks with no container deps (repo scaffold
   etc.), (b) each container in `build_order` that still has unexecuted
   tasks, (c) the system integration/e2e tail (cross-container `integration`
   + system `test` tasks). If everything is executed, print the completion
   message and point at `/sdlc:deploy` (planned — not yet implemented).
4. Anything else → print the three valid forms (and the `--parallel` modifier)
   and abort.

Confirm the resolved target before executing (Phase 3). This is the
**plan-approval gate** — the codegen equivalent of the demo's Stage-14 HITL
gate.

## Preconditions (a CLOSED set — do not invent gates)

- The in-scope task file(s) exist, carry `metadata.status: "complete"`, and
  `python "${CLAUDE_SKILL_DIR}/../task/validate_schema.py" --path docs/TASKS.json`
  exits 0
  (the **downstream-rejection rule** — a draft or invalid graph must not be
  executed). In container mode the union validation still runs (the stitch
  needs all files), but only the target container's tasks execute.
- `python "${CLAUDE_SKILL_DIR}/../task/crosscheck_artifacts.py" --docs-dir docs`
  exits 0 —
  the cross-artifact linter; a task graph whose references dangle across
  artifacts (a renamed work_unit, a removed TST, a stale entity) must not be
  executed. On `[FAIL]`, name the broken refs and point at the artifact/skill
  to fix; warnings are FYI only.
- For every container in scope: `docs/ARCH__<cid>.yaml` is readable — one
  header slice per container for the **tech stack** (the only
  container-general fact codegen needs from ARCH). Task artifacts at
  version >= 1.4 embed all per-task specifics (`interface_contract`,
  `test_spec`, `unit_kind`, plus `operation_contract` / `entity_slice` /
  `design_spec` / `config_keys` on their kinds); for **older artifacts** the
  upstream docs are the fallback source per field — the ARCH work_unit and
  the TST entry in `docs/TEST-STRATEGY__<cid>.yaml` (pre-1.3), and
  `API__*.yaml` / `DATA-MODEL.yaml` entity slices / `DESIGN__tokens.yaml` +
  `DESIGN__assets.yaml` (pre-1.4).
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
files' hashes; classify mismatches (`stale` / hand-edited) for Phase 3.

Then read the **breadcrumbs** — `.claude/skills-state/sdlc-code/inflight/*.json`.
Each leftover file is a unit an interrupted session was mid-way through, and it
records exactly how far the worker got (files written + hashes, static/unit ring
exit codes, heal attempts and their outcomes). A unit with a breadcrumb is
**resumed at its last completed phase**, not regenerated: that is the difference
between spending ~5k tokens re-running a ring and ~100k re-authoring a
deliverable that is already on disk. The breadcrumb resume matrix is in
`references/state-and-idempotency.md`.

Also load `.claude/skills-state/sdlc-findings.yaml` if present — open
`FND-NNN` findings are reported at the plan gate (a run whose known spec defects
are unresolved usually wants `/sdlc:repair` first, not more code).

No state file → empty ledger, fresh start.

### Phase 2 — Scan & gate

Run the preconditions above. Then load the graph the deterministic way:

```bash
python "${CLAUDE_SKILL_DIR}/topo_order.py" --scope <all|TASKS|cid> [--state .claude/skills-state/sdlc-code.state.yaml]
```

It prints the schedule (ready → blocked → done/failed/stale/skipped), the ring
boundaries, and the `--next` resolution. Quote its output in the plan-approval
gate; never hand-compute topological order.

**The task is the context.** On a v1.4 artifact the task object is
self-contained: `interface_contract` (the frozen callable shape), `test_spec`
(the TST's tier/directives/acceptance), `unit_kind`, `unit_summary`,
`operation_contract` / `entity_slice` / `design_spec` / `config_keys` (the
per-kind grounding slices), `description`, `acceptance`. Read upstream only
for what the task can't carry: the container's tech stack (one
`ARCH__<cid>.yaml` header slice per container), and — on **older artifacts**
— the field's fallback source (pre-1.3: the ARCH work_unit / TST entry;
pre-1.4: the API operation, the DATA entity's field definitions, the DESIGN
token/asset files). Use
`docs/INDEX.yaml` line ranges (`.claude/rules/sdlc-docs-access.md`) for the
big **upstream YAMLs** (ARCH); read whole files only when INDEX is absent or
the doc is small. Never `Read` a TASKS shard to slice a task — the per-task
JSON is pulled by `topo_order.py --emit --out-dir` (Phase 4), which also joins
the `requirement_context` (FR/NFR/WKF/ACR statements — for a test task these
come from its `test_spec.covers`) so the packet, not PRD, carries the
requirement grounding for implementation *and* test tasks alike. This is what
makes a task a complete **worker packet** (Phase 4).

Extract each in-scope container's tech-stack slice from `ARCH__<cid>.yaml`
**once** and write it to `.claude/skills-state/sdlc-code/stack/<cid>.md`. Worker
briefs name that path; the manager never re-types the stack per worker.

### Phase 3 — Plan & approval

Load `references/session-and-limits.md`. Present the plan-approval gate,
including:

- scope, pending counts by kind and by container, and the dispatch mode
  (`serial` unless `--parallel N` was given);
- `stale` tasks (upstream task JSON changed since execution) → confirm
  regenerate / keep;
- hand-edited files (written hash ≠ current hash) → keep / regenerate / show
  diff, **never overwrite silently**;
- previously `failed` tasks → retry (with escalation) / skip;
- **interrupted units** recovered from breadcrumbs → resume-at-phase (default)
  / regenerate from scratch;
- **open findings** (`FND-NNN`) → continue anyway / stop and run `/sdlc:repair`.

Two policy questions belong to this gate (both have defaults — offer them as
position-1 so approval is one click):

1. **Session budget** — how far to run: *next component* (default) / next
   container / N units / until stopped. This is not a token estimate; it is a
   planned stopping point, so an interrupted 5-hour window becomes a clean
   boundary stop with a resume card instead of a killed worker.
2. **Checkpoint policy** — *adaptive* (default: summarize every component, stop
   only when something needs attention) / every component / containers only.

Record both under `session.budget` / `session.checkpoint_policy` in the ledger.
On approval, enter the loop.

### Phase 4 — The execution loop (manager + workers)

Load `references/execution-loop.md` and `references/emit-rules.md` now. The
manager never writes source files itself — it dispatches **worker subagents**
and integrates their results. Subagents are used at every concurrency level,
including 1: the point is **context isolation** (the worker's file reads, ring
output and heal transcript never enter the manager's context), not speed.

Per unit:

1. **Pick the next unit** from `topo_order.py`'s ready set. A work unit = one
   implementation task + the test task(s) exercising it (test-first ready-queue
   policy — the pair runs in ONE worker so the heal loop sees both sides).
   Skip-check it against the ledger first (idempotency matrix in
   `references/state-and-idempotency.md`).

   Under `--parallel N` the pick is additionally constrained: the candidate's
   `target_files` must be **disjoint from every unit currently in flight** —
   disjointness is **path-aware** (a directory entry contains every path beneath
   it: `tests/` overlaps `tests/unit/test_x.py`). Check mechanically over the
   in-flight set plus the candidate:

   ```bash
   python "${CLAUDE_SKILL_DIR}/topo_order.py" --overlap <in-flight qid>... <candidate qid>
   ```

   A task touching **shared files** (scaffold, barrel exports, a config file
   another pending task also writes) or carrying a **directory-pinned target**
   (canonically `test_infrastructure`'s `["tests/"]`) runs **solo** — drain
   first, then dispatch it alone.

2. **Build the packet as a FILE, never as brief text:**

   ```bash
   python "${CLAUDE_SKILL_DIR}/topo_order.py" --emit <qualified-id> [<qualified-id> ...] --out-dir .claude/skills-state/sdlc-code/packets
   ```

   It writes one packet per task — the verbatim task JSON (v1.4 embeds) joined
   with a `requirement_context` slice (the task's `implements` /
   `implements_workflows` / `test_spec.covers` ids resolved to their one-line PRD
   statements) — and prints **only the paths**. The payload never enters the
   manager's context and is never re-emitted as brief text.

3. **Dispatch one worker** (Agent tool). The brief is short and made of
   **pointers**, not pasted content: it names the packet file(s), the **worker
   digest** file (`references/emit-rules.md` — absolute path, read whole), the
   tech-stack slice file, the test command, the write boundary, the
   **breadcrumb path** the worker must maintain, and the **capped report
   format**. Exact template: `references/execution-loop.md` → "The worker
   brief". Workers never ask the user anything, never write the ledger, and
   never touch files outside their write boundary.

4. **Integrate the result**: verify each reported file exists and hashes match,
   **write the ledger** (the manager is the SOLE ledger writer), then **delete
   that unit's breadcrumb**. Do this after every unit, before dispatching more —
   an interruption then loses at most the units in flight, and even those resume
   from their breadcrumb rather than from zero.

5. **Escalate failures**: a worker reporting an unresolved unit after 2 heal
   attempts triggers attempt 3 — a fresh **opus subagent** with a self-contained
   heal brief (`references/execution-loop.md`), dispatched by the manager. Still
   unresolved → mark `failed`, mark dependents `blocked`, raise an `FND-NNN` if
   the diagnosis names an upstream contradiction (step 8), continue with
   independent work.

6. **Ring closures — serialized in the manager**: when the last task of a
   component / container / the system graph completes, **drain** (stop
   dispatching; let in-flight units finish) and run that ring's suite (component
   unit tests together → container integration + full container suite → system
   e2e/contract), healing ≤3 with the same escalation. Higher rings never run
   inside workers (port/DB collisions). Run every ring command **bare** and
   record its captured numeric exit code in the ledger — never read the exit
   status after a pipe (measurement rule in `references/execution-loop.md`).

7. **Checkpoint** at each component and container boundary — the checkpoint
   ladder below.

8. **Capture findings, never fix them.** When the run reveals a defect in an
   *upstream artifact* rather than in generated code, append an `FND-NNN` entry
   to `.claude/skills-state/sdlc-findings.yaml` and carry on. This skill never
   edits `docs/`. The closed set of raising conditions and the entry shape are in
   `references/execution-loop.md` → "Raising a finding".

The user can type `EXIT` into any gate's free-text to stop; the ledger and
breadcrumbs already hold everything confirmed so far.

#### The checkpoint ladder

Three widening checkpoints: **unit** (ledger write, every unit) → **component**
→ **container**. The component checkpoint is what makes a long run reviewable:
a real container can hold hundreds of tasks across dozens of components, so a
container-only seam means one review after everything is already built.

At each component boundary: drain → component ring → a compact **summary**
(tasks, ring exit, heals, escalations, findings, budget, elapsed, progress) →
a cheap **doctor check** (`doctor.py --quick`) → the **gate policy**. The
default `adaptive` policy prints the summary every time but stops only on a
closed set of six attention triggers — a red ring, a failed/escalated task, a
new finding, the session budget, a red doctor check, or a container boundary.
Container boundaries additionally carry the bare-run continue/stop gate.

Summary format, doctor command, the full trigger list, and the `every component`
/ `containers only` policies: `references/execution-loop.md` → "The checkpoint
ladder".

#### Why serial by default

Under a per-window token cap, three workers complete the **same** number of
units per window as one — they burn the budget three times faster and then wait
for the reset. Concurrency buys no throughput against that cap; it only widens
the blast radius when the window ends mid-flight. Breadcrumbs shrink that loss
to "re-run the ring", but one unit at risk still beats three. `--parallel N` is
the opt-in for when the cap is not binding — small graphs, API billing,
wall-clock pressure — and dispatches **rolling, not batched**. Full rationale,
the in-flight disjointness invariant, and the drain points:
`references/execution-loop.md`.

If the Agent tool is unavailable in the session, execute units inline, one at a
time, same protocol (the report must say so).

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

Close with the report — counts (done/failed/skipped/blocked), heal + escalation
stats, unresolved failures with their errors, orphaned provenance — and then,
**always**, the **resume card** (`references/session-and-limits.md`). The card is
not optional and not only for interrupted runs: a run that stopped at a budget,
at a gate, on `EXIT`, or because the graph is finished all end the same way, with
the user told exactly what to type and whether to do it here or in a fresh
session.

```
── /sdlc:code — where you are ─────────────────────────────
Session:   23 units · 4 components · started 14:02 (2h 11m)
Done:      312 / 414 aicf-cli  ·  0 failed  ·  2 blocked
Next:      component 'stage-node-runtime' (65 tasks)
Resume:    /sdlc:code aicf-cli        ← in a NEW session
Why new:   the ledger is the handoff, not this transcript.
Findings:  2 open (FND-003, FND-004) → /sdlc:repair first
```

When the whole build graph is `done`, the `Next:` line points at what comes
next instead:

> All containers built. Next: `/sdlc:deploy` (deployment spec) — **planned, not
> yet implemented**; until it ships, `deploy-prep` tasks leave handoff stubs and
> verification/deploy is manual.

## Task kind → what gets written

Full rules with examples: `references/emit-rules.md`.

| Kind | Emit |
|---|---|
| `scaffold` | Package/repo skeleton: the files in `target_files` (or path-shaped `outputs`) — manifest, entrypoint, workspace config. |
| `implementation` | **One deliverable** (`target_symbol`) in **one file** (`target_files[0]`). `unit_kind: callable` (default) renders the callable from the task's embedded `interface_contract`; `module`/`content`/`tooling` emit the file itself; `entrypoint` renders the composition/dispatch root (arg/mode parse + step-sequencing + setup + exit codes) that dispatches into the per-mode callables. Pre-1.3 fallback: the ARCH work_unit (or the API operation it defers to). First task on a file creates it; later tasks Edit-insert. |
| `test` | The runnable test(s) realizing each `implements_tests` TST — tier, directives and acceptance from the task's embedded `test_spec` (pre-1.3 fallback: the TST entry in `TEST-STRATEGY__<cid>.yaml`). |
| `test_infrastructure` | The container's ONE shared-test-infrastructure task: conftest, factories, fake helpers per its `description` (mock_policy + fixture_strategy ride in it verbatim). Scaffold-like — no `component_ref`/`target_symbol`, directory `target_files` (`["tests/"]`) the norm, file-header provenance. Every `test` task depends on it; its directory pin means it runs **solo** — it drains the in-flight set under `--parallel` and is never dispatched alongside another unit. |
| `integration` | Wiring: route registration, DI, the consumer-side client against the provider's contract — from the task's embedded `operation_contract` (pre-1.4 fallback: resolve `touches_operations` in `API__*.yaml`). |
| `migration` | Schema/DDL/persistence setup for `touches_entities`, per the task's embedded `entity_slice` (pre-1.4 fallback: the DATA-MODEL entity slice). |
| `config` | Env/settings wiring (the `config_loader` seam) from the task's embedded `config_keys` — never invent keys (pre-1.4 fallback: ground in ARCH/API/PRD and warn); secrets *backends* belong to deploy. |
| `design` | Theme/token files from the embedded `design_spec.tokens`, or the asset-folder scaffold + one `assets/<name>.brief.md` sidecar per `design_spec.assets[]` brief (pre-1.4 fallback: `DESIGN__tokens.yaml` / `DESIGN__assets.yaml`). |
| `chore` / `docs` / `deploy-prep` | Per `description` + `target_files`; `deploy-prep` stops at handoff stubs for `/sdlc:deploy`. |

**Non-code deliverables get a real static ring too.** A deliverable with no
compiler (JSON / YAML / CSS / SVG / Markdown / a prompt pack) is verified by
**format** instead — it must parse, be well-formed, and satisfy the task's
`acceptance` where machine-checkable — and records `verified: static_format`,
never `none`. Text assets are first-class deliverables of this factory and must
not ship unverified (`references/execution-loop.md`).

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
`files_written` (`{path, sha256}`), `heal_attempts`, `escalated`, `verified`
(`unit_ring | static_only | static_format | none`). Written after every task,
**by the manager only** — workers report, the manager records.

Two companions live beside it and are NOT the ledger:

- **Breadcrumbs** (`.claude/skills-state/sdlc-code/inflight/<cid>__TSK-NNN.json`)
  are written by the **worker**, one per in-flight unit, updated after each
  phase. They do not violate the sole-ledger-writer rule — they are a separate
  namespace the manager only reads, and the manager deletes each one as it
  ledgers that unit. They are what makes an interrupted unit resumable at its
  last completed phase instead of regenerable from zero.
- **Findings** (`.claude/skills-state/sdlc-findings.yaml`) are the cross-skill
  `FND-NNN` queue this skill appends to and `/sdlc:repair` resolves. Never
  triage or resolve a finding here.

The ledger is the *execution* truth; the manifest is the *artifact* truth (each
file's `verified` level is projected into `CODE-MANIFEST.json` at Phase 5); the
code on disk always wins a conflict — surface, never silently overwrite.

## Model policy

The manager session runs on **sonnet / high** (frontmatter): scheduling,
ledger writes, and result integration need bookkeeping discipline, not deep
reasoning, and it keeps a 100+-task run affordable. Keeping the manager's
context small is a *cost* discipline, not just hygiene — manager output tokens
count against the same window budget that ends a run, which is why packets,
digests and stack slices travel to workers as **file paths** and why worker
reports are format-capped. **Workers inherit the
session model** (sonnet): atomic tasks render one callable from a frozen
contract, which is exactly the regime a balanced model handles well.
Reasoning-heavy moments get more: heal attempt 3 always goes to a **fresh
opus subagent** (Agent tool, `model: "opus"`) with a self-contained brief — a
deliberately un-anchored second opinion, dispatched by the manager. If
subagents are unavailable in the session, units execute inline one at a time
and attempt 3 runs
inline with the reset-assumptions protocol and the report says so
(`references/execution-loop.md`).

## Quick reference: user inputs at gates

| Input | Effect |
|---|---|
| `EXIT` | Stop after the unit(s) in flight; ledger + breadcrumbs keep everything so far. Prints the resume card. |
| `skip <qualified-id>` | Mark a task `skipped` (with reason) — its dependents become `blocked`. |
| `retry <qualified-id>` | Re-queue a `failed` task (escalation counter resets). |
| `repair` at a checkpoint gate | Stop here so `/sdlc:repair` can triage the open findings; prints the resume card. |
| approve / pick at the plan gate | Start / rescope the run, set the session budget and checkpoint policy. |

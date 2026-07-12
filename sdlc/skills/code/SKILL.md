---
name: code
description: >
  Explicitly invoked EXECUTION skill — the SDLC factory's Stage-14 code
  generation. Consumes the dependency-ordered task graph (docs/TASKS.json +
  docs/TASKS__<container>.json produced by /sdlc:task) and WRITES THE ACTUAL
  SOURCE FILES each task's provenance pins (target_files / target_symbol).
  The session acts as a MANAGER dispatching waves of up to 3 parallel worker
  subagents — one work unit (implementation task + its test task, with a
  test-and-heal loop) per worker; waves contain only tasks with disjoint
  target_files. Three forms: /sdlc:code (container-by-container through
  build_order, pausing at each container boundary with a continue/stop gate),
  /sdlc:code <container> (one container's subgraph, then stop), /sdlc:code
  --next (the next incomplete unit in build_order). Re-running is always safe:
  an execution ledger in .claude/skills-state/sdlc-code.state.yaml tracks
  every executed TSK, so plain /sdlc:code means "do whatever remains".
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

The session is a **manager, not the coder**: it schedules waves of up to
**3 parallel worker subagents**, each executing one self-contained work unit
(the v1.4 task embeds make the task packet the whole context). The manager
owns every HITL gate, is the **sole ledger writer**, serializes the higher
test rings between waves, and pauses at each **container boundary** for a
continue/stop gate — so a long factory run stays bounded and resumable.

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

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — dispatch, the execution flow, the gates. |
| `CODE-MANIFEST.schema.yaml` | Human-readable canonical schema for `docs/CODE-MANIFEST.json`. |
| `validate_schema.py` | Pydantic v2 validator for the manifest (+ advisory disk cross-checks). |
| `topo_order.py` | Deterministic scheduler AND worker-packet builder: loads all TASKS files + the ledger, topo-sorts with the test-first policy, prints ready/blocked/stale tasks and ring boundaries; `--emit <qualified-id>…` prints the verbatim task object(s) + a `requirement_context` slice from PRD for the worker brief. Run it — never hand-compute the order or `Read` a TASKS shard to slice a task. |
| `set_claude_md_pointer.py` | CLAUDE.md pointer injector, called at close. |
| `references/execution-loop.md` | Scheduling policy, the four verification rings, the heal loop, opus escalation. Read on entering Phase 4. |
| `references/emit-rules.md` | Kind → write behavior, provenance markers, same-file merging, the path ladder + path safety. Read on entering Phase 4. |
| `references/state-and-idempotency.md` | Ledger schema, fingerprints, the re-run decision matrix, resume semantics. Read in Phases 1–2. |
| `references/edge-cases.md` | Unusual situations (missing target_files, draft tasks, hand-broken graphs, …). |

Runtime files (NOT in this skill directory): `docs/CODE-MANIFEST.json`,
`.claude/skills-state/sdlc-code.state.yaml`, the generated source tree.

## Invocation dispatch

Classify `$ARGUMENTS`:

1. **No arguments** → **gated run**: work container-by-container through
   `build_order` — ready system tasks with no container deps first (repo
   scaffold etc.), then each container's remaining subgraph, then the system
   integration/e2e tail. At every **container boundary** (a container's
   subgraph + container ring complete), report progress and ask ONE
   AskUserQuestion: *continue with `<next container>` / stop here*. Because
   the ledger persists, this is always "finish what's left" — first run and
   resume are the same code path; stopping at a gate and re-invoking later
   are equivalent.
2. **One positional argument** → **container run**: the argument is a
   `container_id`; `docs/TASKS__<cid>.json` MUST exist (else list the
   available task files and abort). Execute only that subgraph, then stop
   (no boundary gate — the scope was explicit). Tasks blocked
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
- `python sdlc/skills/task/crosscheck_artifacts.py --docs-dir docs` exits 0 —
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
JSON is pulled by `topo_order.py --emit` (Phase 4), which also joins the
`requirement_context` (FR/NFR/WKF statements) so the packet, not PRD, carries
the requirement grounding. This is what makes a task a complete **worker
packet** (Phase 4).

### Phase 3 — Plan & approval

Present the plan-approval gate (dispatch section above), including:

- pending counts by kind and by container;
- `stale` tasks (upstream task JSON changed since execution) → confirm
  regenerate / keep;
- hand-edited files (written hash ≠ current hash) → keep / regenerate / show
  diff, **never overwrite silently**;
- previously `failed` tasks → retry (with escalation) / skip.

On approval, enter the loop.

### Phase 4 — The execution loop (manager + parallel workers)

Load `references/execution-loop.md` and `references/emit-rules.md` now. The
manager never writes source files itself — it dispatches **waves of worker
subagents** and integrates their results. Per wave:

1. **Compose the wave** from `topo_order.py`'s ready set: up to **3 work
   units** whose task sets have **pairwise-disjoint `target_files`**. A work
   unit = one implementation task + the test task(s) exercising it
   (test-first ready-queue policy — the pair runs in ONE worker so the heal
   loop sees both sides). Tasks touching **shared files** (scaffold, barrel
   exports, a config file another pending task also writes) run **solo** —
   a wave of one. Skip-check every candidate against the ledger first
   (idempotency matrix in `references/state-and-idempotency.md`).
2. **Dispatch workers** (Agent tool, run in parallel, non-interactive). Build
   each worker's brief from the **packet builder** — never by `Read`-ing the
   TASKS file (a container shard can be hundreds of KB; slurping it wastes the
   manager's whole context):

   ```bash
   python "${CLAUDE_SKILL_DIR}/topo_order.py" --emit <qualified-id> [<qualified-id> ...]
   ```

   It prints, per requested task, the **verbatim task JSON object** joined with a
   `requirement_context` slice (the task's `implements`/`implements_workflows`
   ids resolved to their one-line PRD statements) — so the worker has its FR/NFR
   grounding in-packet without opening PRD. Each worker's brief is then
   self-contained: its packet(s) (the v1.4 embeds + requirement_context ARE the
   context), the container's tech-stack slice, the
   emit-rules digest (provenance marker + path safety), and the instruction
   set: emit per the kind table, run the **static ring** (compile / import /
   typecheck / format check of touched files), run the **unit ring** (the
   unit's just-authored tests), **heal ≤2 attempts inline**, then STOP and
   report. Workers never ask the user anything, never write the ledger,
   never touch files outside their task's `target_files` (+ the test file).
3. **Integrate results** as workers return: verify each reported file exists
   and hashes match, then **ledger write** (the manager is the SOLE ledger
   writer) — after every unit, before dispatching more. An interruption
   never loses more than the wave in flight (interrupted units re-verify
   from disk on resume, Phase 1).
4. **Escalate failures**: a worker reporting an unresolved unit after 2 heal
   attempts triggers attempt 3 — a fresh **opus subagent** with a
   self-contained heal brief (`references/execution-loop.md`), dispatched by
   the manager. Still unresolved → mark `failed`, mark dependents `blocked`,
   continue with independent work.
5. **Ring closures — serialized in the manager** between waves: when the
   last task of a component / container / the system graph completes, run
   that ring's suite (component unit tests together → container integration
   + full container suite → system e2e/contract), heal ≤3 with the same
   escalation. Higher rings never run inside workers (port/DB collisions).
6. **Container boundary** (bare-run form only): after a container's ring
   closes, report ("`backend-api` done: 14 impl, 9 test, container ring
   green — 2 containers remain") and gate: *continue with `<next>` / stop
   here*.

The user can type `EXIT` into any gate's free-text to stop; the ledger
already holds everything confirmed so far.

**Why 3 workers, why disjoint files:** parallel workers can't see each
other's just-written code — the embedded contracts are the only seam. Disjoint
`target_files` makes write conflicts impossible; the integration/container
rings catch contract-level mismatches one ring later. Three is the sweet spot
between wall-clock speedup and blast radius when a seam assumption is wrong.
If the Agent tool is unavailable in the session, fall back to executing units
inline, one at a time, same protocol (the report must say so).

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
stats, unresolved failures with their errors, and what `--next` would do. When
the whole build graph is `done`, point at what comes next:

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
| `integration` | Wiring: route registration, DI, the consumer-side client against the provider's contract — from the task's embedded `operation_contract` (pre-1.4 fallback: resolve `touches_operations` in `API__*.yaml`). |
| `migration` | Schema/DDL/persistence setup for `touches_entities`, per the task's embedded `entity_slice` (pre-1.4 fallback: the DATA-MODEL entity slice). |
| `config` | Env/settings wiring (the `config_loader` seam) from the task's embedded `config_keys` — never invent keys (pre-1.4 fallback: ground in ARCH/API/PRD and warn); secrets *backends* belong to deploy. |
| `design` | Theme/token files from the embedded `design_spec.tokens`, or the asset-folder scaffold + one `assets/<name>.brief.md` sidecar per `design_spec.assets[]` brief (pre-1.4 fallback: `DESIGN__tokens.yaml` / `DESIGN__assets.yaml`). |
| `chore` / `docs` / `deploy-prep` | Per `description` + `target_files`; `deploy-prep` stops at handoff stubs for `/sdlc:deploy`. |

**Non-code deliverables get a real static ring too.** A `unit_kind:
module/content/tooling` (or design/config/docs) deliverable that is JSON /
YAML / CSS / SVG / Markdown / a prompt pack has no compiler — verify it by
format instead: JSON/YAML must parse, CSS/SVG must be well-formed, Markdown
links/headings must resolve, and the file must satisfy the task's
`acceptance` phrasing where machine-checkable. A file passing only these
checks records `verified: static_format` (never `none`) — text assets are
first-class deliverables of this factory and must not ship unverified
(`references/execution-loop.md`).

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
**by the manager only** — workers report, the manager records. The ledger is
the *execution* truth; the manifest is
the *artifact* truth (each file's `verified` level is projected into
`CODE-MANIFEST.json` at Phase 5); the code on disk always wins a conflict —
surface, never silently overwrite.

## Model policy

The manager session runs on **sonnet / high** (frontmatter): scheduling,
ledger writes, and result integration need bookkeeping discipline, not deep
reasoning, and it keeps a 100+-task run affordable. **Workers inherit the
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
| `EXIT` | Stop after the task in flight; ledger keeps everything done so far. |
| `skip <qualified-id>` | Mark a task `skipped` (with reason) — its dependents become `blocked`. |
| `retry <qualified-id>` | Re-queue a `failed` task (escalation counter resets). |
| approve / pick at the plan gate | Start / rescope the run. |

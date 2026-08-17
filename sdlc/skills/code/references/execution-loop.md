# Execution loop — scheduling, dispatch, rings, heal, escalation (sdlc-code)

Read this on entering Phase 4. It defines the order tasks run in, the
manager/worker dispatch protocol, the verification rings, the heal loop, the
opus escalation, and how a spec defect becomes a finding instead of a patch.

---

## Scheduling policy (why not plain topological order)

A plain topo sort is *correct* but tends to batch: all implementations first,
all tests afterwards — which discovers a broken unit long after the context
that produced it is gone. The factory wants the FR-084 shape instead: each
unit is verified right after it is built, while its contract slice is still
the freshest thing in context.

`topo_order.py` therefore schedules with one priority rule on top of the topo
constraint:

> Among **ready** tasks (all `depends_on` executed), always pick a ready
> **`test` task first**; break ties among non-test tasks by (same component as
> the previous task, then file order, then `tsk_id`).

Because `task` seeds every test task with `depends_on` edges to the
implementation task(s) it exercises, a test task becomes ready the moment its
last implementation lands — so the emergent order is
`impl → its tests → heal → next impl`, without any pairing table. The
component-locality tie-break keeps one component's work contiguous, which is
what makes the component checkpoint meaningful.

Never hand-compute the order. Run the tool; it also diffs against the ledger:

```bash
python "${CLAUDE_SKILL_DIR}/topo_order.py" --scope all --state .claude/skills-state/sdlc-code.state.yaml
```

## Dispatch — serial default, rolling parallel opt-in

The session is the **manager**; source files are written by **worker
subagents**. Subagents are used at every concurrency level, including 1 —
their purpose is **context isolation**, not speed. A worker's file reads, ring
output and heal transcript stay in the worker; only its capped report comes
back.

### Why the default is one worker

Under a per-window token cap, three workers complete the **same** number of
units per window as one — they burn the budget three times faster and then wait
for the reset. Concurrency does not buy throughput against that cap. What it
does buy is a larger blast radius when the window ends mid-flight: every
in-flight worker's un-integrated work is at risk. Breadcrumbs (below) shrink
that loss from "regenerate the unit" to "re-run its ring", but one unit at risk
still beats three.

`--parallel N` (N ≤ 3) is therefore the **opt-in**, for when the cap is not the
binding constraint: small graphs, API billing, or plain wall-clock pressure.

### The serial loop (default)

```
pick ready unit → --emit --out-dir → dispatch worker → integrate
   → ledger-write → delete breadcrumb → pick next
```

### The rolling loop (`--parallel N`)

**Rolling, not batched.** Keep N units in flight; dispatch a replacement the
moment one returns. Do NOT spawn a batch of N and wait for all N to finish —
that idles workers on the tail of the slowest unit and lengthens the window
during which an abort is expensive.

- Dispatch workers with `run_in_background: true` and refill on each completion
  notification: integrate → ledger-write → delete breadcrumb → dispatch the
  next ready unit.
- **The disjointness invariant widens.** It is no longer "the batch is pairwise
  disjoint" but *"every newly dispatched unit's `target_files` are disjoint
  from every unit currently in flight"*. Overlap is **path-aware**: a directory
  entry contains every path beneath it (`tests/` overlaps
  `tests/unit/test_x.py`). Check it mechanically over the in-flight set plus the
  candidate — the tool takes any number of ids:

  ```bash
  python "${CLAUDE_SKILL_DIR}/topo_order.py" --overlap <in-flight qid>... <candidate qid>
  ```

  Exit 0 = disjoint, 1 = overlapping. A candidate that overlaps waits.
- **Solo tasks**: a task touching shared files (scaffold, barrel/exports, a
  config file another pending task also writes) or carrying a DIRECTORY-pinned
  target — canonically `test_infrastructure`'s `["tests/"]` — drains the
  in-flight set first and then runs alone. When in doubt, solo: correctness
  beats parallelism.
- **Drain points**: before any serialized ring, at every component and
  container boundary, when the session budget is reached, and on any drain
  trigger from `session-and-limits.md`. Draining means "stop dispatching, let
  in-flight units finish" — never "kill in-flight units".

### The worker brief

The brief is made of **pointers, not pasted content**. Every byte the manager
types into a brief is a manager *output* token, and output tokens count against
the same window budget whose exhaustion ends the run. On a several-hundred-task
graph, pasting the digest plus the packet into each brief is the single largest
avoidable cost in the skill.

Build the packet as a file first:

```bash
python "${CLAUDE_SKILL_DIR}/topo_order.py" --emit <qualified-id> [...] --out-dir .claude/skills-state/sdlc-code/packets
```

It prints only the paths. Then the brief, in full:

```
Execute one sdlc-code work unit. Non-interactive: never ask the user anything.

PACKET(S):        <path>                      ← Read these first. The packet is
                                                 the whole task context: the
                                                 verbatim task object (v1.4
                                                 embeds) + requirement_context.
WORKER DIGEST:    <abs path to references/emit-rules.md>
                  Read the block from "## Worker digest" to
                  "*End of worker digest.*" WHOLE. Never cherry-pick it.
TECH STACK:       <path to .claude/skills-state/sdlc-code/stack/<cid>.md>
TEST COMMAND:     <the recorded ring command, or "not yet established">
WRITE BOUNDARY:   <target_files> + <test file>. Nothing else. Ever.
BREADCRUMB:       .claude/skills-state/sdlc-code/inflight/<cid>__TSK-NNN.json
                  Create it before your first write and update it after EVERY
                  phase (schema in state-and-idempotency.md). It is the only
                  thing that survives an aborted session.

DO: emit per the digest's kind table → run the static ring → run the unit ring
    → heal at most 2 attempts inline → STOP and report.
DO NOT: write the ledger, ask questions, read other tasks' fresh output, or
    touch a file outside the write boundary. If a decision needs the user,
    report STATUS: blocked with the question.

REPORT in exactly this format, nothing else: <the capped report block below>
```

If a needed fact is genuinely absent from the packet, the digest names the one
sanctioned fallback (DATA-MODEL entity slices via `docs/INDEX.yaml`). Everything
else is a `blocked` report, not a guess.

### The capped worker report

Workers answer in exactly this block. No prose outside the fields, no restating
the task, no summarizing the code — hundreds of units of worker prose is how a
manager's context dies mid-container.

```
UNIT: <qualified-id>
FILES: <path> <sha256[:16]>          (one line per file)
STATIC: exit <n>
UNIT_RING: exit <n>
HEALS: <n>
STATUS: green | red | blocked
NOTES: <at most 3 lines>
FAILURE: <at most 20 lines, verbatim tail — only when red>
BLOCKED_ON: <the one question — only when blocked>
```

`STATIC`/`UNIT_RING` carry the **captured numeric exit code**, never a
pass/fail paraphrase (measurement rule below). A ring that could not be run at
all reports `exit -` with the reason on a NOTES line.

### Breadcrumbs — what makes an interrupted unit cheap

The worker writes one small JSON file per unit and updates it after each phase.
This does not violate the sole-ledger-writer rule: it is a separate namespace,
written by the worker, read by the manager, and deleted by the manager the
moment it ledgers the unit. Schema and the resume matrix:
`state-and-idempotency.md`.

Two worker-side rules make it pay off:

- **Write the deliverable to disk as soon as you have it.** Never hold
  generated code in context while reasoning about the next step. Code on disk
  survives an abort; code in a context window does not.
- **Update the breadcrumb after each phase** — one small Write, negligible cost,
  and it is the difference between a resumed run re-running a ring (~5k tokens)
  and re-authoring a deliverable that is already on disk (~100k).

## The verification rings

Verification runs at four widening scopes. Each ring has the same failure
protocol (heal ≤3, escalate on 3, flag on exhaust) — only the test selection
and blast radius differ.

| Ring | Fires when | Runs | Catches |
|---|---|---|---|
| **static** | after *every* task's write | cheapest machine check the stack affords on the touched file(s): `python -m py_compile` / `tsc --noEmit` / `node --check` / `cargo check` / a syntax-level lint. **Non-code deliverables verify by format**: JSON/YAML parse (`python -c "import json,sys; json.load(open(sys.argv[1]))"` / `yaml.safe_load`), SVG/XML well-formedness (`xml.etree`), CSS brace/at-rule sanity, Markdown heading/link resolution — a content file passing these records `verified: static_format`, never `none` | typos, broken imports, malformed code, unparseable assets |
| **unit** | a `test` task completes | exactly the tests that task authored, against the implementation(s) it `depends_on` | a unit that doesn't meet its contract |
| **component** | the last task with `component_ref == C` completes | all unit tests exercising C together | cross-unit interactions inside a component |
| **container** | the last task of `TASKS__<cid>.json` completes | the container's integration-level TSTs + its whole suite | wiring, DI, cross-component contracts |
| **system** | system `test` tasks (e2e/contract) become ready — their cross-file deps enforce "last" | that TST's suite as authored | cross-container behaviour |

(The system ring is just the unit ring applied to system-level test tasks; it
is listed for completeness, not as a separate mechanism.)

The static and unit rings run **inside the worker**. The component, container
and system rings run **in the manager, after a drain** — parallel suites collide
on ports, DBs and fixtures, and even in serial mode the wider rings are the
checkpoint the manager reports on.

How to *run* tests: derive the command from the container's stack — the
scaffold task's outputs/acceptance usually name it (`pnpm --filter X test`,
`uv run pytest`, …). Establish it once per container at the container's first
test run, confirm it works, record it in the ledger
(`containers[<cid>].test_command`) so every later ring reuses it. If no
runnable test command can be established (no runner in the scaffold, missing
toolchain), say so at the gate, record the best level actually reached
(`static_only` for compiled/typechecked code, `static_format` for
format-verified content, `none` only when not even a static check exists),
and continue — generation without verification is degraded, not blocked.

**Measure rings bare — never through a pipe.** Run every ring/gate command
BARE and capture its exit code directly: `cmd | tail -5; echo $?` reports
*tail's* exit, not the suite's — an upstream validator once ran false-green
for a full plan cycle behind exactly that pipe, masking 294 real errors.
When the output must be kept, redirect instead:
`cmd > ring.out 2>&1; echo $?`. The captured numeric exit code — not a
pass/fail paraphrase — is what goes into the ledger (`ring_exit` /
`ring_container_exit`, see `state-and-idempotency.md`) and into any
`failure:` record (`"exit N: …"`).

A test task whose `depends_on` only reaches the scaffold (weakly linked) still
runs at its topo position; the component ring backstops the pairing. Rings
never re-run green suites redundantly: component/container rings run once at
their boundary, not after every member task.

## The checkpoint ladder

Three widening checkpoints: **unit** (ledger write, every unit) → **component**
→ **container**. The component checkpoint is where a long run becomes
reviewable: a container in a real corpus can hold hundreds of tasks across
dozens of components, so a container-only seam means one review after everything
is already built.

At every component boundary: **drain** → component ring → component summary →
doctor check → gate policy.

Component summary — one compact block, no prose:

```
component 'prompt-registry' — 10 tasks (7 impl, 3 test) · ring exit 0
heals 2 · escalations 0 · findings 0
budget 23/next-component · session 2h11m · aicf-cli 312/414
```

Doctor check — cheap, catches drift a mid-run hand-edit or a repair pass
introduced. Run **bare**, capture the numeric exit:

```bash
python "${CLAUDE_SKILL_DIR}/../repair/doctor.py" --quick --docs-dir docs
```

Gate policy `adaptive` (the default) stops and asks only when one of these
**attention triggers** fires — a closed set:

1. component ring exit ≠ 0;
2. a task in the component is `failed`, or was escalated;
3. a new `FND-NNN` was raised during the component;
4. the session budget is reached;
5. the doctor check exits ≠ 0;
6. it is also a container boundary in the bare-run form.

Otherwise: print the summary line and continue. When a trigger fires, gate with
one AskUserQuestion: *continue / stop and run `/sdlc:repair` / stop here* — and
print the resume card (`session-and-limits.md`) with the stop options.
Policy `every component` always gates; `containers only` gates only at trigger 6.

At every **container boundary** (bare-run form): the same, plus the
continue/stop gate naming the next container.

Two properties worth preserving when editing this logic:

- The **doctor check is cheap on purpose** (`doctor.py --quick` is a thin
  wrapper over `crosscheck_artifacts.py`). The full validator sweep belongs to
  `/sdlc:repair --check`; running it at every component boundary would trade the
  cost this design is trying to save.
- The **triggers are a closed set**. Adding "interesting-looking" stop
  conditions turns the adaptive policy back into `every component` and the user
  stops reading the summaries.

## The heal loop

On a red ring (attempts 1–2 run **inside the worker** for unit-ring failures,
inline in the manager for the serialized higher rings; attempt 3 is always
manager-dispatched):

- **Attempt 1 (inline, sonnet).** Read the failure output. Diagnose against
  the *contract*, not the test: the task's embedded `interface_contract`
  (pre-1.3: the ARCH work_unit / deferred API schema) plus the task's
  `acceptance` are the truth. Fix the implementation when it violates the
  contract; fix the **test** only when the test contradicts the contract or
  the embedded `test_spec`. Re-run the ring. Record the attempt in the
  breadcrumb.
- **Attempt 2 (inline, sonnet).** Same, with the previous diff in mind. If
  attempt 1's fix didn't move the failure at all, revert it first — don't
  stack speculative patches.
- **Attempt 3 (escalated, opus).** Spawn a **fresh subagent** (Agent tool,
  `model: "opus"`, synchronous) with a self-contained heal brief. Fresh
  context is the point: the subagent has not seen the two failed fixes'
  reasoning, only their diffs and outcomes, so it won't anchor on them.
- **Exhausted.** Revert to the best-passing state (or leave the last attempt
  with a `// sdlc-code: HEAL-FAILED <qualified-id>` marker if nothing passed),
  set the task `failed` in the ledger with the final failure output, mark
  transitive dependents `blocked`, continue with independent tasks. Every
  `failed`/`blocked` item appears in the close report — this mirrors the
  demo's FR-084 "flag at the Stage-14 HITL gate" rather than halting the whole
  factory for one stubborn unit. If the exhausted diagnosis names an upstream
  contradiction, raise a finding (below) as well.

Component/container/system rings use the same ladder; their heals may touch
any file inside the ring's scope, but never outside it.

`heal_attempts` counts per ring invocation and is recorded on the ledger entry
and the manifest's file entries (telemetry — mirrors the demo's
`GeneratedFile.heal_attempts`).

## The escalation brief (attempt 3)

The subagent gets everything it needs and nothing else — it must not need to
re-derive project context. Like a worker brief, it points at files rather than
pasting them wherever a file exists:

```
You are healing one atomic codegen unit that failed its tests twice.

TASK PACKET:      <path written by `topo_order.py --emit --out-dir`> — the task
  object (embedded interface_contract / test_spec + the per-kind grounding
  slices) plus its requirement_context (FR/NFR/WKF/ACR statements).
INTERFACE CONTRACT: the packet's `interface_contract`; pre-1.3: the ARCH
  work_unit slice or the API operation schema the unit defers to.
ACCEPTANCE:       the packet's `acceptance` list.
CURRENT FILES:    <paths of target_files and the test file(s)> — read them.
BREADCRUMB:       <path> — carries the prior attempts' diffs and outcomes.
FAILURE OUTPUT:   <the current failing run, verbatim>
TEST COMMAND:     <the recorded ring command>

Fix the implementation (or the test, only if it contradicts the contract).
Run the test command. Iterate until green or you are confident the failure is
not fixable at this scope — then say exactly why, naming the upstream artifact
and symbol you believe is wrong.
Report: what you changed, final test output.
```

Run it with `run_in_background: false` — the loop needs the verdict before
deciding `done` vs `failed`. Set `escalated: true` on the ledger entry and
`generated_by_model: opus` on the manifest entries for files the subagent
changed. If the Agent tool is unavailable, run attempt 3 inline instead —
but first re-read the contract slices from disk and explicitly re-derive the
diagnosis from scratch (reset-assumptions protocol), and note the degradation
in the close report.

## Raising a finding

Codegen is where spec defects finally become visible: a contract that doesn't
determine behaviour, a test that contradicts the thing it tests, a path that
cannot exist. **This skill never fixes them** — it never edits `docs/`. It
records them so `/sdlc:repair` can localize the defect to its source stage and
fix it there.

Append an `FND-NNN` entry to `.claude/skills-state/sdlc-findings.yaml` (schema:
`../../repair/FINDINGS.schema.yaml`) when — and only when — one of these fires:

1. a worker reports `STATUS: blocked` with a question about the **contract**
   (not about the environment or the toolchain);
2. attempt-3 escalation fails **and** its diagnosis names an upstream
   contradiction;
3. a `test_spec` cannot be realized as written because it contradicts the
   `interface_contract` it exercises (`edge-cases.md`);
4. an `interface_contract` genuinely underdetermines the behaviour the task's
   `description`/`acceptance` demands;
5. `target_files` contains an absolute path or `..`, or the task's `acceptance`
   is not satisfiable as written, or a dependency edge is missing (the ring
   fails because a prerequisite symbol was never scheduled);
6. the component-boundary doctor check exits non-zero.

Nothing else. This list is closed on purpose: a findings queue that fills with
every ordinary red test is a queue nobody reads. A failing unit is a `failed`
task; a failing *specification* is a finding.

Each entry carries the evidence that made it visible — the failing assertion,
the contract excerpt, the captured exit code — and a `suspected_stage` /
`suspected_source` guess. **The guess is not authoritative**: localization is
`/sdlc:repair`'s job, and it will often land a stage earlier than the one that
looked wrong from here. Counter-signal to respect: the artifact that *looks*
wrong from inside codegen is usually a task embed, and per CLAUDE.md §9 an
embed is never the source — the upstream it was copied from is.

Reconcile the `FND` counter the way every sdlc skill reconciles an id counter:
on append, take `max(last_ids.FND on disk, highest FND-NNN present)` and
increment from there.

## Failure containment

- A `failed` task never blocks tasks that don't depend on it.
- `blocked` is transitive but lazy: computed from the ledger at scheduling
  time, not stored as a cascade.
- `retry <qualified-id>` at any gate re-queues a failed task with
  `heal_attempts` reset; its `blocked` dependents thaw automatically when it
  lands.
- Two consecutive *systemic* failures (e.g. the test runner itself broken,
  the scaffold missing) are not per-unit problems — stop the loop and surface
  at a gate instead of burning heal attempts on every task.

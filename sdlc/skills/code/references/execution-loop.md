# Execution loop — scheduling, waves, rings, heal, escalation (sdlc-code)

Read this on entering Phase 4. It defines the order tasks run in, the
manager/worker wave protocol, the verification rings, the heal loop, and the
opus escalation.

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
what makes the component ring boundary meaningful.

Never hand-compute the order. Run the tool; it also diffs against the ledger:

```bash
python "${CLAUDE_SKILL_DIR}/topo_order.py" --scope all --state .claude/skills-state/sdlc-code.state.yaml
```

## Waves & workers (the manager protocol)

The session is the **manager**; source files are written by **worker
subagents** dispatched in parallel waves. The rules that make this safe:

- **Wave composition.** From the ready set, pick up to **3 work units** — a
  work unit is one implementation task plus the test task(s) whose
  `depends_on` reaches it (impl + its tests heal together, so they share a
  worker). The units' combined `target_files` (+ test files) must be
  **pairwise disjoint** — a candidate overlapping another pending task's
  files waits or runs **solo** (scaffold tasks, barrel/exports files, shared
  config). When in doubt, solo: correctness beats parallelism.
- **The worker brief is the task packet.** Build the packet with
  `python "${CLAUDE_SKILL_DIR}/topo_order.py" --emit <qualified-id> …` — never
  by `Read`-ing the TASKS file (a shard can be hundreds of KB). It prints the
  verbatim task JSON (v1.4 embeds included) joined with a `requirement_context`
  slice (the task's FR/NFR/WKF ids → their PRD statements), so the worker's
  requirement grounding rides in the packet, not a per-worker PRD read. Add the
  container tech-stack slice, the provenance-marker and
  path-safety rules from `emit-rules.md`, the established test command, and
  the write boundary (its `target_files` + the test file, nothing else).
  Workers are **non-interactive**: no AskUserQuestion, no ledger writes, no
  reading other tasks' fresh output. A worker that hits a decision only the
  user can make reports `blocked: <question>` instead of guessing.
- **Worker verification**: static ring, then unit ring, heal **≤2 attempts**
  inline, then stop and report: files written (+ sha256), ring outcomes,
  heal count, failure output if red.
- **Integration**: as each worker returns, the manager verifies the reported
  hashes against disk, writes the ledger (manager is the **sole ledger
  writer**), and refills the wave. Attempt 3 (opus) is always
  manager-dispatched — see "The escalation brief".
- **Serialization points**: component/container/system rings run in the
  manager between waves (never inside workers — parallel suites collide on
  ports/DBs/fixtures). A container boundary additionally carries the bare-run
  continue/stop gate.
- **Fallback**: no Agent tool → execute units inline one at a time with the
  identical per-unit protocol; say so in the close report.

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

A test task whose `depends_on` only reaches the scaffold (weakly linked) still
runs at its topo position; the component ring backstops the pairing. Rings
never re-run green suites redundantly: component/container rings run once at
their boundary, not after every member task.

## The heal loop

On a red ring (attempts 1–2 run **inside the worker** for unit-ring failures,
inline in the manager for the serialized higher rings; attempt 3 is always
manager-dispatched):

- **Attempt 1 (inline, sonnet).** Read the failure output. Diagnose against
  the *contract*, not the test: the task's embedded `interface_contract`
  (pre-1.3: the ARCH work_unit / deferred API schema) plus the task's
  `acceptance` are the truth. Fix the implementation when it violates the
  contract; fix the **test** only when the test contradicts the contract or
  the embedded `test_spec`. Re-run the ring.
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
  factory for one stubborn unit.

Component/container/system rings use the same ladder; their heals may touch
any file inside the ring's scope, but never outside it.

`heal_attempts` counts per ring invocation and is recorded on the ledger entry
and the manifest's file entries (telemetry — mirrors the demo's
`GeneratedFile.heal_attempts`).

## The escalation brief (attempt 3)

The subagent gets everything it needs and nothing else — it must not need to
re-derive project context:

```
You are healing one atomic codegen unit that failed its tests twice.

TASK PACKET (from `topo_order.py --emit <qualified-id>`): <the task object,
  qualified id included — carries the embedded interface_contract / test_spec
  (v1.3) and the per-kind grounding slices (v1.4) — plus its requirement_context
  (the task's FR/NFR/WKF ids resolved to their PRD statements)>
INTERFACE CONTRACT: <the task's interface_contract; pre-1.3: the ARCH
  work_unit slice or the API operation schema the unit defers to>
ACCEPTANCE: <the task's acceptance list>
CURRENT FILES: <path + full content of target_files and the test file(s)>
FAILURE OUTPUT: <the current failing run, verbatim>
PRIOR ATTEMPTS: <diff + one-line outcome of attempts 1 and 2>
TEST COMMAND: <the recorded ring command>

Fix the implementation (or the test, only if it contradicts the contract).
Run the test command. Iterate until green or you are confident the failure is
not fixable at this scope — then say exactly why. Report: what you changed,
final test output.
```

Run it with `run_in_background: false` — the loop needs the verdict before
deciding `done` vs `failed`. Set `escalated: true` on the ledger entry and
`generated_by_model: opus` on the manifest entries for files the subagent
changed. If the Agent tool is unavailable, run attempt 3 inline instead —
but first re-read the contract slices from disk and explicitly re-derive the
diagnosis from scratch (reset-assumptions protocol), and note the degradation
in the close report.

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

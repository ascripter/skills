# Interview mechanics (sdlc-task)

The AskUserQuestion batch format, EXIT semantics, and the importance-tier state
machines are **identical across all SDLC skills**. Rather than restate them, this
file points at the canonical spec and notes the task-specific bits.

## Canonical spec — read this

The four importance tiers (`med` / `high` / `critical` / `nested_freeform`), the
per-item `critical` state machine (propose → challenge → detail → approve →
next), iteration caps, the EXIT-mid-flow rules, and the **scope-completeness
sweep** for `critical synthesis: true` themes are specified once in:

> `sdlc/skills/prd/references/importance-flows.md`

Read it on entering Phase 6. Everything below is the delta for `task`.

## AskUserQuestion batch rules (recap)

- 2–4 questions per call (hard limit 4). Recommended/inferred option first.
- A free-text "Other" is always added by the tool — the user may type `EXIT`
  there to abort (see SKILL.md → "Reserved EXIT command").
- `med` questions batch together. `high` questions each get a draft-then-approve
  mini-section (cap 3 iterations). `critical` questions run the full per-item
  state machine — here, **one task at a time**.

## The per-task `critical` flow (system_tasks / container_tasks)

Both themes are `critical synthesis: true`. Run each candidate task through:

1. **propose** — show the draft: `kind`, `title`, and what it realizes (the
   `component_ref` it implements, the `TST-NNN` it authors, the ARCH edge it
   wires, or the FR/NFR it satisfies). State where the candidate came from
   ("implementation task for component `auth-service`" / "test task realizing
   `TST-007`" / "integration task for edge `web-frontend`→`backend-api`").
2. **challenge** — confirm the `kind` and the scope. An implementation task must
   be scoped to one component (`component_ref`) or one contract
   (`touches_operations`) and build exactly one work_unit (`target_symbol`) in one
   file (`target_files`) — push back on a task that tries to do two work_units /
   two components at once (split it) or a vague task with no scope.
3. **detail** — fill `depends_on` (the ordering edges), `outputs`
   (what the codegen agent emits), and `acceptance` (machine-checkable done
   conditions). For a `test` task, `acceptance` is usually "the
   tests realizing `TST-NNN` pass".
4. **approve** — set the task's `status: confirmed`; persist state.
5. **next** — move to the next candidate.

After the per-item loop closes, run the **scope-completeness sweep** and then the
**coverage check** — both described in `coverage-and-defer.md`.

## Ordering is part of the interview, not an afterthought

Unlike `test` (where tests are independent), tasks form a graph. As each task is
confirmed, capture its `depends_on` immediately — it is far cheaper than
back-filling the whole DAG at the end. A good default: every container task
depends on that container's `scaffold` task; every container `scaffold` depends
on the system repo `scaffold` (`TASKS/TSK-NNN`); a consumer's integration task
depends on the provider's contract/implementation task. See
`granularity-and-ordering.md`.

## Batching the cheap fields

Within one task's `detail` step you may batch `depends_on` + `outputs` +
`acceptance` into a single AskUserQuestion call (≤4 questions) to keep the
interview brisk. Never batch across two different tasks — the per-item boundary is
what makes EXIT/resume clean.

## State after every step

Write `.claude/skills-state/sdlc-task.state.yaml` after every confirmed batch,
mini-section, and per-task approval — including Phase 3 draft confirmation and
Phase 5 pre-fill confirmations. The `current_task` and `defined_tasks` fields
make resume land exactly where the user left off.

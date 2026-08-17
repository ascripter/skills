# Session, limits, and the resume card (sdlc-code)

Read this in Phase 3 (the plan gate sets the budget) and at every stop. A
codegen run over a real task graph does not fit one session — it fits several,
and the difference between a cheap continuation and an expensive one is entirely
about *how* the user comes back.

---

## The one rule about coming back

**After any interruption, start a FRESH session and re-invoke `/sdlc:code`.
Never `/resume`, never `--continue`.**

The reason is structural, not a preference. This skill's handoff is the
**ledger plus breadcrumbs**, not the transcript. A fresh manager reconstructs
its entire working state in two tool calls — read the state file, run
`topo_order.py` — and that state is *better* than the transcript's, because it
has been reconciled against what is actually on disk. Resuming instead replays
every turn of a long run back into context to rediscover facts the ledger
already holds, and it starts the new window already deep in its budget.

The single exception: the session died **mid-gate**, with a question asked and
unanswered, and nothing written since the last ledger entry. Then `/resume`
saves re-answering one question. That is the only case; when in doubt, fresh.

Say this explicitly in the resume card. Users reach for `/resume` by habit, and
on this skill the habit is expensive.

## Session budget

Chosen at the plan gate, recorded in `session.budget`. It is **not** a token
estimate — predicting a unit's token cost would itself cost tokens and be wrong
often enough to mislead. It is a **planned stopping point**, which is the part
that actually helps: an unpredictable mid-unit kill becomes a clean boundary
stop with a resume card.

| Mode | Stops when |
|---|---|
| `next_component` (default) | the current component's checkpoint completes |
| `next_container` | the current container's ring closes |
| `units` | `units_done` reaches the chosen count |
| `unbounded` | never — the user is watching, or the graph is small |

Budget exhaustion is attention trigger 4: drain, close the boundary ring, print
the resume card, stop. It is a normal, successful end to a run — report it as
one, not as a failure.

`session.budget.units_done` counts units completed **this session** and resets
each invocation. It is what the `budget: 23/next-component` line reports.

## Drain triggers

"Drain" = stop dispatching new units, let in-flight units finish, ledger them,
then act. Never kill a worker mid-unit if draining is possible — a killed worker
wastes everything since its last breadcrumb phase.

Drain on:

1. a component or container boundary;
2. a solo task reaching the head of the ready queue (directory-pinned or
   shared-file targets);
3. any serialized ring;
4. session budget reached;
5. **a rate-limit or usage warning surfaced by the harness** — the only
   forward-looking signal available, so act on it the moment it appears rather
   than pressing on and being killed mid-unit;
6. two consecutive systemic failures (`execution-loop.md` → failure
   containment);
7. `EXIT` at any gate.

## Interruption symptoms and what actually happens

| What happened | What survives | What to do |
|---|---|---|
| Usage limit hit mid-worker | files already written + the breadcrumb up to its last phase | fresh session, `/sdlc:code <same scope>` — the unit resumes at its phase |
| Usage limit hit between units | everything (the ledger was written) | fresh session, same command |
| Context compaction mid-run | everything — the manager holds no unique state | nothing; the run continues, and a fresh session would be equivalent |
| User Ctrl-C / `EXIT` | everything up to the last ledgered unit, plus breadcrumbs | fresh session, same command |
| Machine died / process killed | same as a limit hit | fresh session, same command |

In every row the answer is the same command, because the ledger makes the run
idempotent. That uniformity is the point: the user should never have to work out
*which kind* of interruption they had.

## Signalling risk before it bites

The manager cannot see its remaining quota, so it must not pretend to. Report
only what it can actually measure, on every component summary:

```
budget 23/next-component · session 2h11m · aicf-cli 312/414
```

- `units_done` this session and the budget it is counting toward;
- elapsed wall-clock since `session.started_at`;
- absolute progress through the scope.

Those three let the user judge the risk themselves. Do **not** editorialize
("you may hit your limit soon") on the basis of a number the skill cannot see.
The one exception is a harness-surfaced rate-limit warning — that is real
information, and it triggers an immediate drain and a resume card, with the
reason stated plainly.

A long run should also just *stop* on schedule rather than gamble: that is what
the default `next_component` budget is for.

## The resume card

Printed at **every** stop: budget stop, gate stop, `EXIT`, failure abort, and a
completed graph. Never omit it because the run ended well — its job is to tell
the user what to type, and that is needed most when nothing dramatic happened.

```
── /sdlc:code — where you are ─────────────────────────────
Session:   23 units · 4 components · started 14:02 (2h 11m)
Done:      312 / 414 aicf-cli  ·  0 failed  ·  2 blocked
Next:      component 'stage-node-runtime' (65 tasks)
Resume:    /sdlc:code aicf-cli        ← in a NEW session
Why new:   the ledger is the handoff, not this transcript.
Findings:  2 open (FND-003, FND-004) → /sdlc:repair first
```

Rules for filling it in:

- **`Next:`** is what `topo_order.py --next` resolves to, quoted — never a
  hand-guess. When the graph is fully executed, it names `/sdlc:deploy` instead.
- **`Resume:`** is a command the user can paste verbatim, carrying the same
  scope and modifiers the stopped run had (`--parallel` included).
- **`Findings:`** appears only when open findings exist, and it leads with
  `/sdlc:repair` when a finding blocks progress (a failed unit whose diagnosis
  named an upstream contradiction), otherwise it is informational.
- **`Why new:`** stays on the card even in the happy path — see the one rule
  above.
- Omit rows that have nothing to say rather than printing zeros; a card with
  five honest lines is read, a card with twelve is not.

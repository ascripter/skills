# Edge cases (sdlc-repair)

The theme: **diagnosis degrades gracefully, edits never happen implicitly.**
This skill has write access to every artifact in the chain, which makes it the
one skill in the pipeline that can do real damage. Every unusual situation below
resolves toward "surface it and ask", not "make a reasonable guess".

## Inputs and preconditions

- **No findings queue and a clean sweep** → nothing to repair. Say so, print the
  sweep, and stop. This is a success, not an empty result: `/sdlc:repair --check`
  returning green is the whole point of having a doctor.
- **A findings queue that fails `validate_findings.py`** → refuse to edit
  anything. A corrupted queue means ids may be ambiguous, and appending or
  resolving against it can lose a finding. Show the validator's errors and offer
  to repair the queue file itself (that edit is in scope; artifact edits are not
  until it validates).
- **`docs/` absent or empty** → nothing to diagnose. Point at `/sdlc:prd`.
- **The project never ran `/sdlc:setup`** → no `docs/INDEX.yaml`, so no
  `--refs` blast radius. Degrade to `crosscheck_artifacts.py` plus a targeted
  grep, say so at the confirmation gate, and record it in the resolution. Do not
  silently narrow the radius.
- **A validator or the crosscheck linter is missing from the skill tree**
  (partial install) → that check is *skipped*, never assumed green. A skipped
  check is reported as skipped in the sweep and never produces a finding.

## Localization

- **The walk terminates at `code`** → the finding was mis-raised: generated code
  is an output, never a source. Close it `wontfix` naming the reason, and treat
  the underlying red as a `failed` task for `/sdlc:code` to heal.
- **The walk terminates nowhere** (every stage is internally consistent and the
  contradiction only exists between two of them) → the earliest stage that
  *should* have adjudicated is the source, which is usually `prd`. If PRD is
  genuinely silent, this is a product decision: ask, and record the answer as a
  new FR/NFR rather than as a downstream patch.
- **Two findings localize to the same symbol** → merge them: resolve one and
  mark the other `duplicate` with `duplicate_of`. Never fix the same symbol
  twice in one run; the second edit will be reasoning against a file the first
  already changed.
- **The finding's `suspected_stage` is right** → say so plainly and move on.
  Confirming the raiser's guess is a normal outcome; do not manufacture a
  more interesting localization to justify the walk.

## Editing

- **The source artifact has uncommitted hand-edits** (its content hash differs
  from what every downstream `upstream_provenance` recorded) → surface it before
  editing. Someone is mid-change; layering a repair on top produces a file
  neither party intended.
- **The fix requires deleting an item** (an entity, a work_unit, a TST) → never
  delete implicitly. Deletion changes the *set* of downstream items, so it is a
  `re-invoke` case by definition, and it needs explicit approval naming what
  disappears and what currently references it.
- **The radius reaches an artifact that does not exist yet** (a repair to PRD
  while `api` has never run) → that is not a gap. Stages that have not run have
  nothing to reconcile; note them as "not yet authored" and exclude them from
  the radius.
- **A downstream artifact is `status: draft`** → repair it anyway, but say so:
  a draft artifact will be rewritten by its own skill, and the edit may not
  survive. Prefer `re-invoke` for draft stages.
- **Write-permission error mid-repair** → stop immediately, do not continue to
  the next finding. Report which artifacts were already edited and which were
  not: a half-propagated fix is the one state worse than an unfixed defect, and
  the user needs to know exactly where it stopped.

## Verification

- **A validator was already red before the repair** → record its before and
  after exit codes and state plainly that the pre-existing failure is unrelated.
  Never let an unrelated red be read as caused by the repair, and never claim a
  repair fixed something it did not touch.
- **The repair fixes the finding but breaks a coverage gate** (e.g. adding an FR
  leaves it traced by nothing) → that is an incomplete forward-propagation, not
  a validator problem. Either complete the propagation or record the deferral as
  a `WRN-NNN` in the artifact that owes the coverage (CLAUDE.md §6 — trace or
  defer, never silent omission).
- **Verification cannot run** (missing pydantic, no python on PATH for a
  subprocess) → do not mark anything `resolved`. Leave findings `triaged`, state
  what could not be verified, and say what the user should run.

## Session

- **EXIT mid-triage** → persist the state file with `status: aborted`, leave
  every unresolved finding as it was, and confirm which artifacts were already
  edited. Findings already resolved stay resolved — the queue is append-only and
  resolutions are audit records, not a transaction.
- **Interrupted mid-repair** → on the next invocation, reconcile: for each
  finding marked `triaged` with a partial `artifacts_touched` list, re-verify
  those artifacts against disk before continuing. Re-applying an edit that
  already landed is the common failure mode here.
- **A finding whose artifacts have changed since it was raised** → re-read
  before trusting the evidence. Evidence is a snapshot; the defect may already
  be gone, in which case close it `resolved` with `mode: none` and a note that
  it was fixed elsewhere.

## Boundaries

- This skill **never writes source code** and never touches the generated tree.
  Its output is artifacts under `docs/`, the findings queue, and its own state
  file.
- It **never runs another skill.** `re-invoke` mode prints a command sequence
  for the user; it does not execute one.
- It **never edits `.claude/skills-state/sdlc-code.state.yaml`.** That ledger
  belongs to `/sdlc:code`, and the `stale` handback works precisely because
  repair leaves it alone.
- `CLAUDE.md` is not touched: this skill owns no artifact and adds no pointer
  bullet.

# Skills fix plans — overview

Source of truth for findings: `SKILLS-AUDIT.md` (immutable — plans cite SK-NN, never
edit it). Audited version: plugin cache **0.3.6**; re-locate every line number against
skills-repo HEAD before editing.

Goal: make the sdlc skills produce, first-try, the artifact properties the AICF corpus
needed four hand-executed fix plans to reach — so the next project's Stage-13 output is
/sdlc:code-ready without a PLAN1–PLAN4 cycle.

## Plan set and execution order

Execute in this order (rationale below):

| # | Plan | Skills touched | Findings | Status |
|---|---|---|---|---|
| 1 | SPLAN2 — task schema & validator repairs (incl. D2 priority removal) | task | SK-02, SK-03, SK-12..SK-20 | **EXECUTED 2026-07-19** |
| 2 | SPLAN1 — test→subject seam + shared test infrastructure | test, task | SK-06..SK-11, SK-16 | **EXECUTED 2026-07-19** |
| 3 | SPLAN3 — arch work-unit contract quality | arch | SK-21..SK-24 | open |
| 4 | SPLAN4 — code packets & execution loop | code | SK-04, SK-25..SK-28 | open |
| 5 | SPLAN5 — pipeline integrity + upstream skills + CLAUDE.md delta | setup, prd, ux, data, api, design, arch/task (D2 loaders), CLAUDE.md | SK-01, SK-05, SK-29..SK-35 | open |

**Why SPLAN2 first:** the D2 priority removal deletes/rewrites the same task-validator
regions (required-field loops, check #22, check #23's could-arm, the granularity
invariants) that SPLAN1's new checks land next to — remove before adding. **SPLAN1
second:** it spans test+task and is the highest-value seam (the corpus BLOCKER's root
cause). **SPLAN5 last:** its CLAUDE.md delta documents conventions the earlier plans
introduce, and its D2 downstream-loader re-scope (ux/data/api/arch/task read the flat
`features` list) should land after SPLAN2 removed the task-side priority machinery.

D2's cross-plan split, to be explicit: **SPLAN2** = task-side removal; **SPLAN1** =
test-side per-TST `priority` removal (it edits those schema regions anyway); **SPLAN5**
= prd schema change + every downstream must-have-keyed loader.

## Binding conventions (every plan)

1. **Self-contained execution.** Each plan embeds its evidence; the executor needs no
   access to the AICF repo (exception: SPLAN5's named porting source, transferred by
   the repo owner).
2. **Lockstep contract.** Every schema change lands in BOTH `<NAME>.schema.yaml` and
   `validate_schema.py`, plus `_smoke/` fixtures (at least one valid + one
   intentionally-broken case per new rule) and the skill's `evals/` where present.
3. **Version-gate new blocking checks** on the artifact's declared version
   (`*_version` in metadata); new checks on existing fields start as **warnings**.
   In-repo precedent: task `interface_contract` "REQUIRED … at artifact version >= 1.3
   (older artifacts warn instead)" (`TASKS__CONTAINER.schema.yaml:160-161`).
   **Amendment (2026-07-19, from SPLAN2/SPLAN1 execution):** the AICF corpus
   self-stamps versions ABOVE the stock schema (TEST-STRATEGY containers at 1.9;
   TASKS containers at 1.8/1.9), so "gate on the next version" is porous — the
   corpus walks through it. A new blocking check's floor must CLEAR the corpus's
   self-stamped numbers (use 2.0), and SHOULD additionally shape/mode-gate
   (`meta_corpus_dialect`, PRD shape) per the FR_GATE precedent
   (task `validate_schema.py`, `load_prd_id_families`) — a mode flag can't be
   version-stamped past.
4. **Removals keep readers tolerant.** A removed field (e.g. `priority`) is never
   *required* again but stays *accepted* on old artifacts (parse-and-ignore); coverage
   loaders read old + new shapes and union them.
5. **SKILL.md stays lean** (~500-line budget): new mechanics go into `references/` and
   SKILL.md points at them.
6. **⚠ decision protocol:** a ⚠ OPEN box means the repo owner decides; each carries a
   recommendation. If an executor finds a ⚠ still OPEN, stop and ask — don't pick
   silently.
7. **Per-plan verification suite** (run from the skills repo root):
   - `python sdlc/skills/<skill>/validate_schema.py --path <each _smoke fixture>` —
     expected exit codes per fixture header.
   - The skill's `evals/` runner where present.
   - **Live meta-corpus regression (optional but recommended):** with the AICF repo
     checked out beside this one, run the touched validators against its `docs/`
     (task: exit 0; arch: exit 0; test: exit 0). Expected deltas are stated per plan
     (e.g. SPLAN1 collapses the 191+8 placement advisories).
   - **Measurement rule:** never read a validator's exit code after a pipe —
     `cmd | tail; echo $?` reports tail's exit. Redirect to a file and `echo $?` on
     the bare command.
8. **Each plan ends with an execution ledger** — mark steps done with a one-line
   result; resume from the ledger.
9. **Runtime strings are cp1252-safe** (2026-07-19, SPLAN2 lesson): any string a
   validator can `print()` at runtime (warnings, errors, summaries) must contain
   only cp1252-encodable characters — a `→`/`≥`/`⊆` in a warning crashes
   `print()` with UnicodeEncodeError on the Windows console, turning exit 0 into
   exit 1. Non-ASCII typography is fine in comments and docstrings only.

## Decision log

- **D1 (2026-07-16, resolved):** plans grouped per-theme.
- **D2 (2026-07-16, resolved):** priority paradigm retired PIPELINE-WIDE (see SK-05
  for the verified blast radius). PRD keeps a single flat `features` list;
  milestones deleted; per-TST and per-task priority removed; every must-have-keyed
  coverage check re-scopes to all FRs.
- **⚠A (2026-07-19, resolved):** infra task kind = (i) new `kind: test_infrastructure`.
- **⚠B (2026-07-19, resolved):** `inputs[]` = drop (owner condition — "tell the skill
  directly which inputs it shall take" — satisfied by the v1.4 self-contained embeds;
  rationale recorded in SPLAN2 step 3).
- Open ⚠ boxes remaining: SPLAN5 ⚠C (`mitigation_refs` restriction), SPLAN5 ⚠D
  (`paradigm` required at complete).
- **Addendum 2026-07-19:** dogfooding findings A.1–A.6 verified already-implemented at
  HEAD as `Gap-1`..`Gap-6` (see README addendum for the mapping + plan-side
  reconciliation notes in SPLAN2/SPLAN3). Executors: treat Gap code as existing
  neighbors, not greenfield.
- **SPLAN1 executed 2026-07-19.** Deviations (all in its ledger/reconciliation
  note): seam check silent (not advisory) in meta-dialect; #27–#30 as ungated
  warnings; test schemas → 2.0, task container stays 1.5. Post-execution
  corpus baselines: test validator **exit 0** (was exit 1 / 224 errors; 225
  warnings = 222 work-unit-coverage + 3 shared-infra true positives); task
  validator exit 0 with **8** warnings (was 207 — placement class collapsed).
  Pre-existing defect repaired in passing: the test eval gold's TST-001..008
  collided with the staged system file under global uniqueness → renumbered
  006-013.

---
name: repair
description: >
  Explicitly invoked DIAGNOSTIC + REPAIR skill for the SDLC artifact chain.
  Runs a doctor sweep (every skill validator + the cross-artifact linter + the
  docs-index dangling-reference gate), merges it with the FND-NNN findings
  /sdlc:code raised during codegen, then BACK-PROPAGATES each finding to the
  earliest artifact whose content is actually wrong, fixes it there, and
  forward-propagates along the computed reference graph — surgically, or by
  handing the user the exact downstream re-invocation sequence. Three forms:
  /sdlc:repair (full flow), /sdlc:repair --check (read-only sweep, edits
  nothing), /sdlc:repair FND-003 FND-005 (named findings only). Hands back to
  /sdlc:code automatically: edited task artifacts change their fingerprints, so
  affected tasks show up as `stale` at the next codegen plan gate.
  Trigger only on /sdlc:repair or a direct natural-language request to
  diagnose/repair the sdlc artifact chain — never auto-trigger from a generic
  request to fix a bug or a failing test.
user-invocable: true
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read Write Edit Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-repair

The pipeline's repair stage. Every other sdlc skill *writes forward*: it
consumes upstream artifacts and produces one more. This skill is the only one
that **walks backward** — from a defect that surfaced late (usually during
`/sdlc:code`, which is where under-specification finally becomes visible) to the
stage that actually caused it — and then carries the fix forward again.

It exists because the alternative is worse. Left to itself, a codegen agent that
hits an underdetermined contract will patch what it can reach: the task embed,
or the generated code. Both re-diverge the next time anything regenerates, and
the real defect stays in ARCH or PRD, invisible, waiting.

**Outputs:**

- Edits to the artifact(s) under `docs/` that actually hold the defect, with
  `metadata` version bumps and changelog entries.
- `.claude/skills-state/sdlc-findings.yaml` — the `FND-NNN` queue, with a
  `resolution` block per finding it closed (schema: `FINDINGS.schema.yaml`).
- `.claude/skills-state/sdlc-repair.state.yaml` — session state, for resume.
- A close report naming the stale tasks `/sdlc:code` will offer to rebuild.

It owns no `docs/` artifact of its own, so it injects **no** `CLAUDE.md` pointer.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — dispatch, the six phases, the gates. |
| `FINDINGS.schema.yaml` | Canonical schema for `.claude/skills-state/sdlc-findings.yaml`. |
| `validate_findings.py` | Pydantic v2 validator for the queue (+ id/resolution integrity checks). |
| `doctor.py` | The sweep runner. `--quick` = cross-artifact linter only (what `/sdlc:code` runs at component boundaries); default = the full sweep. |
| `references/back-propagation.md` | Finding → source stage. The localization rules. Read in Phase 2. |
| `references/forward-propagation.md` | Blast radius, surgical vs re-invoke, verification, handback. Read in Phase 4. |
| `references/edge-cases.md` | Unusual situations. |

## Invocation dispatch

Classify `$ARGUMENTS`:

1. **No arguments** → **full flow**: sweep, merge with open findings, localize,
   confirm, fix, verify, hand back. Phases 1–6 below.
2. **`--check`** → **read-only doctor**: run the full sweep, write any new
   findings to the queue, print the report, stop. **Edits no artifact.** This is
   the form to run before starting a long codegen session, and in CI.
3. **One or more `FND-NNN` arguments** → work only those findings (they must
   exist in the queue and be `open` or `triaged`). Skips the sweep; everything
   else is identical.
4. Anything else → print the three forms and abort.

## Preconditions (a CLOSED set — do not invent gates)

- `docs/` exists and holds at least one artifact. Otherwise there is nothing to
  diagnose — point at `/sdlc:prd`.
- If `.claude/skills-state/sdlc-findings.yaml` exists, it must pass
  `python "${CLAUDE_SKILL_DIR}/validate_findings.py"`. A corrupted queue is
  repaired first (that edit is in scope); no artifact is touched until it
  validates.
- Nothing else. Missing artifacts are *skipped checks*, not errors — this skill
  must be runnable at any pipeline stage, including halfway through. Draft
  status, dirty git trees, and incomplete stages are observations for the
  report, never grounds for refusal.

## The flow

### Phase 1 — Session & queue

Read `.claude/skills-state/sdlc-repair.state.yaml` if present. `in_progress`
→ offer resume / restart / discard. Load and validate the findings queue.

On resume, reconcile before continuing: for every finding left `triaged` with a
partial `artifacts_touched` list, re-verify those artifacts against disk. The
common failure mode here is re-applying an edit that already landed.

### Phase 2 — Sweep & localize

Run the doctor (bare; capture the numeric exit code — never read an exit status
after a pipe, CLAUDE.md §11):

```bash
python "${CLAUDE_SKILL_DIR}/doctor.py" --docs-dir docs --emit-findings
```

It runs every skill validator against its canonical artifact, every
`TASKS__*.json` shard, `crosscheck_artifacts.py`, and the docs-index dangling
gate; appends one finding per failed check (deduplicated against still-open
findings); and reports each check's captured exit code. Skipped checks (artifact
absent, tool absent) are reported as skipped and never become findings.

Merge the sweep's findings with the queue's existing open ones, then **localize
each**. Load `references/back-propagation.md` now — it holds the rules. The
shape of the work:

- walk **backwards** from where the finding surfaced to the earliest artifact
  whose content is wrong;
- never localize to `code` (generated output is never a source) and never to a
  task **embed** (CLAUDE.md §9 — the artifact it was copied from is the source);
- read the upstream slice an embed was copied from and compare: same wrong thing
  → upstream is the source; different → the embed is merely stale;
- compute the blast radius rather than guessing it:
  `python .claude/sdlc/docs_index.py --refs <symbol>`.

**Read by slice, not by slurp.** The upstream artifacts are large; use
`docs/INDEX.yaml` line ranges (`.claude/rules/sdlc-docs-access.md`) to read only
the symbol under suspicion and its inbound sites.

### Phase 3 — Confirm

One `AskUserQuestion` per finding (batch 2–4 when several are mechanical and
low-stakes). Present, per finding: the **walk** (surfacing site → stages
examined → chosen source → why), the proposed fix, the computed blast radius,
and the mode (`surgical` / `re-invoke`).

Options: *fix as proposed* (position 1) / *fix differently* (free text) / *defer*
(record a `WRN-NNN` in the source artifact and mark the finding `wontfix`) /
*wontfix*.

`references/back-propagation.md` names when to **ask rather than decide**:
`missing_requirement` findings, two equally defensible stages, any fix that
changes product behaviour rather than clarifying a description, and any walk
that terminates at PRD. Mechanical cases (a stale embed re-slice, a dangling ref
whose owner `--refs` makes obvious) can be batched.

`EXIT` in any free-text field stops the run: persist state as `aborted`, confirm
which artifacts were already edited, stop.

### Phase 4 — Fix at the source

Load `references/forward-propagation.md`. Two modes, chosen by one question:
does the fix change the **set** of downstream items, or only their **content**?

- **`surgical`** (content) — edit the source; bump
  `metadata.<name>_version` and append one changelog line in the same write;
  re-derive any prose the change invalidated (CLAUDE.md §8); **re-slice every
  task embed copied from the changed symbol**; then walk the rest of the
  `--refs` set. Order is source-first, then outward.
- **`re-invoke`** (set) — fix the source, then **stop and print the exact
  downstream command sequence** in pipeline order (`/sdlc:arch <cid>` →
  `/sdlc:test <cid>` → `/sdlc:task <cid>`). This skill never runs another skill:
  those are interviews and the user owns them. Each already carries the §7
  upstream-change reconciliation contract, so it will detect the changed hash
  and run its own delta-review. Leave such findings `triaged`, not `resolved`,
  until the user reports the re-invocations done.

When in doubt, prefer `re-invoke`: a surgical edit that should have been a
re-invocation leaves a downstream artifact internally consistent but missing an
item, and no coverage gate catches an item that was never created.

### Phase 5 — Verify

Re-run, **bare**, capturing every numeric exit code: each touched artifact's
validator, `crosscheck_artifacts.py`, `docs_index.py` (regenerate) and
`docs_index.py --check`. Validate **every artifact touched**, not just the
source.

A check that was already red before this repair, for an unrelated reason, is
reported with its before/after exit codes and explicitly called out as
pre-existing. Never let an unrelated red read as caused by the repair, and never
claim a repair fixed something it did not touch.

If verification cannot run at all, nothing is marked `resolved`.

### Phase 6 — Close & hand back

Write each finding's `resolution` block (`by`, `at`, `located_stage`, `mode`,
`artifacts_touched`, `downstream_rerun`, `stale_tasks`, `summary`), set the
queue's `last_updated`, and re-validate it with `validate_findings.py`.

Then compute the handback. There is no bespoke mechanism and there should not
be: editing a task artifact changes each affected task's `task_fingerprint`,
which `/sdlc:code` already classifies as `stale` and gates at its plan approval.

```bash
python "${CLAUDE_SKILL_DIR}/../code/topo_order.py" --scope <cid> --state .claude/skills-state/sdlc-code.state.yaml
```

Its `stale` section is the answer; record those ids in `resolution.stale_tasks`.
Close with the report:

```
── /sdlc:repair — what changed ────────────────────────────
Findings:  2 resolved · 1 triaged (awaiting re-invocation) · 1 wontfix
Located:   FND-001 → arch (suspected: task)  ·  FND-002 → api (suspected: test)
Edited:    docs/ARCH__demo-api.yaml, docs/TASKS__demo-api.json
Verified:  arch exit 0 · task exit 0 · crosscheck exit 0 · index exit 0
Next:      /sdlc:arch demo-api  then  /sdlc:test demo-api      (for FND-004)
           /sdlc:code demo-api        ← in a NEW session
           3 tasks are now stale and will be offered for regeneration.
```

Set the state file `status: complete`.

## Localization at a glance

Full rules: `references/back-propagation.md`. The one-line version of each:

| Finding kind | Usual source | The check that decides |
|---|---|---|
| `contract_underdetermined` | `arch` work_unit | …unless it `traces_api_operation` (→ `api`), or filling it in would require inventing behaviour (→ `prd`) |
| `test_contradicts_contract` | `arch`/`api` **or** `test` | trace both to PRD; whichever the FR/NFR/ACR supports is right. Supports neither → `prd` |
| `missing_requirement` | `prd` **or** the downstream stage | is the behaviour legitimate, or invented scope? Always the user's call |
| `missing_operation` / `missing_entity` | `api` / `data` | …unless the container should not reach for it at all (→ `arch`) |
| `drifted_embed` | upstream, or a stale slice | compare embed to source: same wrong thing → upstream; different → re-slice |
| `wrong_path`, `missing_dependency_edge`, `impossible_acceptance` | `task` | …unless the acceptance was copied from an unsatisfiable ACR (→ `prd`) |
| `validator_error` | the named artifact | …unless it is a coverage failure naming an upstream id |
| `crosscheck_broken_ref`, `dangling_reference` | whichever side is stale | `docs_index.py --refs`: many inbound refs + absent definer → the definer; one dangling ref → the referencer |

## Hard boundaries

- **Never writes source code** and never touches the generated tree. Code
  defects are `/sdlc:code`'s heal loop, not findings.
- **Never runs another skill.** `re-invoke` prints a command sequence.
- **Never edits `.claude/skills-state/sdlc-code.state.yaml`.** The `stale`
  handback works precisely because that ledger is left alone.
- **Never deletes an artifact item implicitly.** Deletion changes the downstream
  item set, so it is a `re-invoke` case requiring explicit approval that names
  what disappears and what references it.
- **Never marks a finding `resolved` without a resolution block** — the queue
  validator enforces this, and an unauditable resolution is worse than an open
  finding.

## Model policy

**opus / xhigh** (frontmatter), and deliberately so. This is the one skill whose
core operation is cross-artifact archaeology: holding eight artifacts' semantics
in view at once and deciding which of them is *actually* wrong. It is the
opposite regime from `/sdlc:code`'s manager (sonnet/high bookkeeping), which is
exactly why the two are separate skills rather than one — running this reasoning
inside the codegen manager would both mis-model the work and consume the very
context that codegen is trying to conserve.

## Quick reference: user inputs at gates

| Input | Effect |
|---|---|
| `EXIT` | Stop; state persisted as `aborted`, edits so far confirmed and named. |
| *fix as proposed* | Apply the localization and fix shown. |
| *fix differently* | Free text — your localization or fix overrides the proposal. |
| *defer* | Record a `WRN-NNN` in the source artifact; finding → `wontfix`. |
| *wontfix* | Close with the reason; no artifact is touched. |

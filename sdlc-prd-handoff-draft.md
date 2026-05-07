## Goal

Create a Claude skill named **`sdlc-prd`** that guides a user through defining a software product's requirements via a structured interview, produces a validated `PRD.yaml` file at the project root intended for downstream AI agent consumption, persists session state so interrupted interviews can be resumed, and injects a pointer into `CLAUDE.md` on completion.

---

## Skill Summary

When explicitly invoked, the skill:
1. Checks for an existing session state at `.claude/skills-state/sdlc-prd.state.yaml` and offers to resume if found.
2. Scans the project for existing context files and pre-fills what it can.
3. Presents pre-filled values to the user for confirmation, theme by theme.
4. Conducts a structured interview in thematic batches of 3–5 questions with multiple-choice answer suggestions.
5. Persists state after every confirmed batch.
6. After required themes, proactively suggests additional items.
7. Writes (or merges into) `PRD.yaml` at the project root.
8. Validates output via a bundled Pydantic v2 script (`validate_prd.py`).
9. Injects or updates a pointer block in `CLAUDE.md`.
10. Marks session state as `complete`.

---

## What the Skill Should Enable Claude to Do

- Recursively read all discoverable files in: project root, `docs/`, `orga/`, `meta/`, `project/`. Skip binaries. Prioritize: `README*`, `package.json`, `pyproject.toml`, `Makefile`, `*.config.*`, and any existing `PRD.yaml`.
- Extract and infer product-relevant signals: name, purpose, users, stack, constraints, existing decisions, open questions.
- Run a structured interview grouped into thematic batches (3–5 questions each), covering the full product requirements space as defined in the bundled `product-questions.yaml`.
- For each question, offer multiple-choice answers (3–5 options) plus a free-text fallback ("Other / type your own").
- Allow the user to answer an entire batch in one reply (e.g. "1a, 2b, 3 SaaS").
- After required themes, suggest lower-priority or inferred items the user may not have considered, and ask if they want to address them.
- Write or merge `PRD.yaml` at the project root.
- Run `validate_prd.py` and surface any errors before declaring completion.
- Inject a pointer block into `CLAUDE.md` (create the file if absent).

---

## When the Skill Should Trigger

This skill must **only trigger on explicit invocation**. It must never auto-trigger from natural-language context, product discussions, or planning conversations.

Explicit triggers:
- User runs `/sdlc-prd` as a slash command in Claude Code.
- User types a phrase that directly requests the PRD workflow, e.g.: "run sdlc-prd", "start the product requirements skill", "create my PRD".

The `description` field in SKILL.md must be written to be explicit and slightly pushy to avoid undertriggering, since the description is the primary activation mechanism. Suggested wording:

> "Explicitly invoked skill for creating or updating PRD.yaml. Trigger only when
> the user runs /sdlc-prd or directly requests the product requirements interview
> workflow. Do not trigger from general product discussion, requirements chat, or
> planning conversations."

---

## Slash-Command and Argument Behavior

- Slash command name: `/sdlc-prd`
- No arguments in v1 — always runs the full flow.
- `disable-model-invocation: true` should NOT be set, because the skill must also respond to natural-language explicit invocations.

Recommended SKILL.md frontmatter:

```yaml
name: sdlc-prd
description: >
  Explicitly invoked skill for creating or updating PRD.yaml for a software
  product. Trigger only when the user runs /sdlc-prd or directly asks to
  start the product requirements interview. Scans project files, interviews
  the user in thematic batches with multiple-choice answers, persists session
  state for resumability, then writes and validates PRD.yaml for downstream
  agent consumption.
```

---

## Session State: `.claude/skills-state/sdlc-prd.state.yaml`

The skill must persist session state so users can abort and resume long interviews.

State is written to `.claude/skills-state/sdlc-prd.state.yaml`. This path is inside `.claude/` (a tool-artifact directory), keeping the project root clean. The `skills-state/` subfolder is a logical home for runtime state produced by skills, separating it from `skills/` (definitions) and `rules/` (context files).

State file structure (skill-creator should define the full schema, guided by):

```yaml
session_id: <uuid>
skill_version: "1.0"
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted
pre_fill_confirmed: false
suggestion_phase_done: false
completed_themes: []
skipped_themes: []
pending_themes: []
current_theme: null
partial_answers: {}  # mirrors PRD.yaml structure, populated incrementally
```

Behavior:
- **On invocation**: check for state file. If `status: in_progress`, ask: *"Unfinished session found from [last_updated]. Resume, restart, or discard?"*
- **During interview**: write state after every confirmed batch — not just at end.
- **On completion**: set `status: complete`, keep file as audit trail (do not delete).
- **On user abort**: set `status: aborted`, write current `partial_answers` so nothing is lost.
- `validate_prd.py` must ignore the state file — it validates only `PRD.yaml`.

---

## Bundled Reference File: `product-questions.yaml`

The skill-creator must **research, design, and populate** this file with depth and genuine coverage. It is the core intellectual asset of the skill — not a thin placeholder. Invest real thought into question coverage.

Each entry should include:
- `theme`: grouping label (used to batch questions and track state)
- `id`: unique slug
- `question`: question text
- `hint`: why this matters for downstream agents
- `suggested_answers`: list of 3–5 plausible multiple-choice options
- `free_text_allowed`: true/false
- `required`: true/false

Themes to cover (skill-creator should expand beyond this list):
- Product identity: name, tagline, one-liner, vision, mission
- Problem & opportunity: problem statement, who has the pain, current workarounds
- Users & personas: primary/secondary users, goals, frustrations
- Use cases & user stories: core workflows, jobs-to-be-done
- Functional requirements: must-have features, nice-to-have, explicitly out-of-scope
- Non-functional requirements: performance, scalability, reliability, availability
- Technical constraints: stack, language, platform, existing integrations
- Data model hints: key entities, data ownership, storage preferences
- Security & compliance: auth model, data sensitivity, regulatory requirements
- Business model: monetization, pricing, licensing, open vs. proprietary
- Stakeholders & team: owner, contributors, decision-makers, external dependencies
- Timeline & milestones: MVP scope, phases, deadlines
- Success metrics: KPIs, acceptance criteria, definition of done
- Risks & assumptions: known unknowns, blockers, dependencies
- Open questions: what is still undecided

The skill uses this file as a **guide, not a rigid script**. Skip questions already answered by the file scan. Skip questions irrelevant to the detected project type.

---

## `PRD.yaml` Schema

The skill-creator must design a thoughtful YAML schema that:
- Is keyed and structured so downstream AI agents navigate it predictably.
- Uses consistent types: strings, lists, enums, booleans — no freeform prose blobs.
- Groups keys by theme (matching question themes above).
- Includes a metadata block:
  ```yaml
  prd_version: "1.0"
  last_updated: <iso8601>
  generated_by: sdlc-prd
  session_id: <uuid>
  ```
- Uses `null` for explicitly unanswered fields rather than omitting them, so agents know the gap exists.
- Includes a `prd_warnings` list at the top for required fields left null.
- Has inline YAML comments on each key explaining its purpose (human-readable without breaking agent parsing).

On re-run: **merge** — update changed keys, add new keys, never silently delete existing keys. If a key is being removed, ask the user to confirm.

---

## Pydantic Validation: `validate_prd.py`

A bundled Python script the skill calls after writing `PRD.yaml`.

Requirements:
- Uses **Pydantic v2** syntax.
- Mirrors the full PRD.yaml schema exactly.
- Required fields are non-optional; optional fields use `Optional[...]`.
- Uses `Enum` classes for fixed-value fields (e.g. `ProjectType`, `AuthModel`, `LicenseType`).
- Loads `PRD.yaml` from the project root, parses it, runs validation.
- Prints a clear **pass/fail summary** with field-level error messages on failure.
- The skill must call this script after every write and surface errors to the user before declaring the workflow complete.
- On validation failure: show field-level errors and offer to re-enter failing values interactively, then re-run validation.

---

## CLAUDE.md Pointer Injection

On successful completion, the skill must inject or update this block in `CLAUDE.md` (create `CLAUDE.md` at project root if absent):

```markdown
## Product Requirements
`PRD.yaml` in the project root contains the full structured product requirements. Load it when working on features, architecture, API design, or user-facing decisions. Last updated by `sdlc-prd` skill on [iso8601 timestamp].
```

If the block already exists, update the timestamp. Do not duplicate the block.

---

## Interview Flow

1. **Resume check**: Look for `.claude/skills-state/sdlc-prd.state.yaml`. If `status: in_progress`, offer resume/restart/discard.
2. **Scan phase**: Read project files. Build pre-fill map.
3. **Confirmation phase**: Show pre-filled values grouped by theme. One block per theme. User confirms, edits, or skips. Write state after each confirmed theme.
4. **Interview phase**: For unanswered required and high-value optional questions, proceed theme by theme. 3–5 questions per batch with multiple-choice options. User can answer a full batch in one reply. Write state after each batch.
5. **Suggestion phase**: Offer lower-priority or inferred items. Ask if the user wants to address them. Mark `suggestion_phase_done: true` in state.
6. **Write & validate phase**: Generate or merge `PRD.yaml`. Run `validate_prd.py`. Report result. If errors, offer interactive correction.
7. **Completion**: Inject CLAUDE.md pointer. Set state `status: complete`.

---

## Edge Cases and Boundaries

- **No project files found**: skip scan/confirmation phases, start interview cold.
- **`PRD.yaml` already exists**: inform user, show `last_updated`, offer update/abort.
- **Conflicting signals in scanned files**: surface conflict to user during confirmation phase — never guess.
- **User skips a required field**: write `null` in YAML, add to `prd_warnings`, report in validation summary.
- **Validation failure**: show field-level errors, offer interactive re-entry, re-run validation.
- **User aborts mid-interview**: write current state with `status: aborted`, confirm state was saved before exiting.
- **Very large projects**: sample and summarize rather than parsing everything — prioritize `README`, `package.json`, `pyproject.toml`, `Makefile`, `*.config.*`.

---

## Success Criteria

- `PRD.yaml` is written to project root with all required fields populated or explicitly `null`.
- File passes Pydantic validation with zero errors (or all nulls acknowledged).
- User completed core flow primarily via multiple-choice — minimal typing required.
- Downstream agents can parse `PRD.yaml` without ambiguity.
- On re-run, existing data is preserved unless explicitly changed.
- Session state is saved incrementally — no progress lost on abort.
- `CLAUDE.md` contains an up-to-date pointer to `PRD.yaml`.

---

## Test-Case Guidance

Test cases are strongly recommended (deterministic output, fixed schema):

1. **Empty project** — no files; full cold interview; valid `PRD.yaml` produced.
2. **Partial context** — README + `package.json` present; skill pre-fills name, stack, language correctly; only remaining gaps asked.
3. **Resume from state** — simulate abort mid-interview; re-invoke; skill resumes from correct theme with `partial_answers` intact.
4. **Existing PRD.yaml** — re-run merges new answers without overwriting old keys.
5. **Validation failure** — manually corrupt `PRD.yaml`; script reports clear field-level errors.
6. **Required field skipped** — `null` in output, entry in `prd_warnings`, reported in validation summary.
7. **CLAUDE.md injection** — file absent before run; pointer block present after; re-run updates timestamp without duplicating block.

---

## Files to Produce

All under `.claude/skills/sdlc-prd/`:
- `SKILL.md` — main skill instructions and full interview flow
- `product-questions.yaml` — bundled question inventory (skill-creator researches and populates with genuine depth)
- `validate_prd.py` — Pydantic v2 validation script for `PRD.yaml`
- `PRD.schema.yaml` — canonical schema reference (recommended)

Runtime files (not inside the skill directory):
- `PRD.yaml` — project root (output artifact)
- `.claude/skills-state/sdlc-prd.state.yaml` — session state
- `CLAUDE.md` — project root (pointer injected on completion)

## Not yet conceptualized (please guide me here)

### Multi-product / monorepo support
The spec assumes one PRD.yaml per project root. A monorepo with 3 packages needs either packages/auth/PRD.yaml or a namespaced single file. No guidance exists for this. Maybe a namespaced file?

### "Why" fields alongside "what" fields
The schema captures decisions but not rationale. Downstream agents making trade-off decisions benefit enormously from knowing why a choice was made (e.g. "chose PostgreSQL because team already knows it, not for technical reasons"). A rationale subfield per decision *might* be high value? Think about it

### Exit / partial-output command
Typing `EXIT` or `QUIT` should interrupt execution.

### Confidence / certainty flags
Requirements often have different levels of certainty. A `confidence: high | medium | low | assumption` field per item would help downstream agents weight decisions appropriately.

### Risk: Pre-fill hallucination
When scanning files, Claude may confidently infer things that aren't actually stated — e.g. reading a package.json and assuming the target platform is "web" when it's actually a CLI tool. A pre-filled answer the user skims and confirms without reading closely becomes a wrong requirement. Mitigation: pre-fills from inference (not explicit text) should be visually flagged as ⚠ inferred vs. ✓ found.

### State file as source of truth confusion
partial_answers in the state file and the final PRD.yaml can diverge if a merge goes wrong or a user manually edits PRD.yaml. No reconciliation logic is defined for when the two conflict.






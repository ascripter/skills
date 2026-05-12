---
name: prd
description: >
  INTERNAL — only loaded by sdlc:prd agent. Never invoke this skill implicitly.
  Create or update PRD.yaml for a software product. Scans project files,
  captures the user's idea in free text, asks the structural monorepo
  question, interviews the user in thematic batches with multiple-choice
  answers (via AskUserQuestion), persists session state for resumability,
  then writes and validates PRD.yaml for downstream agent consumption.
  ONLY stop when no open questions remain or the user types EXIT.
user-invocable: false
allowed-tools: Read Write(CLAUDE.md) Write(docs/PRD.yaml) Write(.claude/skills-state/sdlc-prd.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

> **Invocation note**: this skill is normally fronted by the
> `sdlc/agents/prd.md` agent so the long interview runs in
> its own context. The skill body below is the single source of truth for
> the workflow regardless of which path invokes it (agent or inline).

# sdlc-prd

Guides the user through a structured interview that produces a validated
`docs/PRD.yaml` at the project root, so downstream AI agents have a single
unambiguous source of product truth.

## What this skill does (at a glance)

1. **Resume check** → load existing state if any (otherwise scan from scratch).
2. **Scan + idea capture** → build pre-fill map and a free-text idea summary.
3. **Structural questions** → monorepo? products? (sets PRD shape.)
4. **Pre-fill confirmation** → theme by theme, each `⚠ inferred` confirmed individually.
5. **Theme interview** → required themes always run; optional themes are gated now/skip/todo. Per-question flow varies by `importance` tier (see `references/importance-flows.md`).
6. **Write + validate** → merge into `docs/PRD.yaml`, run `validate_prd.py`.
7. **CLAUDE.md pointer + close** → inject the pointer block, mark state `complete`.

State is persisted **after every confirmed batch**, so the user can `EXIT`
at any time without losing progress.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `product-questions.yaml` | The full question inventory, grouped by theme. |
| `PRD.schema.yaml` | Human-readable canonical schema for `docs/PRD.yaml`. |
| `validate_prd.py` | Pydantic v2 validator, called after every write. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, inferred-option pattern, conditional promotions. Read on entering Phase 6. |
| `references/importance-flows.md` | The `med` / `high` / `critical` interview flows, including the per-item state machine for critical lists and the `product_identity` synthesis batch. Read alongside `interview-mechanics.md` on entering Phase 6 — required whenever a question with `importance: high` or `critical` is up next. |
| `references/merge-validate.md` | Merge logic for existing PRD.yaml, validator exit-code recovery, CLAUDE.md pointer rules. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations and their handling. Read whenever the happy path doesn't fit. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/PRD.yaml` (project root) | Output artifact consumed by downstream agents. |
| `.claude/skills-state/sdlc-prd.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer block injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the free-text
field of any `AskUserQuestion` call to abort the interview. State is *always*
saved automatically after each confirmed batch, so progress is never lost —
`EXIT` simply marks the session `status: aborted` and stops.

There is no `SAVE` command — saving is implicit.

## The 8-phase flow

### Phase 1 — Resume check

Before doing anything else, check for `.claude/skills-state/sdlc-prd.state.yaml`:

- If it exists with `status: in_progress`, ask:
  > "I found an unfinished session from `<last_updated>`. Would you like to
  > **resume**, **restart** (discard previous answers), or **discard** (delete
  > state and exit)?"
- If `status: complete` or `status: aborted` and `docs/PRD.yaml` exists, treat
  this as an update flow — see Phase 7's *merge* behavior.
- If no state file, continue to Phase 2.

### Phase 2 — Scan

Recursively read discoverable files in (in priority order):

1. Project root: `README*`, `package.json`, `pyproject.toml`, `Cargo.toml`,
   `go.mod`, `Makefile`, `*.config.*`, any existing `docs/PRD.yaml`, any
   `BRD.yaml`, any `*idea*.md`, `*vision*.md`, `*pitch*.md`.
2. `docs/`, `doc/`, `project/` — read all readable text files.
3. Any additional config files at the root (`.env.example`, `tsconfig.json`,
   `next.config.*`, etc.).

Skip:

- Binary files, lockfiles (`package-lock.json`, `poetry.lock`,
  `Cargo.lock`), node_modules, venv directories, `.git/`.
- For *very large projects* (>500 readable files), sample the priority list
  only and explain to the user that you skipped the rest.

Build a pre-fill map. For each candidate field, classify the source as:

- **`✓ found`** — the value is a direct quote/value from a file. Record file
  path. Example: `package.json: "name": "acme-app"` → product_identity.name.
- **`⚠ inferred`** — derived from signals, not explicit. Example:
  `package.json` exists with `"react"` in deps → runtime_platform = web,
  primary_language = javascript. Record the reasoning in one sentence.

Anything you didn't pre-fill is unmarked and will be asked in the interview.

Also extract any **idea-like text** for Phase 3: README description, the
`description` field of `package.json`/`pyproject.toml`, the contents of
any `BRD.yaml`/`*idea*.md`/`*vision*.md`/`*pitch*.md`. Preserve verbatim
snippets and their source paths so Phase 3 can quote them back to the user.

### Phase 3 — Idea capture & summary

This phase exists because most invocations have very little to scan — often
just a typed slash-command and an idea in the user's head. Three branches:

**Branch A — `$ARGUMENTS` provided OR scan found idea-like content (or both):**

Concatenate everything available (args + extracted snippets) and produce a
2–10 sentence exhaustive summary of what's been said about the product.
Then prompt:

> "Here's what I understood about your idea so far:
>
> > _[2–10 sentence summary covering everything relevant the inputs imply
> > about the product]_
>
> Source(s): `$ARGUMENTS`, `README.md` line 3, `package.json: description`.
>
> Want to add or correct anything in free text before we start the structured
> interview? (Type your additions, or `ok` to proceed.)"

**Branch B — Nothing on disk, no `$ARGUMENTS`:**

> "I don't know anything about your idea yet. Please describe it briefly in
> free text — even a paragraph is enough. After that we'll start a structured
> interview to fill in the details."

After the user replies (or accepts with `ok`), run a small **idea-extraction
pass**: probabilistically pre-fill candidate fields (`product_identity.one_liner`,
`problem_opportunity.problem_statement`, `users_personas.primary_users`,
possibly `functional_requirements.must_have_features`) and mark every one
of them as `⚠ inferred`. These join the Phase 2 pre-fill map and are
governed by the Phase 5 hallucination guard.

**Persist** the user's free-text idea verbatim into:
- `state.idea_text` — for the agent to re-read during later phases.
- `product_identity.idea_text` — written to `docs/PRD.yaml` so downstream agents
  see the original brief.

### Phase 4 — Structural questions

These determine *the shape of the PRD*, not its content. They must be asked
before any theme batch, because every later batch needs to know whether to
write to `product_identity.name` or `products.<slug>.product_identity.name`.

Ask in order:

1. **Monorepo / multi-product mode?** (single | multi)
   - Pre-fill default: scan signals (`workspaces` in `package.json`,
     top-level `packages/` or `apps/` with >1 package manifest, multiple
     `pyproject.toml`).
   - If signals present → pre-fill `multi`, mark `⚠ inferred`, ask the user
     to confirm with explanation:
     > "I see monorepo signals: `<signals>`. Should the PRD use multi-product
     > mode (one PRD.yaml at root, each product namespaced under
     > `products: <slug>:`)?"
   - If no signals → ask cold; pre-fill `single` as the typed default but
     require explicit confirmation:
     > "Are you working on a single product, or several distinct products
     > in one repo (monorepo)? (Default: single.)"
2. **(only if multi)** Which product slugs? (free text list — kebab-case)
3. **(only if multi)** Should each product get its own theme answers, or
   are some themes shared at the root? (Default: each product gets its own
   for product_identity, problem_opportunity, users_personas, use_cases,
   functional_requirements; technical_constraints and downstream themes
   may be shared.)

Persist these to state under `monorepo:` and `products:` (already in the
state schema) before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme**. For each theme that has any
pre-filled values, render a block like this:

```
## Product Identity (pre-filled)

  ✓ name        : "acme-app"            [from package.json]
  ⚠ slug        : "acme-app"            [inferred from package name]
  ✓ one_liner   : "Acme is a tool for…" [from README.md line 3]
    tagline     : (not pre-filled — will ask in interview)

For each ⚠ inferred item, type **confirm** to accept, or correct it.
For ✓ found items, you can batch-accept by typing **ok** to take all of them.
```

**Critical rule**: `⚠ inferred` items must NOT be batch-accepted via
shortcuts like "ok" or "1a, 2b". Each one needs an explicit confirmation
or correction. This is the hallucination guard — pre-filled inferences are
where wrong requirements sneak in unnoticed.

Write the confirmed values into the state file. Set
`<field>_confidence: confirmed` for explicitly confirmed items,
`<field>_confidence: inferred` for accepted-as-is inferences.

### Phase 6 — Theme interview

Walk the themes in the order defined by `product-questions.yaml`. Use
`AskUserQuestion` as the canonical asking channel. For each theme:

- **Required themes** (`required: true` in the YAML): run the theme's
  questions until every required question is answered. Write state after
  every confirmed batch or mini-section.
- **Optional themes** (`required: false`): before asking any questions, offer
  a gate via `AskUserQuestion`:

  > "Theme: **\<name\>** — N questions. \<one-line description\>.
  > Address now, skip, or mark as todo?"

  - **now** → run the theme's questions as above.
  - **skip** → record under `skipped_themes` in state, move on.
  - **todo** → append `"TODO: address theme <name>"` to
    `open_questions.undecided_decisions`, move on.

Required questions can never be `todo`'d. They must be answered, set to
`null` (writing a note to `prd_warnings`), or the user must `EXIT`.

After all themes are addressed (answered/skipped/todo'd), set
`suggestion_phase_done: true` in state.

#### Within a theme: tiered question flow

Each question in `product-questions.yaml` carries an `importance` field
(`med | high | critical`) that controls how the agent runs it:

- **`med`** (the default — most questions): batch with up to 3 sibling
  `med` questions from the same theme into one `AskUserQuestion` call.
  `⚠ inferred` candidate at position 1. Current behavior.
- **`high`** (~12 questions, mostly required list[string] fields and
  foundational narratives): runs as its **own mini-section** — never
  batched with other questions. For scalars: agent drafts a full answer,
  shows it, user approves or iterates (max 3 rounds). For list[string]:
  per-item with one clarifying challenge round each.
- **`critical`** (currently only `must_have_features` and
  `nice_to_have_features`): full per-item state machine — propose →
  optionally challenge → detail → optionally clarify → final approval →
  next item. Every item is examined before being added.

Order within a theme: run all `med` questions first (in 2–4-question
batches), then each `high`/`critical` question as its own mini-section
in the order they appear in `product-questions.yaml`.

**Read `references/importance-flows.md` before running any
`high`/`critical` question.** It contains the exact `AskUserQuestion`
prompts, iteration caps, EXIT-mid-flow rules, and the
`product_identity` synthesis batch example.

For batch format details (option layout, free-text-only questions,
`capture_rationale` follow-ups, `required_if` conditional-promotion
table) → see `references/interview-mechanics.md`.

The two non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended option**
   in their `AskUserQuestion` call. They cannot be silently accepted — the
   user must explicitly pick or correct. This is the hallucination guard.
2. State is written after **every confirmed batch or mini-section**, not
   at theme boundaries.

### Phase 7 — Write & validate

Write or merge `docs/PRD.yaml` at the project root, then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_prd.py" --path PRD.yaml
```

For full merge logic (conflict handling, key preservation, deletion
confirmation), type discipline when writing list-typed fields, and the
exit-code recovery flow → see `references/merge-validate.md`.

When writing the file: inline YAML comments on top-level keys, updated
`metadata.last_updated` and `metadata.session_id`.

Set `metadata.status`:
- `"complete"` — only when all required fields are filled and the validator
  passes with `[OK]`.
- `"draft"` — on early EXIT or when any required field is still null.

If the validator returns `[FAIL]` because required fields are missing despite
`status: complete`, ask the user via `AskUserQuestion` to either fill them
in now or accept `status: draft`.

### Phase 8 — CLAUDE.md pointer & complete

On successful validation (`[OK]` or `[DRAFT]`), inject (or update) the
`## Product Requirements` pointer block in the project root `CLAUDE.md`.
Create the file with the block alone if missing.

For block content, detection rule, and append behavior → see
`references/merge-validate.md`.

After the CLAUDE.md write succeeds: set `status: complete` in the state
file (do not delete it — it's an audit trail), and tell the user where
the artifacts live.

## Session state file

Path: `.claude/skills-state/sdlc-prd.state.yaml`

Schema:

```yaml
session_id: <uuid4 string>
skill_version: "1.1"
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted
monorepo: false      # mirrors PRD metadata
products: []         # populated only when monorepo: true; list of product slugs
idea_text: null      # user's free-text idea description (Phase 3)
pre_fill_confirmed: false
suggestion_phase_done: false
completed_themes: []
skipped_themes: []
todo_themes: []      # themes the user marked `todo` in Phase 6
pending_themes: []
current_theme: null
partial_answers: {}  # mirrors PRD.yaml structure incrementally
```

Rules:

- Generate `session_id` as a UUID4 on first creation.
- Update `last_updated` on every write.
- Write the file **after every confirmed batch**, including pre-fill
  confirmations and the Phase 3 idea-text capture.
- On user `EXIT`: set `status: aborted`, write current `partial_answers`,
  confirm to user that state was saved, then stop.
- On Phase 8 completion: set `status: complete` but keep the file.
- The validator ignores this file — it validates only `docs/PRD.yaml`.

**Source of truth on resume:**

- `docs/PRD.yaml` (if present) is the on-disk source of truth for *answers*.
- The state file is the source of truth for *interview progress*.
- On resume: load `docs/PRD.yaml` first as the baseline, then layer the state's
  `partial_answers` on top.
- If they conflict on the same key, ask the user which to keep — never
  silently overwrite. (See Phase 7.)

## Edge cases

For unusual situations (no files found, existing PRD without state, conflicting
scan signals, skipped required fields, validation failures, mid-interview
abort, very large projects, write-permission errors, skipped Phase 3 idea
capture, monorepo-mode change mid-flow, hallucination-guard violation
attempts) → see `references/edge-cases.md`.

## Style of conversation

The interview is potentially long. Keep it humane:

- Use the user's terminology as soon as they introduce it.
- Keep AskUserQuestion batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme boundary ("That's problem & opportunity
  done — next: users & personas, 5 questions.").
- Always make multiple-choice the path of least resistance.
- For the product_identity batch (Phase 6 finale), explicitly call out that
  candidates were synthesized from prior answers — don't pretend they came
  from nowhere.
- After all themes are done, congratulate the user briefly and move to write/validate.
  Do not repeat the entire summary back at them.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 summary as-is. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs it to `open_questions.undecided_decisions`. |

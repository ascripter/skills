---
name: data
description: >
  Launch in empty context. Create or update DATA-MODEL.yaml for a software
  product. Reads docs/PRD.yaml and any docs/UX*.yaml as upstream inputs,
  scans pre-fill candidates, asks the structural monorepo/bounded-contexts
  questions, runs a resume-aware thematic interview (with a per-entity
  drill-down for the critical `entities` theme), persists session state for
  resumability, then writes and validates docs/DATA-MODEL.yaml for downstream
  agent consumption (api, arch, test). Trigger only on /sdlc:data or a direct
  natural-language request for the data model — do not auto-trigger from
  generic chat. ONLY stop when no open questions remain or the user types EXIT.
user-invocable: true
disable-model-invocation: true
model: opus
effort: high
allowed-tools: Read Write(CLAUDE.md) Write(docs/DATA-MODEL.yaml) Write(.claude/skills-state/sdlc-data.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-data

Guides the user through a structured interview that produces a validated
`docs/DATA-MODEL.yaml` at the project root, so downstream AI agents (api,
arch, test, deploy) have a single unambiguous source of persistent-data
truth.

## What this skill does (at a glance)

1. **Resume check** → load existing state if any (otherwise scan from scratch).
2. **Scan inputs** → read `docs/PRD.yaml` (required) and every `docs/UX*.yaml`
   (required); build pre-fill map.
3. **Structural questions** → monorepo (inherited from PRD)? bounded contexts?
   polyglot persistence?
4. **Pre-fill confirmation** → theme by theme, each `⚠ inferred` confirmed
   individually (hallucination guard).
5. **Theme interview** → required themes always run; optional themes are
   gated now/skip/todo. Importance tiers (`med | high | critical`) control
   batching. The `entities` theme is the lone `critical` — full per-entity
   drill-down.
6. **Write + validate** → merge into `docs/DATA-MODEL.yaml`, run
   `validate_schema.py` (Pydantic + 6 cross-checks).
7. **CLAUDE.md pointer + close** → inject the pointer block, mark state
   `complete`.

State is persisted **after every confirmed batch and after every per-entity
drill-down step**, so the user can `EXIT` at any time without losing
progress, even mid-entity.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `data-questions.yaml` | The full question inventory, grouped by theme. |
| `DATA-MODEL.schema.yaml` | Human-readable canonical schema for `docs/DATA-MODEL.yaml`. |
| `validate_schema.py` | Pydantic v2 validator + cross-checks, called after every write. |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector, called in Phase 8. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, EXIT semantics, importance-tier flows. Read on entering Phase 6. |
| `references/entity-discovery.md` | Heuristics for deriving entity candidates from PRD features + UX surfaces. Read in Phase 3. |
| `references/pre-fill-sources.md` | Explicit PRD/UX-field → DATA-MODEL-field map. Read in Phase 3 + Phase 5. |
| `references/polyglot-persistence.md` | Guidance for multi-store designs. Read when the user opts into polyglot in Phase 4. |
| `references/merge-validate.md` | Merge logic for existing DATA-MODEL.yaml, validator recovery, CLAUDE.md pointer rules. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations (entity rename, mode switches, mass import, missing upstreams). Read whenever the happy path doesn't fit. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/DATA-MODEL.yaml` (project root) | Output artifact consumed by downstream agents. |
| `.claude/skills-state/sdlc-data.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer block injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the
free-text field of any `AskUserQuestion` call to abort the interview. State
is *always* saved automatically after each confirmed batch — `EXIT` simply
marks the session `status: aborted` and stops.

There is no `SAVE` command — saving is implicit.

## The 8-phase flow

### Phase 1 — Resume check

Before doing anything else, check for `.claude/skills-state/sdlc-data.state.yaml`:

- If it exists with `status: in_progress`, ask:
  > "I found an unfinished `sdlc:data` session from `<last_updated>`. Would
  > you like to **resume**, **restart** (discard previous answers), or
  > **discard** (delete state and exit)?"
- If `status: complete` or `status: aborted` and `docs/DATA-MODEL.yaml`
  exists, treat this as an update flow — see Phase 7's *merge* behavior.
- If no state file, continue to Phase 2.

### Phase 2 — Scan inputs

Required upstream artifacts:

1. **`docs/PRD.yaml`** — fail fast and inform the user if missing. Suggest
   running `/sdlc:prd` first.
2. **`docs/UX.yaml`** — strongly recommended (used for surface coverage and
   entity-field discovery). If missing, warn the user; offer to continue
   without UX context but note that downstream `api` will have weaker
   surface-coverage.
3. **`docs/UX__*.yaml`** — every sibling file is read for `validation_rules`,
   `components.content_slots`, and `interactions.effects`, which seed
   entity-field candidates.

Also scan:

- Existing `docs/DATA-MODEL.yaml` (for merge flow).
- Schema-like files in `db/`, `migrations/`, `prisma/`, `schema.prisma`,
  `*.sql`, `models/`, `entities/` — extract entity names verbatim where
  obvious (mark as `✓ found`).
- Lockfiles, binaries, and node_modules/venv directories — skip.

Build the pre-fill map (see `references/pre-fill-sources.md` for the full
mapping table). Tag each candidate:

- **`✓ found`** — value is a direct quote/value from a file (e.g.
  `PRD.security_compliance.encryption_at_rest: true` → `data_classification.encrypted_at_rest_default: true`).
- **`⚠ inferred`** — derived from signals (e.g. `PRD.data_model.key_entities: [User]` →
  candidate entity name `User`, but no fields yet).

If both PRD and DATA-MODEL.yaml exist and `PRD.metadata.session_id` doesn't
match what's recorded in `DATA-MODEL.metadata`, flag a possible stale-PRD
warning to `data_warnings`.

### Phase 3 — Entity-candidate discovery

This is the most novel and most hallucination-prone phase. The skill
proposes a **draft entity list** before any deep interview begins, so the
user can correct course early. Sources of candidates, in priority order:

1. **`PRD.data_model.key_entities`** — direct names (PascalCase'd if not
   already). Tag `✓ found`.
2. **`PRD.functional_requirements.must_have_features`** — extract the
   nouns from each F-NNN feature using lightweight heuristics (see
   `references/entity-discovery.md`). Tag `⚠ inferred`.
3. **`UX__<surface>.yaml.layout` + `validation_rules` + `components.content_slots`** —
   forms imply entities; list items imply entities; filters imply entities.
   Tag `⚠ inferred`.
4. **Schema files on disk** (Prisma, SQL, `models/`) — if present, those
   names are authoritative. Tag `✓ found`.

Present the draft to the user:

> "Based on PRD + UX, I see these entity candidates:
>
>   ✓ User           (from PRD.data_model.key_entities)
>   ✓ Project        (from PRD.data_model.key_entities)
>   ⚠ Task           (inferred from F-001 'Add a task in under 3 seconds')
>   ⚠ Tag            (inferred from UX__dashboard form field 'tags')
>
> Add, remove, or rename anything before we go deep on each one?"

Persist the confirmed list to `state.defined_entities`. **Critical rule**:
each `⚠ inferred` candidate must be confirmed individually — no batch-accept
shortcuts.

### Phase 4 — Structural questions

These determine *the shape of DATA-MODEL.yaml*, not its content.

Ask in order:

1. **Monorepo mode** — inherited from `PRD.metadata.monorepo`. Show as
   pre-filled and ask the user to confirm only if PRD signals conflict
   (rare).
2. **Bounded contexts** — opt-in. Ask:
   > "Do you want to group entities under DDD-style bounded contexts (e.g.
   > `auth: { entities: [...] }`, `billing: { entities: [...] }`)? Default:
   > no — keep `entities` as a flat dict."
   If the user opts in, ask for context names and assign each confirmed
   entity to exactly one context. Persist `state.bounded_contexts_enabled`
   and the assignment map.
3. **Polyglot persistence** — pre-fill from `PRD.data_model.storage_preferences`.
   If multiple stores are listed, default to `polyglot: true` and ask the
   user to confirm. See `references/polyglot-persistence.md` for the
   secondary-store interview script.

Persist all structural answers to state before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme** (skipping `entities` — that
gets its own treatment in Phase 6). Render each themed block as:

```
## Persistence (pre-filled)

  ✓ primary_store          : postgres                 [from PRD.data_model.storage_preferences]
  ⚠ polyglot               : true                     [inferred from secondary store: redis]
    secondary_stores       : (not pre-filled — will ask)
  ⚠ file_blob_store        : s3                       [inferred from regulatory_requirements: gdpr → audit log retention]

For each ⚠ inferred item, type **confirm** to accept, or correct it.
For ✓ found items, you can batch-accept by typing **ok**.
```

**Critical rule** (hallucination guard): `⚠ inferred` items must NOT be
batch-accepted via "ok" or "1a, 2b". Each one needs an explicit
confirmation or correction. Pre-filled inferences are where wrong
requirements sneak in unnoticed.

Write the confirmed values into the state file. Set
`<field>_confidence: confirmed` for explicitly confirmed items,
`<field>_confidence: inferred` for accepted-as-is inferences.

### Phase 6 — Theme interview

Walk the themes in the order defined by `data-questions.yaml`. Use
`AskUserQuestion` as the canonical asking channel.

#### Required vs optional themes

- **Required themes** (`required: true`): run the theme's questions until
  every required question is answered.
- **Optional themes** (`required: false`): before asking any questions,
  offer a gate:
  > "Theme: **\<name\>** — N questions. \<one-line description\>.
  > Address now, skip, or mark as todo?"
  - **now** → run the theme's questions.
  - **skip** → record under `skipped_themes` in state, move on.
  - **todo** → append `"TODO: address theme <name>"` to
    `data_warnings`, move on.

#### Conditional promotion

If `PRD.data_model.data_volume_estimate ∈ {terabytes, petabytes}`, the
`scale_and_retention` theme is promoted to required regardless of its
default. The agent re-evaluates promotion rules at every theme boundary.

#### Tiered question flow (within a theme)

Each question in `data-questions.yaml` carries an `importance` field
(`med | high | critical`) that controls how the agent runs it:

- **`med`** (default): batch with up to 3 sibling `med` questions from the
  same theme into one `AskUserQuestion` call. `⚠ inferred` candidate at
  position 1.
- **`high`**: runs as its **own mini-section** — never batched. For
  scalars: agent drafts a full answer, shows it, user approves or iterates
  (max 3 rounds). For list[string] fields: per-item with one clarifying
  challenge round each.
- **`critical`** (only `entities`): full per-entity state machine — propose
  → challenge → fields → relationships → indexes → traces → final approval
  → next entity. Each entity is examined before being added. The
  per-entity questions use a `entity.<field>` prefix on `schema_path` that
  the agent rewrites per entity (e.g. `entity.fields` →
  `entities.User.fields` when drilling User).

Order within a theme: run all `med` questions first (in 2–4-question
batches), then each `high`/`critical` question as its own mini-section in
the order they appear in `data-questions.yaml`.

**Read `references/interview-mechanics.md` before running any
`high`/`critical` question** for the exact AskUserQuestion prompts,
iteration caps, EXIT-mid-flow rules, and the per-entity state machine.

The two non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended option**
   in their `AskUserQuestion` call. They cannot be silently accepted — the
   user must explicitly pick or correct. This is the hallucination guard.
2. State is written after **every confirmed batch, mini-section, or
   per-entity step** — not at theme boundaries.

### Phase 7 — Write & validate

Write or merge `docs/DATA-MODEL.yaml` at the project root, then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/DATA-MODEL.yaml
```

For full merge logic (conflict handling, entity renames, field removal,
deletion confirmation), type discipline when writing nested entity blocks,
and the exit-code recovery flow → see `references/merge-validate.md`.

When writing the file: inline YAML comments on top-level keys, updated
`metadata.last_updated` and `metadata.session_id`.

Set `metadata.status`:

- `"complete"` — only when all required fields are filled and the validator
  passes with `[OK]`.
- `"draft"` — on early EXIT or when any required field is still null, or
  when a cross-check (feature coverage, relationship integrity,
  classification integrity) reports problems.

If the validator returns `[FAIL]` because required fields are missing
despite `status: complete`, ask the user via `AskUserQuestion` to either
fill them in now or accept `status: draft`.

### Phase 8 — CLAUDE.md pointer & close

On successful validation (`[OK]` or `[DRAFT]`), call
`set_claude_md_pointer.py` to inject or update this skill's bullet inside
the shared `## SDLC Documents` section of the project root `CLAUDE.md`.
Create `CLAUDE.md` with the section if missing.

For the bullet format, detection rule, and append behavior → see
`references/merge-validate.md`.

After the CLAUDE.md write succeeds: set `status: complete` in the state
file (do not delete it — it's an audit trail), and tell the user where the
artifacts live.

## Session state file

Path: `.claude/skills-state/sdlc-data.state.yaml`

Schema:

```yaml
session_id: <uuid4 string>
skill_version: "1.0"
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted
monorepo: false      # mirrors DATA-MODEL metadata; inherited from PRD
products: []         # populated only when monorepo: true; list of product slugs
bounded_contexts_enabled: false
bounded_contexts_map: {}     # entity_name → context_name (when enabled)
polyglot_persistence: false
pre_fill_confirmed: false
completed_themes: []
skipped_themes: []
todo_themes: []
pending_themes: []
current_theme: null
current_entity: null         # which entity is mid-deepdive in theme 3
defined_entities: []         # list of {name, status: proposed|draft|confirmed|dropped, source}
dropped_entity_candidates: []  # so we don't re-propose ones the user rejected
partial_answers: {}          # mirrors DATA-MODEL.yaml structure incrementally
```

Rules:

- Generate `session_id` as a UUID4 on first creation.
- Update `last_updated` on every write.
- Write the file **after every confirmed batch, mini-section, and per-entity
  step**, including pre-fill confirmations and Phase 3 entity-list
  confirmation.
- On user `EXIT`: set `status: aborted`, write current `partial_answers`,
  confirm to user that state was saved, then stop.
- On Phase 8 completion: set `status: complete` but keep the file.
- The validator ignores this file — it validates only `docs/DATA-MODEL.yaml`.

**Source of truth on resume:**

- `docs/DATA-MODEL.yaml` (if present) is the on-disk source of truth for
  *answers*.
- The state file is the source of truth for *interview progress*.
- On resume: load `docs/DATA-MODEL.yaml` first as the baseline, then layer
  the state's `partial_answers` on top.
- If they conflict on the same key, ask the user which to keep — never
  silently overwrite.

## Edge cases

For unusual situations (missing PRD, missing UX, existing DATA-MODEL.yaml
without state file, conflicting scan signals, entity rename mid-flow,
relationship integrity failures, mass entity import from schema files,
mid-interview abort, very large projects, write-permission errors,
hallucination-guard violation attempts) → see `references/edge-cases.md`.

## Style of conversation

The interview is potentially long, especially the per-entity drill-down.
Keep it humane:

- Use the user's terminology as soon as they introduce it.
- Keep AskUserQuestion batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme boundary and at each entity boundary
  ("That's User done — 5 fields, 2 relationships, 3 indexes. Next: Task,
  which I've drafted as 4 fields. Review and add?").
- Always make multiple-choice the path of least resistance.
- After all themes are done, congratulate the user briefly and move to
  write/validate. Do not repeat the entire summary back at them.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 entity list as-is. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs it to `data_warnings`. |

## Project Overview

A repo containing a collection of skills bundled as a Claude Code plugin (`sdlc`).
The skillset is an **SDLC factory**: each skill produces a machine-readable spec
that the next skill consumes, so downstream AI agents can scaffold a software
project from a structured chain of artifacts. Skills are invoked as
`/sdlc:<skill>` and run in order:

| Skill        | Folder              | Inputs                                                                                       | Output(s)                                            |
|--------------|---------------------|----------------------------------------------------------------------------------------------|------------------------------------------------------|
| `prd`        | `sdlc/skills/prd`   | repo scan + ideation + interview                                                             | `docs/PRD.yaml`                                      |
| `ux`         | `sdlc/skills/ux`    | `docs/PRD.yaml` + interview                                                                  | `docs/UX.yaml`, `docs/UX__<surface>.yaml`            |
| `api`        | `sdlc/skills/api`   | `docs/PRD.yaml` + `docs/UX.yaml` + interview                                                 | `docs/API.yaml`                                      |
| `data`       | `sdlc/skills/data`  | `docs/PRD.yaml` + `docs/UX.yaml` + `docs/API.yaml` + interview                               | `docs/DATA-MODEL.yaml`                               |
| `arch`       | `sdlc/skills/arch`  | PRD + UX + API + DATA-MODEL + interview                                                      | `docs/ARCH.yaml`, `docs/ARCH__<component>.yaml`      |
| `test`       | `sdlc/skills/test`  | PRD + API + DATA-MODEL + ARCH__<component> + interview                                       | `docs/TEST-STRATEGY__<component>.yaml`               |
| `task`       | `sdlc/skills/task`  | API + DATA-MODEL + ARCH__<component> + TEST-STRATEGY                                         | `docs/TASKS__<component>.json`                       |
| `deploy`     | `sdlc/skills/deploy` | `docs/ARCH.yaml` + interview                                                                | `docs/DEPLOY.yaml`                                   |

**Downstream consumers of every output are AI agents, not humans.** Optimize
artifacts for unambiguous machine consumption (typed enums, no prose blobs,
explicit `null` for unanswered fields).

## Canonical naming

Use these forms consistently across all skills:

| Concept                                          | Form                                          | Example                                  |
|--------------------------------------------------|-----------------------------------------------|------------------------------------------|
| Skill folder + frontmatter `name`                | kebab-case (lowercase, hyphens, ≤64 chars)    | `prd`, `ux`, `arch`                      |
| Plugin invocation                                | `/<plugin>:<skill>`                           | `/sdlc:prd`, `/sdlc:ux`                  |
| State file path                                  | `.claude/skills-state/sdlc-<skill>.state.yaml`| `.claude/skills-state/sdlc-prd.state.yaml`|
| `generated_by` tag in output                     | `sdlc-<skill>`                                | `sdlc-prd`                               |
| Question inventory file (in skill folder)        | `<skill>-questions.yaml`                      | `prd-questions.yaml`, `ux-questions.yaml`|
| Output spec file (in `docs/`)                    | UPPERCASE (with `-` for compounds)            | `PRD.yaml`, `DATA-MODEL.yaml`            |
| Output sub-artifact (per surface/component)      | `<NAME>__<slug>.yaml`, slug in kebab-case     | `UX__login-flow.yaml`, `ARCH__auth.yaml` |
| Schema reference file (in skill folder)          | `<UPPERCASE-OUTPUT-NAME>.schema.yaml`         | `PRD.schema.yaml`, `UX.schema.yaml`      |
| Bundled Python helpers                           | snake_case `.py`                              | `validate_schema.py`, `set_claude_md_pointer.py` |

Slugs inside `__<slug>` segments are always kebab-case.

## Designing a new skill

When asked to design a new SDLC skill, read **only the upstream skills it
depends on** (per the table above) plus their assets (`references/`,
`<skill>-questions.yaml`, `<NAME>.schema.yaml`). Do not read other unrelated
skills.

Every SDLC skill follows the same architecture: read inputs → resume-aware
interview → write & validate output → inject CLAUDE.md pointer → mark state
complete. The sections below define the contract.

### Frontmatter (required fields)

```yaml
---
name: <skill>                    # kebab-case
description: >
  One-line explicit-invocation summary. Trigger only on /sdlc:<skill> or a
  direct natural-language request. Do not auto-trigger from generic chat.
user-invocable: true
disable-model-invocation: true   # always — these skills are deliberate, not ambient
model: opus                      # opus | sonnet | opusplan ; sonnet only when the
                                 # logic is genuinely simple and shallow-reasoning
effort: <low|medium|high|xhigh|max>
allowed-tools: Read Write(CLAUDE.md) Write(docs/<OUTPUT>.yaml) Write(.claude/skills-state/sdlc-<skill>.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---
```

`allowed-tools` is **space-separated** (per Anthropic skill docs) or a YAML
list. Never comma-separated.

### Skill directory layout

```
sdlc/skills/<skill>/
├── SKILL.md                     # required — workflow + phase outlines
├── <skill>-questions.yaml       # interview inventory (themes + questions)
├── <UPPERCASE-OUTPUT>.schema.yaml  # human-readable canonical schema
├── validate_schema.py           # Pydantic v2 validator
├── set_claude_md_pointer.py     # CLAUDE.md pointer injector
└── references/                  # on-demand reference material
    ├── interview-mechanics.md
    ├── merge-validate.md
    ├── edge-cases.md
    └── …
```

**`references/` folder** is mandatory for non-trivial skills. SKILL.md stays
under ~500 lines and points into `references/<topic>.md` for detailed rules.
Reference files are loaded only when the phase that needs them is entered.
This keeps the entry-point lean and the loaded context proportional to the
work in progress.

### Interview contract

A skill that has `interview` in its inputs runs an interactive interview via
`AskUserQuestion` driven by `<skill>-questions.yaml`.

`<skill>-questions.yaml` has **two top-level keys**:

```yaml
themes:
  - id: <theme_id>                # snake_case, matches a key in the output schema
    title: <Human Title>          # for messages to user
    required: true|false          # if false, the agent asks a now/skip/todo gate
    description: <one-liner>      # what this theme is about

questions:
  - theme: <theme_id>
    id: <question-id>             # kebab-case, unique
    schema_path: <dotted.path>    # where the answer is written in the output yaml
    question: <prompt shown to user>
    hint: <short note for the agent — why this matters downstream>
    suggested_answers: [<≤4 plausible options>]
    free_text_allowed: true|false # false ⇒ only one of suggested_answers is valid
    required: true|false          # inherited from themes[].required by default
    importance: med|high|critical # see "Importance tiers" below (default: med)
```

Interview style:

- Batch 2–4 questions per `AskUserQuestion` call (the tool's hard limit is 4).
- Recommended answer first; auto-added "Other" lets the user type free text.
- Show a completeness summary at every theme boundary; advance only after
  user confirms.
- Challenge vague answers ("clean and simple") for concrete examples or
  references — but always make sensible proposals.

#### Reserved EXIT command (mandatory)

In any `AskUserQuestion` "Other" free-text field the user may type `EXIT`
(case-insensitive). On detection: persist current state with
`status: aborted`, confirm save to the user, stop.

There is no SAVE command — saving is implicit after every confirmed batch.

#### Importance tiers (recommended)

Question entries may set `importance: med | high | critical` to control
how they are run:

- **`med`** (default) — batched 2–4 per `AskUserQuestion` call.
- **`high`** — own mini-section. Agent drafts an answer, user approves
  or iterates (cap iterations, e.g. 3).
- **`critical`** — full per-item drill-down (propose → challenge →
  detail → final approval → next item).

Reserve `critical` for scope-defining fields (e.g. MVP features in `prd`).

#### Confidence / rationale sibling fields (recommended)

For fields where downstream agents benefit from knowing certainty or the
"why" behind a choice, write sibling fields in the output:

- `<field>_confidence`: `confirmed | inferred | assumption`
- `<field>_rationale`: short string explaining the trade-off

The schema file documents which sibling pairs exist.

### Schema validation contract

Each skill defines its output schema **twice**, kept in lockstep:

1. `<UPPERCASE-OUTPUT>.schema.yaml` — human/agent-readable, with inline comments.
2. `validate_schema.py` — Pydantic v2 model that enforces it.

`validate_schema.py` requirements:

- Required fields are non-optional; optional fields use `Optional[...]`.
- Fixed-value fields use `Enum` classes.
- Loads the skill's output YAML (default path is its canonical location;
  CLI flag `--path` overrides), parses, validates.
- Prints a clear **pass/fail summary** with field-level error messages.
- The skill **must** call this script after every write and surface errors
  before declaring the workflow complete.
- On validation failure: show field-level errors, offer interactive
  re-entry via `AskUserQuestion`, re-run validation.

**Exit codes** (include verbatim in module docstring):

```
0 — schema valid; either status='complete' with all required fields filled,
    or status='draft' (with or without missing required fields).
1 — schema invalid (pydantic error), OR status='complete' but required
    fields are missing.
2 — could not read or parse the file (missing, bad YAML, etc.)
3 — required dependency missing (pydantic v2 or pyyaml).
```

### Output `metadata.status` contract

Every output YAML carries a `metadata` block with at least:

```yaml
metadata:
  <name>_version: "1.0"
  last_updated: <ISO-8601 UTC>
  generated_by: sdlc-<skill>
  session_id: <uuid4>
  status: "draft" | "complete"
```

- `status: complete` — set **only** when all required fields are filled
  and validation exits 0.
- `status: draft` — set on early EXIT or whenever any required field is null.

**Downstream-agent rejection rule**: downstream skills/agents MUST reject
an input artifact if `metadata.status != "complete"` OR if its
`validate_schema.py` exits non-zero. Document this rule in the skill's
`references/merge-validate.md`.

### State file contract

Path: `.claude/skills-state/sdlc-<skill>.state.yaml`

Baseline schema (skills may add skill-specific keys):

```yaml
session_id: <uuid4>
skill_version: <semver>
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted
completed_themes: []
skipped_themes: []   # themes the user gated as "skip"
todo_themes: []      # themes the user gated as "todo"
pending_themes: []
current_theme: null
partial_answers: {}  # mirrors the output yaml structure, populated incrementally
```

Behavior:

- **On invocation**: check for the state file.
  - If `status: in_progress` → ask:
    *"Unfinished session found from `<last_updated>`. Resume, restart, or
    discard?"*
  - If `status: aborted` or `status: complete` and the output yaml exists,
    treat as an update flow (merge into existing output; see below).
- **During interview**: write state after every confirmed batch — not at
  theme boundaries, not at the end.
- **On EXIT**: set `status: aborted`, persist `partial_answers`, confirm to
  user, stop.
- **On completion**: set `status: complete`, keep the file as audit trail
  (do not delete).
- `validate_schema.py` ignores the state file — it validates only the
  output yaml.

**Source-of-truth on resume**: the output yaml is authoritative for
*answers* (it may have been edited manually); the state file is
authoritative for *interview progress*. If the two conflict on the same
key, surface the conflict to the user — never silently overwrite.

### Workflow phases (canonical 8-phase flow)

Every skill implements these phases, in order:

1. **Resume check** — load state if present, offer resume/restart/discard.
2. **Scan inputs** — read all dependency artifacts and ad-hoc context.
   Exit early with a clear warning if a required input is missing or
   corrupted (e.g. PRD.yaml absent for sdlc:ux).
3. **Pre-fill** — build a map of values that can be derived from inputs.
   Mark each as `✓ found` (direct quote) or `⚠ inferred` (derived).
   *Recommended:* `⚠ inferred` items must never be batch-accepted; each
   needs explicit user confirmation in Phase 4 or 5 (hallucination guard).
4. **Structural questions** — questions that determine the *shape* of the
   output (e.g. monorepo? CLI vs GUI?). Asked before any theme batch.
5. **Pre-fill confirmation** — theme by theme, present pre-filled values
   for confirmation.
6. **Theme interview** — walk `<skill>-questions.yaml`. Required themes
   run unconditionally; optional themes get a now/skip/todo gate.
   Persist state after every confirmed batch.
7. **Write & validate** — write or merge `docs/<OUTPUT>.yaml`, run
   `validate_schema.py`. On validation failure, show field-level errors
   and offer interactive re-entry, then re-validate.
8. **CLAUDE.md pointer + close** — call `set_claude_md_pointer.py`, set
   state `status: complete`.

### Merge behavior (Phase 7)

If `docs/<OUTPUT>.yaml` already exists:

- Load as baseline.
- Overwrite keys only where the user changed the value in this session.
- Add new keys.
- For keys the session would remove (rare), ask the user to confirm
  before deleting.
- Surface conflicts (user-edited yaml vs. state file) — never auto-resolve.
- Preserve unrelated keys you don't recognize.

### CLAUDE.md pointer contract

There is **one shared `## SDLC Documents` section** in the project root
`CLAUDE.md`. Each skill appends or updates one bullet pointing to its
artifact(s). Bullet format:

```
- `docs/<OUTPUT>.yaml`: <short purpose>. Load when working on <topics>. Last updated by `sdlc-<skill>` on <ISO-8601 timestamp>.
```

Rules:

- If the section doesn't exist → create it.
- If a bullet whose substring matches `` `docs/<OUTPUT>.yaml` `` and
  `sdlc-<skill>` already exists → update the timestamp only; do not
  duplicate.
- Append new bullets at the section's end.
- Never reorder or modify the user's existing CLAUDE.md content.

Each skill ships its own `set_claude_md_pointer.py` that implements this
logic deterministically. The script accepts a `--dry-run` flag and operates
on the project root `CLAUDE.md`. The skill calls it as the final write step
in Phase 8.

### Test-case guidance

Each skill should be tested for:

1. New output (no state file, no output file).
2. Resume from state file (no output yet).
3. Resume from state file (output already present — merge path).
4. Output file with invalid schema (validator surfaces errors).
5. CLAUDE.md pointer injection (file absent → created; bullet present →
   timestamp updated; section present but bullet missing → bullet
   appended).

### Edge cases reference

Every non-trivial skill includes `references/edge-cases.md` covering at
minimum: missing/corrupted inputs, conflicting scan signals, skipped
required fields, mid-interview abort, write-permission errors, very
large repos.

## Key files and directories

- `CLAUDE.md` — this file (project conventions).
- `sdlc/.claude-plugin/plugin.json` — plugin manifest (skills inventory).
- `sdlc/skills/<skill>/` — per-skill folder.
- `.claude/skills-state/` — per-skill session state.
- `docs/` — generated SDLC artifacts (project root).
- `pyproject.toml` — Python dependencies (`pip install -e .`).

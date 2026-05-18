---
name: ux
description: >
  Explicitly invoked skill. Creates or updates docs/UX.yaml plus one
  docs/UX__<surface>.yaml per UI surface, consumed by downstream coding
  agents (api → arch → test → task → deploy). Trigger only on /sdlc:ux
  or a direct natural-language request to start the UX surface skill —
  never auto-trigger from generic UI/design chatter.
user-invocable: true
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read Write(CLAUDE.md) Write(docs/UX.yaml) Write(docs/UX__*.yaml) Write(.claude/skills-state/sdlc-ux.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-ux

Guides the user through a structured interview that produces a validated
`docs/UX.yaml` (global UX contract) plus one `docs/UX__<surface>.yaml`
per UI surface, so downstream AI agents have an unambiguous machine-
readable description of every screen, modal, panel, CLI command, or
flow step they need to implement.

## What this skill does (at a glance)

1. **Resume check** → load existing state if any.
2. **Scan + idea capture** → read `docs/PRD.yaml`, verify
   `metadata.status == "complete"`, run PRD's validator, exit early if
   the PRD isn't there or isn't complete.
3. **Structural questions** → confirm surface family
   (cli | web | mobile | desktop | mixed) derived from
   `PRD.technical_constraints.runtime_platform`.
4. **Pre-fill confirmation** → theme by theme, each `⚠ inferred` confirmed individually.
5. **Theme interview** → required themes always run; optional themes are
   gated now/skip/todo. Theme 4 (`surface_inventory`) and theme 11
   (`per_surface_deepdive`) run as `critical` per-item drill-downs —
   every surface is examined, confirmed, and traced back to PRD flows.
6. **Write & validate** → merge into `docs/UX.yaml` and write all
   `docs/UX__<surface>.yaml`, then run `validate_schema.py` (which also
   runs the PRD-flow coverage check).
7. **CLAUDE.md pointer + close** → call `set_claude_md_pointer.py`, mark
   state `complete`.

State is persisted **after every confirmed batch and after every
per-surface deep-dive**, so the user can `EXIT` at any time without
losing progress.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `ux-questions.yaml` | Full question inventory grouped by theme. |
| `UX.schema.yaml` | Human-readable canonical schema for `docs/UX.yaml`. |
| `UX__SURFACE.schema.yaml` | Human-readable canonical schema for `docs/UX__<surface>.yaml`. |
| `validate_schema.py` | Pydantic v2 validator (UX.yaml + every UX__*.yaml + PRD coverage check). |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector, called in Phase 8. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, EXIT handling, conditional promotions. Read on entering Phase 6. |
| `references/surface-discovery.md` | How to enumerate surfaces from PRD workflows, generate `surface_id`s, run the per-surface state machine. Read whenever theme 4 or 11 is active. |
| `references/cli-ux.md` | CLI-specific guidance — subcommand modelling, arg parsing, output formats, exit codes. Loaded only when `surface_family == "cli"`. |
| `references/merge-validate.md` | Merge logic for `UX.yaml` and surface yamls, the flow-coverage check, CLAUDE.md pointer rules. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations and how to handle them. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/UX.yaml` (project root) | Global UX contract consumed by downstream agents. |
| `docs/UX__<surface>.yaml` (project root) | One file per UI surface. `<surface>` is kebab-case. |
| `.claude/skills-state/sdlc-ux.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer bullet injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the
free-text field of any `AskUserQuestion` call to abort. State is saved
after every confirmed batch and after every per-surface deep-dive, so
progress is never lost — `EXIT` simply marks the session
`status: aborted` and stops.

There is no `SAVE` command — saving is implicit.

## The 8-phase flow

### Phase 1 — Resume check

Before doing anything else, check for
`.claude/skills-state/sdlc-ux.state.yaml`:

- If it exists with `status: in_progress`, ask:
  > "I found an unfinished UX session from `<last_updated>`. Would you
  > like to **resume**, **restart** (discard previous answers), or
  > **discard** (delete state and exit)?"
- If `status: complete` or `status: aborted` and `docs/UX.yaml` exists,
  treat this as an update flow — see `references/merge-validate.md`.
- If no state file, continue to Phase 2.

### Phase 2 — Scan inputs

`sdlc:ux` does NOT re-interview anything that already lives in `docs/PRD.yaml`.
Read these files at startup:

1. **`docs/PRD.yaml`** — required. Run the PRD validator first:

   ```bash
   python sdlc/skills/prd/validate_schema.py --path docs/PRD.yaml
   ```

   - If exit code ≠ 0 or `metadata.status != "complete"` → stop. Print
     a clear warning telling the user to complete the PRD first
     (`/sdlc:prd`). Do not proceed.
   - If valid and complete → extract the fields the UX skill needs:
     - `technical_constraints.runtime_platform` → preliminary `surface_family`
     - `technical_constraints.framework` → preliminary component-library hint
     - `non_functional_requirements.accessibility` → preliminary WCAG target
     - `use_cases.core_workflows` → preliminary surface inventory candidates
     - `users_personas.expertise_level` → tone hint
     - `product_identity.name`, `product_identity.one_liner` → context only
     - `functional_requirements.must_have_features` → may suggest surfaces
     - `metadata.monorepo` + `products: <slug>:` → if true, the UX skill
       runs the interview **per product** and writes one `UX.yaml` per
       product slug. (See `references/edge-cases.md` — monorepo mode.)

2. Existing `docs/UX.yaml` and `docs/UX__*.yaml` — if present, treat as
   the merge baseline (Phase 7).

3. Optional context files at project root: `README*`, design notes
   under `docs/design/`, `docs/wireframes/`, any `*ux*.md`, `*flow*.md`.
   Quote findings in pre-fill rationale.

Build the pre-fill map exactly as `sdlc:prd` does, classifying each
candidate as `✓ found` (direct PRD/file value) or `⚠ inferred` (derived).

### Phase 3 — Idea capture (lightweight)

Unlike `sdlc:prd`, this skill does NOT need to capture a free-text idea
brief — the PRD's `product_identity.idea_text` already serves that role.
Quote it back briefly so the user knows the context you're working with:

> "Working from `docs/PRD.yaml`. Product: `<name>` — `<one_liner>`.
> Runtime platform: `<runtime_platform>`. PRD lists `<N>` core workflows.
> Starting the UX interview. Type anything to add framing context, or
> `ok` to proceed."

If the user types extra context, store it verbatim in `state.idea_text`
(used as additional pre-fill signal — never overwrites PRD).

### Phase 4 — Structural questions

These determine the *shape* of the UX output:

1. **Surface family** — derived from
   `PRD.technical_constraints.runtime_platform`:
   - `cli` → `surface_family: cli`
   - `web` → `surface_family: web`
   - `mobile_ios | mobile_android` → `surface_family: mobile`
   - `desktop` → `surface_family: desktop`
   - `server | embedded | browser_extension | other` → ask the user to
     pick `cli | web | mobile | desktop | mixed`.
   - `mixed` is used when the product genuinely targets ≥2 surface
     families (e.g. a web app + a CLI companion).
   - Always surface as `⚠ inferred` position-1 option; user must
     confirm or pick another.

2. **(only if `mixed`)** Which surface families? (multi-select from
   `cli`, `web`, `mobile`, `desktop`)

3. **(only if `web` or `mixed-including-web`)** Device targets
   (desktop, tablet, mobile) and viewport breakpoints. Pre-fill from
   common defaults; user confirms.

4. **(only if `cli` or `mixed-including-cli`)** Promote theme
   `cli_specifics` to required for that surface family.

Persist these to state under `surface_family:`, `surface_family_members:`,
`device_targets:`, `viewport_breakpoints:` before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme**. Same rules as `sdlc:prd`:

- `✓ found` items can be batch-accepted with `ok`.
- `⚠ inferred` items must be confirmed or corrected one by one. No
  batch-acceptance. **This is the hallucination guard.**

Write confirmed values to state with the right `_confidence` value:
`confirmed` (explicit pick or typed answer) or `inferred` (`⚠` accepted
as-is).

### Phase 6 — Theme interview

Walk the themes in this order (canonical order from `ux-questions.yaml`):

1. `platform_and_shell` — required.
2. `design_principles` — required.
3. `navigation_model` — required.
4. **`surface_inventory`** — required, `synthesis: true`. CRITICAL tier.
   Per-item drill-down (see `references/surface-discovery.md`). Build the
   inventory of surfaces and trace each to PRD `use_cases.core_workflows`.
5. `component_library` — required.
6. `state_patterns` — required.
7. `content_rules` — required.
8. `accessibility` — required.
9. `localisation` — optional (now/skip/todo gate).
10. **`cli_specifics`** — `required_if: surface_family in ['cli', 'mixed']`.
11. **`per_surface_deepdive`** — required, `synthesis: true`. CRITICAL tier.
    For each surface defined in theme 4, run a per-surface mini-interview
    that fills out the surface yaml (layout, states, interactions,
    components, validation, accessibility, `traces_prd_flows`).

Required questions can never be `todo`'d. They must be answered, set to
`null` (writing a note to `ux_warnings`), or the user must `EXIT`.

After all themes are addressed, set `suggestion_phase_done: true` in state.

#### Within a theme: tiered question flow

Same tier mechanics as `sdlc:prd` — see
`references/interview-mechanics.md` for batch format and
`references/surface-discovery.md` for the `critical` per-surface state
machine.

Tier assignments (set in `ux-questions.yaml`):

- Theme 4 (`surface_inventory`) → `critical` per item — every surface
  is examined, named, typed, and traced back to PRD flows.
- Theme 11 (`per_surface_deepdive`) → `critical` per surface — for each
  surface, run the full per-surface mini-interview (layout / states /
  interactions / components / validation / accessibility / traces).
- Themes 2, 3, 5, 7 → mostly `high` (agent drafts; user iterates).
- Remainder → `med` (batched 2–4 per `AskUserQuestion` call).

**Read `references/surface-discovery.md` before running theme 4 or 11.**
**Read `references/cli-ux.md` before running theme 10.**

The two non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended option**
   in their `AskUserQuestion` call. They cannot be silently accepted —
   the user must explicitly pick or correct.
2. State is written after **every confirmed batch, every mini-section,
   and every per-surface deep-dive completion**.

#### Conditional promotions (`required_if`)

Some questions in `ux-questions.yaml` are conditionally required:

| Question / theme | Becomes required when |
|---|---|
| `cli_specifics` (entire theme) | `surface_family in ['cli', 'mixed']` |
| `device_targets`, `viewport_breakpoints` | `surface_family in ['web', 'mobile', 'desktop', 'mixed']` |
| `localisation.framework` | `localisation.enabled == true` |

Re-evaluate at the start of each new theme batch.

### Phase 7 — Write & validate

Write or merge `docs/UX.yaml` and write every `docs/UX__<surface>.yaml`
in one consistent batch (so that the surface inventory and the per-
surface files always agree).

Then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/UX.yaml
```

The validator also walks `docs/UX__*.yaml` siblings and runs the
**PRD-flow coverage check**: every entry in `PRD.use_cases.core_workflows`
must be referenced by at least one `UX__<surface>.yaml` via
`traces_prd_flows`. Any uncovered flow is appended to `UX.yaml`'s
`ux_warnings` and forces `status: draft`.

For full merge logic and the exit-code recovery flow, see
`references/merge-validate.md`.

When writing files: inline YAML comments on top-level keys, updated
`metadata.last_updated` and `metadata.session_id`.

Set `metadata.status`:
- `"complete"` — only when all required fields are filled, the validator
  passes with `[OK]`, AND the coverage check passes.
- `"draft"` — on early EXIT, when any required field is null, or when
  coverage is incomplete.

### Phase 8 — CLAUDE.md pointer & complete

On successful validation (`[OK]` or `[DRAFT]`), call
`set_claude_md_pointer.py` to inject or update this skill's bullet
inside the shared `## SDLC Documents` section of the project root
`CLAUDE.md`. Create `CLAUDE.md` with the section if missing.

Bullet format (the pointer script produces this exact text):

```
- `docs/UX.yaml` (+ `docs/UX__<surface>.yaml`): UX surfaces, flows, components, and states. Load when working on UI implementation, flow wiring, or component contracts. Last updated by `sdlc-ux` on <ISO-8601 timestamp>.
```

For the bullet detection rule and append behavior, see
`references/merge-validate.md`.

After the CLAUDE.md write succeeds: set `status: complete` in the state
file (keep the file — audit trail), tell the user where the artifacts live.

## Session state file

Path: `.claude/skills-state/sdlc-ux.state.yaml`

Schema (extends the baseline state schema from CLAUDE.md):

```yaml
session_id: <uuid4 string>
skill_version: "1.0"
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted

# Phase 4 — structural answers (mirror UX.yaml top-level)
surface_family: null        # cli | web | mobile | desktop | mixed
surface_family_members: []  # populated only when surface_family == "mixed"
device_targets: []
viewport_breakpoints: []

idea_text: null             # optional extra context user typed in Phase 3
pre_fill_confirmed: false
suggestion_phase_done: false
completed_themes: []
skipped_themes: []
todo_themes: []
pending_themes: []
current_theme: null
current_surface: null       # which surface_id is mid-deepdive (theme 11)

# Surface registry — one entry per defined surface
defined_surfaces:           # extension over the baseline state schema
  - surface_id: <kebab>
    surface_type: <enum>     # screen | modal | panel | cli_command | flow_step | …
    status: defined          # defined | draft | confirmed
    file_path: docs/UX__<slug>.yaml
    traces_prd_flows: []     # filled during theme 11

partial_answers: {}         # mirrors UX.yaml structure incrementally
partial_surfaces: {}        # mirrors per-surface yamls incrementally,
                            # keyed by surface_id
```

Rules:

- Generate `session_id` as a UUID4 on first creation.
- Update `last_updated` on every write.
- Write the file **after every confirmed batch** and **after every
  per-surface deep-dive completion**.
- On user `EXIT`: set `status: aborted`, write current `partial_answers`
  and `partial_surfaces`, confirm to user, stop.
- On Phase 8 completion: set `status: complete`, keep the file.
- The validator ignores this file — it validates only `docs/UX.yaml`
  and the surface yamls.

**Source of truth on resume:**

- `docs/UX.yaml` + the existing `docs/UX__*.yaml` files (if present)
  are the on-disk source of truth for *answers*.
- The state file is the source of truth for *interview progress*.
- On resume: load the on-disk yamls first as the baseline, then layer
  `partial_answers` and `partial_surfaces` on top.
- If they conflict on the same key, ask the user which to keep —
  never silently overwrite.

## Edge cases

For unusual situations (PRD missing or in draft state, surfaceless PRD
workflow, conflicting design decisions across surfaces, mid-interview
platform change, deleted PRD workflows mid-session, validation
failures, write-permission errors, monorepo mode) →
`references/edge-cases.md`.

## Style of conversation

The interview can be long, especially for products with many surfaces.
Keep it humane:

- Use the user's terminology as soon as they introduce it.
- Keep `AskUserQuestion` batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme boundary
  (*"Navigation done — next: surface inventory, ~6 surfaces drawn from
  the PRD workflows."*).
- For theme 11 (per-surface deep-dive), announce each surface before
  diving in (*"Now: `surface-id` (cli_command). 4 questions."*).
- Always make multiple-choice the path of least resistance.
- For the `surface_inventory` and `per_surface_deepdive` themes,
  explicitly call out that candidates were synthesized from the PRD —
  don't pretend they came from nowhere.
- After all themes are done, congratulate the user briefly and move to
  write/validate. Do not repeat everything back at them.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 framing summary. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs it to `ux_warnings`. |

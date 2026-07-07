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
   the PRD isn't there or isn't complete. Build a pre-fill map from
   **every relevant PRD family** (WKF, FR, ENT, JTB), not just workflows.
3. **Structural questions** → confirm surface family
   (cli | web | mobile | desktop | mixed) derived from
   `PRD.technical_constraints.runtime_platform`.
4. **Pre-fill confirmation** → theme by theme, each `⚠ inferred` confirmed individually.
5. **Theme interview** → required themes always run; optional themes are
   gated now/skip/todo. Theme 4 (`surface_inventory`) and theme 11
   (`per_surface_deepdive`) run as `critical` per-item drill-downs —
   every surface is examined, assigned a stable `SCR-NNN` id, and traced
   back to PRD via `traces_workflows` / `implements_requirements` /
   `references_entities`. Theme 4 closes with a **dynamic scope-
   completeness sweep** (analogous to PRD's `must_have_features` sweep)
   that catches surfaces implied by FR/ENT/JTB ids but not by any WKF.
6. **Write & validate** → merge into `docs/UX.yaml` and write all
   `docs/UX__<surface>.yaml`, prefixing every `ux_warnings` entry with a
   stable `WRN-NNN`, then run `validate_schema.py` (schema + ID-prefix
   format + PRD WKF-### coverage).
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

**Slice large docs, don't slurp.** If `docs/INDEX.yaml` exists (the project ran
`/sdlc:setup`), read `PRD.yaml` (often 1000+ lines) by slice: look an `FR-###`
or a top-level section up in `INDEX.yaml` (or `python .claude/sdlc/docs_index.py
--show <symbol>`) and `Read` only its `[start, end]` range, rather than loading
the whole PRD to pull a handful of workflows/features. Fall back to whole-file
reads when `INDEX.yaml` is absent. Protocol: `.claude/rules/sdlc-docs-access.md`.

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
     - `use_cases.core_workflows` (WKF-###) → primary seed for surface inventory
     - `functional_requirements.must_have_features` (FR-###) → seed for
       feature-driven surfaces (verbs/screens that implement a specific FR)
     - `functional_requirements.nice_to_have_features` (FR-###) → secondary
       seed; surfaces here get `status: defined` but may stay
       post-MVP-only at the user's discretion
     - `data_model.key_entities` (ENT-###) → seed for entity-driven
       surfaces (CRUD screens, list/detail/registry views, e.g. a
       `ProjectRegistry` entity implies a `list` command)
     - `use_cases.primary_jobs_to_be_done` and `secondary_jobs` (JTB-###)
       → orthogonal lens consulted during the scope-completeness sweep
     - `users_personas.expertise_level` → tone hint
     - `product_identity.name`, `product_identity.one_liner`,
       `product_identity.slug` → context + CLI root_command pre-fill
     - `conventions.artifact_ids` (if present) → the binding ID-family
       map. The UX skill respects every family listed and never invents
       IDs in an upstream family.
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

**Upstream-change detection (re-runs).** If `docs/UX.yaml` already exists and
carries `metadata.upstream_provenance`, this is a re-run: check whether
`docs/PRD.yaml` moved since the last write by comparing the recorded `sha256`
to PRD's current hash (from `docs/INDEX.yaml.generated_from[docs/PRD.yaml]`,
else compute `sha256(bytes)[:16]`). If PRD changed, classify the delta
(added / removed / modified PRD ids) and run the **delta-review pass before
the theme interview** per
`sdlc/skills/ux/references/upstream-reconciliation.md` (CLAUDE.md §7). If PRD
is unchanged, this is an ordinary refine — proceed to the merge flow without a
delta-review. Fresh runs (no prior `docs/UX.yaml`) skip this step.

**Downstream-claim reconciliation (re-runs).** Upstream isn't the only thing
that moves under a UX artifact — downstream does too, and surface `status` is
lifecycle metadata that must track it. On every re-run over an existing
`docs/UX.yaml`, peek at the downstream artifacts if present:

1. Collect the claimed surface set: every `surface_id` in any
   `docs/ARCH.yaml.containers[].owns_ux_surfaces` (and, where drilled, the
   matching `ARCH__*.yaml.ux_surface` lists).
2. For each claimed surface whose inventory `status` is not `confirmed`
   (still `proposed` / `defined` / `draft`), run one consolidated
   `AskUserQuestion` sweep: *"These surfaces are claimed by the architecture
   (and may already be tested) but UX still marks them `<status>`: …"* — per
   surface the user picks **confirm** (bump `status: confirmed`; if it was
   `proposed`, it has evidently been promoted into scope) / **keep** (the
   downstream claim is premature — log a `WRN-NNN` naming the mismatch so the
   arch side gets fixed) / **drop the claim note** (user will fix ARCH).
3. Never bump silently — the mismatch may mean ARCH is wrong, not UX.

The ux validator surfaces the same mismatch as a standing non-blocking
warning ("claimed downstream but not 'confirmed'"), so a stale lifecycle
can't hide between re-runs. Skip the sweep when no downstream artifact
exists yet (the normal first-chain pass).

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
  is examined, named, typed, assigned the next `SCR-NNN` id, and traced
  to PRD via `traces_workflows`. **After the per-item loop closes, a
  dynamic scope-completeness sweep runs** over every upstream PRD family
  (WKF, FR, ENT, JTB) plus project-type heuristics to catch missed
  surfaces. See `references/surface-discovery.md`.
- Theme 11 (`per_surface_deepdive`) → `critical` per surface — for each
  surface, run the full per-surface mini-interview (layout / states /
  interactions / components / validation / accessibility /
  traces_workflows). `implements_requirements` (FR-###) and
  `references_entities` (ENT-###) are inferred by the agent from the
  surface's purpose and presented in the final-approval draft for the
  user to correct.
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

Writer responsibilities for the new ID conventions:

- Every entry appended to `ux_warnings` is prefixed `"WRN-NNN: <message>"`,
  using and persisting `state.last_ids.WRN`.
- Every surface in `surface_inventory` carries its stable `id: SCR-NNN`
  (assigned in theme 4; persisted in `state.last_ids.SCR`).
- The corresponding `docs/UX__<surface_id>.yaml` mirrors the same
  `id: SCR-NNN`.
- All PRD references — in `traces_workflows`, `implements_requirements`,
  `references_entities`, and `cli.exit_codes[code].implements_requirements`
  — are stored as **ID strings only** (e.g. `"WKF-001"`), never as
  verbatim text. The validator's coverage check matches by id.
- `metadata.changelog`: when running in update mode (existing UX.yaml on
  disk), prepend one entry describing the material change, format
  `"<version> (<YYYY-MM-DD>): <one-line summary>"`. Append-only — never
  rewrite existing entries.
- `metadata.upstream_provenance`: (re)write the snapshot of every upstream
  artifact consumed this run — for ux, one entry for `docs/PRD.yaml`
  (`{file, session_id, last_updated, sha256}`; `sha256` from
  `docs/INDEX.yaml.generated_from`, else `sha256(bytes)[:16]`).
  Replace-on-write (not append-only), so it always reflects the latest write.
  See CLAUDE.md §7.

Then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/UX.yaml
```

The validator walks `docs/UX__*.yaml` siblings, enforces ID-prefix
formats (SCR/WRN/WKF/FR/ENT), and runs the **PRD WKF-NNN coverage check**:
every WKF-NNN parsed out of `PRD.use_cases.core_workflows` must be
referenced by at least one `UX__<surface>.yaml` via `traces_workflows`.
Any uncovered id is appended to `UX.yaml`'s `ux_warnings` (as a fresh
`WRN-NNN: coverage: WKF-XYZ has no surface trace` entry) and forces
`status: draft`.

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

**Refresh the navigation index.** If `.claude/sdlc/docs_index.py` exists (the
project ran `/sdlc:setup`), run `python .claude/sdlc/docs_index.py` after
writing `docs/UX.yaml` and its per-surface files so `docs/INDEX.yaml` reflects
the new content right away (the setup hook also does this, but a hook added
mid-session only activates next session). Harmless no-op if not installed.

After the CLAUDE.md write succeeds: set `status: complete` in the state
file (keep the file — audit trail), tell the user where the artifacts live.

## Session state file

Path: `.claude/skills-state/sdlc-ux.state.yaml`

Schema (extends the baseline state schema from CLAUDE.md):

```yaml
session_id: <uuid4 string>
skill_version: "1.1"
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
current_surface: null       # which SCR-NNN is mid-deepdive (theme 11)

# Per-family ID counters (single-product mode). Each entry is the last-
# assigned integer for that family — increment, format as <PREFIX>-{:03d},
# then persist. Families this skill emits:
#   SCR — surface inventory ids (writer-managed; assigned when a surface
#         candidate is accepted in theme 4 step a, or accepted from the
#         scope-completeness sweep in theme 4 step e).
#   WRN — ux_warnings entries (writer-managed; assigned at write time).
last_ids: {}                # e.g. {SCR: 9, WRN: 11}

# Per-product ID counters (monorepo mode only). Same shape as last_ids,
# keyed by product slug. Each product carries an independent SCR/WRN space.
last_ids_by_product: {}     # e.g. {auth: {SCR: 3, WRN: 1}, billing: {SCR: 5}}

# Surface registry — one entry per defined surface
defined_surfaces:           # extension over the baseline state schema
  - id: <SCR-NNN>            # stable id assigned in theme 4
    surface_id: <kebab>      # slug; may be renamed by the user — id stays
    surface_type: <enum>     # screen | modal | panel | cli_command | flow_step | …
    status: defined          # defined | draft | confirmed
    file_path: docs/UX__<slug>.yaml
    traces_workflows: []     # WKF-NNN ids; filled during theme 4/11
    implements_requirements: []  # FR-NNN ids (optional; inferred during deepdive)
    references_entities: []      # ENT-NNN ids (optional; inferred during deepdive)

# Sweep state — tracks scope-completeness sweep passes for theme 4
sweep_passes_done: 0        # 0 | 1 | 2; capped at 2 per importance-flows.md
dropped_surface_candidates: []  # candidates the user explicitly dropped;
                                # not re-proposed on resume

partial_answers: {}         # mirrors UX.yaml structure incrementally
partial_surfaces: {}        # mirrors per-surface yamls incrementally,
                            # keyed by SCR-NNN (stable across renames)
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

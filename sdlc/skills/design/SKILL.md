---
name: design
description: >
  Explicitly invoked skill. Creates or updates docs/DESIGN.yaml — the visual
  design-system contract — plus docs/DESIGN__tokens.yaml (design tokens) and
  docs/DESIGN__assets.yaml (asset manifest + generation briefs) when they
  apply. Consumes docs/PRD.yaml + docs/UX.yaml; consumed by downstream coding
  agents (and arch/task) to style every surface and scaffold the asset
  pipeline. Trigger only on /sdlc:design or a direct natural-language request
  to start the design-system skill — never auto-trigger from generic design,
  styling, branding, or asset chatter.
user-invocable: true
disable-model-invocation: true
model: opus
effort: high
allowed-tools: Read Write(CLAUDE.md) Write(docs/DESIGN.yaml) Write(docs/DESIGN__*.yaml) Write(.claude/skills-state/sdlc-design.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion WebFetch
---

# sdlc-design

Guides the user through a structured interview that produces a validated
`docs/DESIGN.yaml` (global design-system contract) plus, when they apply,
`docs/DESIGN__tokens.yaml` (the concrete DTCG token set) and
`docs/DESIGN__assets.yaml` (the asset manifest + per-asset generation briefs).
This fills the gap UX leaves: UX defines *what each surface does*; DESIGN
defines *what it looks like* and *what bespoke assets must exist*, so downstream
coding agents can actually style the surfaces and scaffold the asset pipeline.

## The two orthogonal axes (read this first)

A design is described along two axes that **combine freely** — a structure
choice never constrains a look:

- **Axis A — `functional_structure`** (HOW visuals are realized in code):
  a multi-select subset of `{token_based_ui, asset_pipeline, headless}`.
  `headless` is exclusive. A game with menus is BOTH `token_based_ui` (HUD/menus)
  and `asset_pipeline` (canvas).
- **Axis B — `aesthetic_direction`** (WHAT it looks and feels like):
  an OPEN style vocabulary + mood + palette intent + references + typographic
  voice + motion + texture/finish. It rides on *any* structure, so a
  `token_based_ui` can carry a hand-drawn / comic / manga / vaporwave look —
  styles a single "UI theme" enum could never express.

**The bridge between the axes:** an artistic aesthetic on a token UI still
needs bespoke illustration/icon/texture assets.
`aesthetic_direction.requires_custom_assets: true` emits an asset manifest
**even on a pure `token_based_ui`**. This is what makes "component UI + comic
style" actually buildable — don't skip it.

## What this skill does (at a glance)

1. **Resume check** → load existing state if any.
2. **Scan** → read `docs/PRD.yaml` + `docs/UX.yaml` (+ `UX__*`) by slice; verify
   both `metadata.status == "complete"` and pass their validators; exit early if
   missing/incomplete. Build a pre-fill map from PRD (identity, brand signals,
   accessibility NFR, asset-implying entities, product type) and UX
   (surface_family, component_library, design_principles, content_rules,
   accessibility, surface ids).
3. **Structural questions** → confirm **Axis A** `functional_structure`, derived
   from UX `surface_family` + PRD product type. This decides which sub-files and
   themes exist.
4. **Pre-fill confirmation** → theme by theme; each `⚠ inferred` confirmed
   individually (hallucination guard).
5. **Theme interview** → **Axis B** aesthetic, then (conditionally) design
   tokens, the asset manifest (critical per-item drill-down + scope sweep), the
   per-asset generation briefs, and brand identity.
6. **Write & validate** → write `docs/DESIGN.yaml` + the applicable sub-files;
   assign `AST-NNN` / `WRN-NNN`; record provenance; run `validate_schema.py`
   (schema + ID-prefix + composition + asset-brief coverage).
7. **CLAUDE.md pointer + close** → `set_claude_md_pointer.py`, mark state
   complete, refresh `docs/INDEX.yaml`.

State is persisted **after every confirmed batch, every token group, and every
per-asset step**, so the user can `EXIT` at any time without losing progress.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `design-questions.yaml` | Full question inventory grouped by theme. |
| `DESIGN.schema.yaml` | Canonical schema for `docs/DESIGN.yaml` (the two axes). |
| `DESIGN__TOKENS.schema.yaml` | Canonical schema for `docs/DESIGN__tokens.yaml`. |
| `DESIGN__ASSETS.schema.yaml` | Canonical schema for `docs/DESIGN__assets.yaml`. |
| `validate_schema.py` | Pydantic v2 validator (DESIGN.yaml + sub-files + composition + coverage). |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector (Phase 8). |
| `references/interview-mechanics.md` | Batch format, schema_path prefixes, EXIT, conditional promotions. Phase 6. |
| `references/aesthetic-direction.md` | Axis B mechanics: open vocab, web_fetch references, the artistic→assets bridge. |
| `references/design-tokens.md` | DTCG authoring, preset import, theme modes, contrast, brand locking. |
| `references/asset-pipeline.md` | Per-asset critical state machine, scope sweep, generation-brief authoring + coverage. |
| `references/merge-validate.md` | Phase 7/8 write/merge logic, validator exit codes, pointer rules. |
| `references/edge-cases.md` | Unusual situations and how to handle them. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/DESIGN.yaml` (project root) | Global design-system contract. |
| `docs/DESIGN__tokens.yaml` | DTCG token set — iff `token_based_ui` ∈ functional_structure. |
| `docs/DESIGN__assets.yaml` | Asset manifest — iff `asset_pipeline` ∈ functional_structure OR `requires_custom_assets`. |
| `.claude/skills-state/sdlc-design.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer bullet injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the free-text
field of any `AskUserQuestion` call to abort. State is saved after every
confirmed batch / token group / per-asset step, so progress is never lost —
`EXIT` marks the session `status: aborted` and stops. There is no `SAVE`
command — saving is implicit.

## The 8-phase flow

### Phase 1 — Resume check

Before anything else, check `.claude/skills-state/sdlc-design.state.yaml`:

- `status: in_progress` → ask: *"I found an unfinished design session from
  `<last_updated>`. Resume, restart (discard previous answers), or discard
  (delete state and exit)?"*
- `status: complete` or `aborted` and `docs/DESIGN.yaml` exists → treat as an
  update flow (see `references/merge-validate.md`); if an upstream changed,
  run the §7 delta-review first (Phase 2).
- No state file → continue to Phase 2.

### Phase 2 — Scan inputs

`sdlc:design` does NOT re-interview anything already in `docs/PRD.yaml` or
`docs/UX.yaml`.

**Slice large docs, don't slurp.** If `docs/INDEX.yaml` exists (the project ran
`/sdlc:setup`), read `PRD.yaml` / `UX.yaml` by slice via the index (or
`python .claude/sdlc/docs_index.py --show <symbol>`) rather than whole-file.
Protocol: `.claude/rules/sdlc-docs-access.md`.

Read at startup:

1. **`docs/UX.yaml`** — required. Run the UX validator first:
   ```bash
   python sdlc/skills/ux/validate_schema.py --path docs/UX.yaml
   ```
   - If exit ≠ 0 or `metadata.status != "complete"` → **stop**. Tell the user
     to finish UX first (`/sdlc:ux`). Do not proceed.
   - If valid → extract: `surface_family` (→ Axis A seed), `component_library`
     (name/theming_approach/theming_tokens → token pre-fill), `design_principles`
     (tenets/inspiration_refs → aesthetic seed), `content_rules.tone`
     (→ typographic/brand voice), `accessibility.wcag_target` (→ token contrast
     constraint), `surface_inventory` (SCR-NNN ids → `traces_ux_surfaces`).
2. **`docs/PRD.yaml`** — required. Validate it too
   (`python sdlc/skills/prd/validate_schema.py --path docs/PRD.yaml`); same
   stop rule. Extract: `product_identity` (name/one_liner/idea_text → brand +
   product type), `data_model.key_entities` (ENT-NNN — entities like
   Character/Sprite/Level imply assets), `non_functional_requirements`
   (accessibility/brand/theming NFRs → `implements_requirements`),
   `functional_requirements` (FR mentioning render/canvas/asset/audio/3D → asset
   signal), `conventions.artifact_ids` (the binding ID-family map).
3. Existing `docs/DESIGN.yaml` + sub-files — if present, the merge baseline (Phase 7).
4. Optional context: `README*`, `docs/design/`, brand guidelines, any
   `*style*.md` / `*brand*.md`. Quote findings in pre-fill rationale.

Build the pre-fill map classifying each candidate `✓ found` (direct quote) or
`⚠ inferred` (derived).

**Upstream-change detection (re-runs).** If `docs/DESIGN.yaml` exists and carries
`metadata.upstream_provenance`, compare the recorded `sha256` of `docs/PRD.yaml`
and `docs/UX.yaml` to their current hashes (from
`docs/INDEX.yaml.generated_from`, else `sha256(bytes)[:16]`). If either moved,
classify the delta and run the **delta-review pass before the theme interview**
per `sdlc/skills/ux/references/upstream-reconciliation.md` (CLAUDE.md §7). If
both are unchanged, this is an ordinary refine — skip the delta-review.

### Phase 3 — Idea capture (lightweight)

Quote the context back so the user knows what you're working from:

> "Working from `docs/PRD.yaml` + `docs/UX.yaml`. Product: `<name>` —
> `<one_liner>`. UX surface family: `<surface_family>`, `<N>` surfaces. I'll
> propose a visual direction next. Type anything to add framing (a vibe, a
> reference, a brand), or `ok` to proceed."

Store extra context verbatim in `state.idea_text` (extra pre-fill signal —
never overwrites PRD/UX).

### Phase 4 — Structural questions (Axis A)

Run **theme 1 `functional_structure`** here — it shapes the whole output.

1. **Derive the recommendation from UX `surface_family`:**

   | UX surface_family | recommended functional_structure |
   |---|---|
   | `web` / `mobile` / `desktop` / `tui` | `[token_based_ui]` |
   | `cli` / `service` / `library` | `[headless]` |
   | `voice` | `[headless]` (Axis B still captures persona/voice) |
   | `mixed` | union over members |

2. **Add `asset_pipeline` when PRD signals a graphic-heavy product** —
   regardless of surface_family. Signals: product one-liner / idea_text mentions
   game, art, music, canvas, generative, illustration, creative tool; key
   entities like Sprite/Tile/Level/Scene/Character/Track; FRs mentioning
   render/canvas/asset/sprite/audio/3D. Surface this as `⚠ inferred` and confirm.

3. **Ask** (multi-select, `⚠ inferred` recommendation at position 1):
   `token_based_ui`, `asset_pipeline`, `headless`. Enforce: `headless` is
   exclusive (reject a mix; re-ask).

4. **Headless path.** If the user confirms `[headless]`:
   - `service` / `library` → DESIGN.yaml is minimal: `aesthetic_direction: null`,
     no sub-files; write a `WRN-NNN` note that visual design is not applicable
     (output/log/format conventions live in ARCH + code style). You may jump to
     Phase 7.
   - `cli` → offer an **optional** light terminal aesthetic (colour scheme,
     output style, ASCII/spinner character). If accepted, run theme 2 only; no
     tokens/assets. If declined, treat like service/library.

Persist `functional_structure`, `_confidence`, `_rationale` to state before
proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme**. `✓ found` items batch-accept with
`ok`; **`⚠ inferred` items are confirmed or corrected one by one — no
batch-acceptance. This is the hallucination guard.** Write confirmed values with
`<field>_confidence: confirmed` (explicit pick/typed) or `inferred` (`⚠`
accepted as-is).

### Phase 6 — Theme interview

Walk the themes in canonical order (skipping those whose `required_if` is false):

1. `functional_structure` — done in Phase 4.
2. **`aesthetic_direction`** (Axis B) — required for any visual structure.
   `high` tier (agent drafts, user iterates). Capture `style_family` (open
   vocab), `mood_keywords`, palette intent, references (fetch URLs to ground the
   look), typographic voice, motion, texture/finish. **Set
   `requires_custom_assets`** — pre-answer `true` when `style_family` is artistic
   or texture is non-trivial, then confirm. See `references/aesthetic-direction.md`.
3. **`design_tokens`** — `required_if: token_based_ui`. Offer **preset import**
   (shadcn / tailwind / Tokens Studio) as a fast pre-fill, else author DTCG from
   scratch. Per-group draft-approve (colour/typography/spacing required;
   radius/elevation/motion optional). Honour the accessibility contrast target;
   lock any `brand_palette`. Writes `docs/DESIGN__tokens.yaml`. See
   `references/design-tokens.md`.
4. **`asset_manifest`** — `required_if: asset_pipeline OR requires_custom_assets`.
   `critical synthesis: true`. Per-asset drill-down assigns `AST-NNN`; a
   **scope-completeness sweep** over the taxonomy + PRD entities + product type
   runs before the list closes. Writes `docs/DESIGN__assets.yaml`. See
   `references/asset-pipeline.md`.
5. **`asset_generation_briefs`** — `required_if: ≥1 asset is to_be_generated`.
   Per-asset: author a ready-to-run brief (modality, tools, prompt, anchors,
   constraints, acceptance). **Every `to_be_generated` asset ends with a brief
   OR an explicit `WRN-NNN` deferral** — the coverage gate. See
   `references/asset-pipeline.md`.
6. **`brand_identity`** — optional; now/skip/todo gate.

**Read `references/aesthetic-direction.md` before theme 2,
`references/design-tokens.md` before theme 3, and
`references/asset-pipeline.md` before themes 4–5.**

The two non-negotiable rules:

1. `⚠ inferred` candidates surface as the **position-1 recommended option** —
   never silently accepted.
2. State is written after **every confirmed batch, every token group, and every
   per-asset step (inventory item, sweep pass, and brief)**.

#### Tier mechanics + schema_path prefixes

Same `med | high | critical` tiers as `sdlc:prd`/`sdlc:ux` (canonical:
`sdlc/skills/prd/references/importance-flows.md`). The question `schema_path`
carries a prefix telling the agent which file the answer lands in:
`tokens.<…>` → DESIGN__tokens.yaml; `assets.<…>` → DESIGN__assets.yaml
top-level; `asset.<…>` → one asset entry (rewritten per asset); `brief.<…>` →
one asset's `generation_brief`. See `references/interview-mechanics.md`.

#### Trace inference (no separate theme)

`implements_requirements` (design-relevant FR/NFR) and `traces_ux_surfaces`
(SCR ids) are **inferred by the agent** from the aesthetic/token/asset answers
and presented in a final-approval draft for the user to correct — not asked as
their own theme. Omit `traces_ux_surfaces` to mean "applies to all visual
surfaces".

### Phase 7 — Write & validate

Write `docs/DESIGN.yaml` and every applicable sub-file in one consistent batch.
Writer responsibilities:

- Set `sub_artifacts.tokens` / `sub_artifacts.assets` to match what you wrote
  (and only when the composition rule holds).
- Assign `AST-NNN` to every asset (persist `state.last_ids.AST`); prefix every
  `design_warnings` entry `"WRN-NNN: <message>"` (persist `state.last_ids.WRN`).
- Store all upstream refs as **ID strings only** (`"SCR-003"`, `"FR-007"`,
  `"NFR-010"`, `"ENT-002"`) — never verbatim text.
- For every `to_be_generated` asset: write its `generation_brief`, OR add a
  `WRN-NNN` deferral naming its `AST-NNN` (trace-or-defer).
- `metadata.changelog`: in update mode, prepend one
  `"<version> (<YYYY-MM-DD>): <summary>"` line (append-only).
- `metadata.upstream_provenance`: (re)write a snapshot for `docs/PRD.yaml` and
  `docs/UX.yaml` (`{file, session_id, last_updated, sha256}`).

Then run:
```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/DESIGN.yaml
```
The validator checks schema, sub-file discovery, ID-prefix formats, **composition
consistency** (headless exclusive; tokens iff token_based_ui; assets iff
asset_pipeline/requires_custom_assets; aesthetic present unless pure headless),
and **asset-brief coverage** (trace-or-defer). Set `metadata.status: complete`
only on `[OK]`; otherwise `draft`. Exit-code handling +merge logic:
`references/merge-validate.md`.

### Phase 8 — CLAUDE.md pointer & complete

On validation exit 0 (`[OK]` or `[DRAFT]`), call `set_claude_md_pointer.py` to
inject/update the skill's bullet in the shared `## SDLC Documents` section.
Then **refresh the navigation index**: if `.claude/sdlc/docs_index.py` exists,
run `python .claude/sdlc/docs_index.py`. Set state `status: complete` (keep the
file as audit trail) and tell the user where the artifacts live.

## Session state file

Path: `.claude/skills-state/sdlc-design.state.yaml`. Extends the baseline state
schema:

```yaml
session_id: <uuid4>
skill_version: "1.0"
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress            # in_progress | complete | aborted

# Phase 4 — structural answers (mirror DESIGN.yaml top level)
functional_structure: null     # list: token_based_ui | asset_pipeline | headless
idea_text: null                # optional extra context from Phase 3
pre_fill_confirmed: false
completed_themes: []
skipped_themes: []
todo_themes: []
pending_themes: []
current_theme: null
current_asset: null            # which AST-NNN is mid-brief (theme 5)

# Per-family ID counters (single-product). Increment, format <PREFIX>-{:03d}, persist.
#   AST — asset ids (assigned when an asset is accepted in theme 4 / sweep).
#   WRN — design_warnings entries (writer-managed, assigned at write time).
last_ids: {}                   # e.g. {AST: 6, WRN: 2}
last_ids_by_product: {}        # monorepo only — same shape keyed by product slug

# Asset registry — one entry per accepted asset (theme 4)
defined_assets:
  - id: <AST-NNN>
    asset_type: <kind>
    source: <to_be_generated|user_supplied|placeholder>
    has_brief: false           # flips true when theme 5 authors the brief

sweep_passes_done: 0           # theme 4 scope sweep; capped at 2
dropped_asset_candidates: []   # candidates the user dropped; not re-proposed

partial_answers: {}            # mirrors DESIGN.yaml + sub-files incrementally
```

Rules: generate `session_id` UUID4 on first creation; update `last_updated` on
every write; write after every confirmed batch / token group / per-asset step;
on `EXIT` set `status: aborted` and flush partials; on Phase 8 set
`status: complete` and keep the file. The validator ignores this file.

**Source of truth on resume:** the on-disk yamls are authoritative for
*answers*; the state file for *interview progress*. Layer `partial_answers` on
top of the on-disk baseline; surface conflicts to the user — never silently
overwrite.

## Edge cases

For unusual situations (PRD/UX missing or draft, headless products, the
artistic-look-on-token-UI bridge, asset-less game, preset-import fetch failure,
stale SCR/FR/ENT refs, validation failures, write-permission errors, monorepo
mode) → `references/edge-cases.md`.

## Style of conversation

Design is a creative interview — keep it concrete and energetic:

- Lead Axis B with a *drafted* direction, not a blank prompt ("Given your calm,
  trustworthy PRD and the Linear reference in UX, here's a minimal-flat
  direction…"). Always make a sensible proposal.
- Use the user's terminology the moment they introduce it; challenge vague
  answers ("clean") for a concrete reference or example.
- Keep `AskUserQuestion` batches to 2–4 questions; `⚠ inferred` at position 1.
- Call out the cross-axis bridge explicitly when it fires ("a comic look on a
  component UI implies bespoke assets — I'll turn on an asset manifest").
- For the asset inventory and per-asset briefs, announce each item before
  diving in. Don't pretend candidates came from nowhere — cite the PRD
  entity / product type they were synthesized from.
- After all themes, congratulate briefly and move to write/validate.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, or accept the Phase 3 framing. |
| `now` / `skip` / `todo` | Run / skip / defer a proposed optional theme (gate question). |

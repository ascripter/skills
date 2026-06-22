# Edge cases — sdlc-design

Read whenever the agent hits a situation off the happy path.

## Input-side (PRD / UX)

- **`docs/UX.yaml` missing** → stop. "Cannot start design — `docs/UX.yaml` is
  missing. Run `/sdlc:ux` first." Exit without writing.
- **`docs/PRD.yaml` missing** → stop. "Cannot start design — `docs/PRD.yaml` is
  missing. Run `/sdlc:prd` first."
- **UX or PRD `status: draft` / validator fails** → do NOT proceed. The design
  is built on the surface inventory, component library, accessibility target,
  and product identity — a draft upstream makes those speculative. Offer:
  "Stop and finish UX/PRD first" (recommended) or "Proceed anyway and record
  draft status in `design_warnings`" (forces `DESIGN.yaml` to `draft`).
- **UX is monorepo** → DESIGN runs per product (see Monorepo below).

## Structure / axis edge cases

- **Pure headless (`service` / `library`)** → minimal `DESIGN.yaml`:
  `aesthetic_direction: null`, no sub-files, a `WRN-NNN` that visual design is
  not applicable (output/format conventions live in ARCH + code style). This is
  a valid `complete` state — don't force a look onto a headless product.
- **Headless `cli`** → offer an optional light terminal aesthetic (colour
  scheme, output style). If declined, treat as service/library. No tokens/assets.
- **`voice`** → no visuals; capture persona in `mood_keywords` /
  `typographic_voice` / `brand_voice`. No tokens/assets.
- **Artistic look on a token UI but user says "no custom assets"** → respect it,
  set `requires_custom_assets: false`, and add a `WRN-NNN` that the look depends
  on externally-sourced assets (asset pack / stock) the design doesn't specify.
  This is the one place the bridge is overridden — make the consequence explicit.
- **Game / creative product but PRD has no asset-implying entities** → still
  seed the inventory from product-type heuristics (a 2D game needs sprites /
  tileset / sfx / music / font) and let the sweep fill gaps. Don't end up with
  an empty manifest for an obviously graphic product.
- **`asset_pipeline` selected but the user adds 0 assets** → write an empty
  manifest with a `WRN-NNN` ("asset_pipeline selected but no assets specified")
  and force `draft`. An empty asset manifest on an asset product is a signal,
  not a finished state.

## Token edge cases

- **Preset import fetch/parse fails** → fall back to `dtcg_authored`, tell the
  user, add a `WRN-NNN`. Never block on a missing preset.
- **Brand colour fails the contrast target as text** → keep it for accent/
  non-text use, choose an accessible nearby ramp step for text, record both in
  `contrast_notes`. Don't silently alter a locked brand colour.
- **Accessibility target unmet by the drafted palette** → adjust ramp steps
  before approving; if the user insists on the failing palette, set `draft` +
  `WRN-NNN` naming the failing pairs.

## ID-family edge cases

- **`AST-NNN` / `WRN-NNN` counter drift on resume** → if `state.last_ids.<P>` is
  lower than the max id already on disk (user copied entries between projects),
  set the counter to `max(on_disk, state)` before assigning the next id.
- **A `traces_ux_surfaces` / `implements_requirements` / `references_entities`
  ref points to an id that no longer exists** (UX/PRD edited between sessions) →
  detect during Phase 2; ask per stale ref: "Surface/requirement/entity `<id>`
  no longer exists upstream. Remove the ref, re-route, or keep + record a
  `WRN-NNN`?" Never silently delete.
- **Wrong-family id in a ref field** (e.g. an `FR-NNN` in `traces_ux_surfaces`)
  → validator flags it (error in `complete`, warning in `draft`). Move it to the
  correct field.

## Asset / brief edge cases

- **`to_be_generated` asset the user can't yet brief** → defer it: add a
  `WRN-NNN` naming its `AST-NNN`. Coverage counts it as covered; the user briefs
  it in a later update session.
- **`user_supplied` / `placeholder` asset** → never needs a brief; never flagged
  by coverage. Note placeholders in `description` so downstream knows they're stubs.
- **Asset modality with no good generator** (e.g. a bespoke font) → still write
  the brief with `recommended_tools` noting it's typically hand-designed; the
  prompt becomes a design spec rather than a model prompt.
- **Very large inventory (> 30 assets)** → refuse politely past the hard cap;
  suggest grouping (a "tileset" entry instead of 40 individual tiles) or
  splitting into phases (`WRN-NNN: phase-2 assets — <…>`).

## Validation failures

Show field-level errors verbatim; offer via `AskUserQuestion`: "Fix now, or
accept `draft`?" Re-validate after re-entry. Common design-specific failures:

- **Composition mismatch** — claimed `complete` but the tokens/assets file is
  missing, or a sub_artifacts pointer is an orphan. Fix the structure↔file
  agreement (write the file, or clear the pointer + structure).
- **Uncovered `to_be_generated` asset** — author its brief or add a `WRN-NNN`
  deferral naming its AST id.
- **`headless` not exclusive** — drop the other members or change the structure.

## Write-permission errors

Report path + OS error verbatim; don't retry silently. Common: `docs/` missing
(offer to create), read-only FS, `CLAUDE.md` open in another editor.

## Monorepo mode

When `PRD/UX.metadata.monorepo == true`:

- `DESIGN.yaml` is monorepo-shaped (blocks under `products.<slug>`).
- Sub-files are `docs/DESIGN__<slug>__tokens.yaml` /
  `docs/DESIGN__<slug>__assets.yaml`. `AST`/`WRN` counters reset per product
  (`state.last_ids_by_product[<slug>]`).
- Run the interview per product; composition + coverage are checked per product
  by the validator. `design_warnings` stays top-level (a deferral names
  `<slug> AST-NNN` for clarity).

## Upstream changes between sessions (§7)

When `/sdlc:design` is re-invoked after `docs/DESIGN.yaml` exists and an upstream
moved, Phase 2 runs the consolidated **delta-review** (added / removed / modified
PRD or UX ids) before the interview, comparing recorded `metadata.upstream_
provenance` hashes to current. Full mechanics:
`sdlc/skills/ux/references/upstream-reconciliation.md` (the canonical §7 file —
don't duplicate it here).

## Resume with stale state

If `state.skill_version` is older than the current skill, warn and offer a clean
restart. Don't auto-migrate state across versions.

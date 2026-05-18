# Merge, validate, and the CLAUDE.md pointer

Detailed rules for Phase 7 (write & validate) and Phase 8 (CLAUDE.md
pointer). Read this when entering Phase 7.

## What Phase 7 writes

Phase 7 always writes **at least two files** for a non-trivial product:

1. `docs/UX.yaml` — the global UX contract.
2. One `docs/UX__<surface_id>.yaml` per confirmed surface in
   `state.defined_surfaces`.

If a surface's status is still `draft` at write time (the user
EXIT'd mid-deep-dive or explicitly chose "Skip for now"), do NOT write
that surface yaml. The inventory entry stays in `UX.yaml` with
`status: draft`, the coverage check will surface any PRD flow it was
supposed to cover, and `UX.yaml.metadata.status` is forced to `draft`.

## Merging into an existing UX.yaml + surface files

If `docs/UX.yaml` already exists:

- Load it as the baseline.
- Merge the session's confirmed answers on top:
  - **Keys present in both** — overwrite *only* if the user changed
    the value during this session. Otherwise keep the existing value.
  - **New keys** — add them.
  - **Keys the session would remove** — ask the user to confirm
    before deleting.

If `docs/UX__<surface_id>.yaml` already exists:

- Load it as the surface baseline.
- Merge the session's confirmed per-surface answers on top with the
  same overwrite/add/remove logic.

If the session's `surface_inventory` would **remove a surface** that
previously existed:

> "I'm about to remove surface `<surface_id>` from the inventory.
> This will delete `docs/UX__<surface_id>.yaml`. Proceed?"

Wait for explicit confirmation before deleting the file.

If the user manually edited an artifact between sessions and state
file disagrees on a specific key, surface the conflict — do NOT
silently pick:

> "Conflict on `UX.yaml.<key>`:
>   UX.yaml has: `<a>`
>   Interview state has: `<b>` (set at <timestamp>)
> Which should I keep?"

Always preserve **unrelated keys** in the existing YAML files even if
you don't recognise them. The validator's `extra="allow"` config means
custom keys are tolerated.

## Writing the files

For `UX.yaml`:

- Inline YAML comments on each top-level key (use `UX.schema.yaml` as a
  template).
- Updated `metadata.last_updated` (ISO-8601 UTC) and
  `metadata.session_id`.
- `metadata.status`:
  - Set to `"complete"` only when:
    1. all required fields are filled,
    2. the validator passes with `[OK]`,
    3. every entry in `PRD.use_cases.core_workflows` is referenced by
       at least one surface's `traces_prd_flows`.
  - Set to `"draft"` on early EXIT, when any required field is null,
    OR when any PRD flow is uncovered.
- `ux_warnings`: informational notes — uncovered PRD flows, low-
  confidence answers, merge conflicts, dropped optional themes
  (the now/skip/todo gates).

For each `UX__<surface_id>.yaml`:

- Inline comments on top-level keys.
- Updated metadata (`last_updated`, `session_id`).
- `metadata.status: complete` only when all required surface fields
  are filled (`surface_id`, `surface_type`, `layout`,
  `traces_prd_flows`) AND the user explicitly approved in theme 11
  step e.

## Running the validator

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/UX.yaml
```

The validator does three things in one pass:

1. Schema-validates `docs/UX.yaml`.
2. Schema-validates every `docs/UX__*.yaml` sibling.
3. Cross-reference check: every entry in
   `PRD.use_cases.core_workflows` (read from `docs/PRD.yaml` directly,
   not from state) must be referenced by at least one surface yaml's
   `traces_prd_flows`. Uncovered flows are surfaced in the output.

Exit codes:

| Code | Meaning | What the agent does |
|---|---|---|
| 0 (`[OK]`) | UX.yaml is complete, all surfaces valid, every PRD flow covered | ✓ Proceed to Phase 8. |
| 0 (`[DRAFT]`) | Draft — schema valid, possibly missing required fields or coverage | Inform user; proceed to Phase 8 (pointer still injected). |
| 1 (`[FAIL]`) | Schema invalid, OR `status: complete` but required fields missing, OR `status: complete` but coverage incomplete | Show field-level errors verbatim. Offer via `AskUserQuestion`: fix now, or accept `status: draft`. Re-run validation after re-entry. |
| 2 | Cannot read/parse one of the files | Surface to user (missing file, bad YAML, permission error). Do not retry silently. |
| 3 | Missing dependency | Validator prints `pip install` instructions. Ask the user to install and re-run; do NOT auto-install. |

**Downstream-agent contract**: downstream skills/agents MUST reject the
UX artifacts if `UX.yaml.metadata.status != "complete"` OR if the
validator exits non-zero. Document this in CLAUDE.md if the user asks.

## Coverage-check details

The coverage check reads `docs/PRD.yaml` and extracts
`use_cases.core_workflows` (or, in monorepo mode, the union across
products). For each flow string, it scans every surface yaml's
`traces_prd_flows` list. A flow is **covered** when at least one
surface lists it verbatim. Whitespace is stripped before comparison;
case is preserved.

If `docs/PRD.yaml` is missing, the validator continues without the
coverage check and prints `0 PRD core_workflow(s) discovered.` so the
user knows it wasn't run.

Any uncovered flow:

1. Appears in the validator's output ("PRD core_workflow(s) with no
   surface trace").
2. Must be written to `UX.yaml.ux_warnings` by the agent during Phase 7
   *before* validation runs (`"coverage: '<flow>' has no surface trace"`).
3. Forces `UX.yaml.metadata.status: draft`.

## CLAUDE.md pointer (Phase 8)

On validation exit code 0 (either `[OK]` or `[DRAFT]`), call
`set_claude_md_pointer.py` (bundled with this skill) to inject or
update the skill's bullet inside the shared `## SDLC Documents`
section of the project-root `CLAUDE.md`. The script is deterministic —
do not write to `CLAUDE.md` by hand.

**Bullet format** (exactly as produced by the pointer script):

```
- `docs/UX.yaml` (+ `docs/UX__<surface>.yaml`): UX surfaces, flows, components, and states. Load when working on UI implementation, flow wiring, or component contracts. Last updated by `sdlc-ux` on <ISO-8601 timestamp>.
```

**Rules** (mirrored from CLAUDE.md project conventions):

- If `CLAUDE.md` does not exist → create it containing only the
  `## SDLC Documents` heading and this bullet.
- If `CLAUDE.md` exists but the `## SDLC Documents` section does not →
  append a blank line, the heading, and this bullet at the end.
- If the section exists and a bullet that contains BOTH
  `` `docs/UX.yaml` `` AND `` `sdlc-ux` `` already exists → update the
  timestamp only; do not duplicate.
- If the section exists but no matching bullet → append the bullet as
  the last line of the section.
- Never reorder or modify the user's existing CLAUDE.md content.
- **Never touch other sdlc-* skills' bullets** (e.g. `sdlc-prd` and
  `sdlc-arch` bullets must be left exactly as they were).

Invoke as:

```bash
python "${CLAUDE_SKILL_DIR}/set_claude_md_pointer.py"
# add --dry-run to preview the diff without writing
```

## Closing the session

After Phase 8's CLAUDE.md write succeeds:

- Set `status: complete` in the state file.
- Keep the state file as an audit trail — do **not** delete it.
- Tell the user the workflow finished and where the artifacts live:
  *"UX spec written: `docs/UX.yaml` plus N surface files. CLAUDE.md
  pointer updated. The downstream `sdlc:api` skill can now consume
  these artifacts."*

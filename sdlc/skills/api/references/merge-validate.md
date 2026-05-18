# Merge, validate, and the CLAUDE.md pointer

Detailed rules for Phase 7 (write & validate) and Phase 8 (CLAUDE.md
pointer). Read this when entering Phase 7.

## What Phase 7 writes

Phase 7 always writes **at least one file** — `docs/API.yaml`. For
non-`none` APIs it also writes one
`docs/API__<resource_id>.yaml` per confirmed resource in
`state.defined_resources`.

If a resource's status is still `draft` at write time (the user
EXIT'd mid-deep-dive or explicitly chose "Skip for now"), do NOT
write that resource yaml. The inventory entry stays in `API.yaml`
with `status: draft`, the coverage checks will surface any PRD
feature / UX surface it was supposed to cover, and
`API.yaml.metadata.status` is forced to `draft`.

## Merging into an existing API.yaml + resource files

If `docs/API.yaml` already exists:

- Load it as the baseline.
- Merge the session's confirmed answers on top:
  - **Keys present in both** — overwrite *only* if the user changed
    the value during this session. Otherwise keep the existing value.
  - **New keys** — add them.
  - **Keys the session would remove** — ask the user to confirm
    before deleting.

If `docs/API__<resource_id>.yaml` already exists:

- Load it as the resource baseline.
- Merge the session's confirmed per-resource answers on top with the
  same overwrite/add/remove logic.

If the session's `resource_inventory` would **remove a resource** that
previously existed:

> "I'm about to remove resource `<resource_id>` from the inventory.
> This will delete `docs/API__<resource_id>.yaml`. Proceed?"

Wait for explicit confirmation before deleting the file.

If the user manually edited an artifact between sessions and the state
file disagrees on a specific key, surface the conflict — do NOT
silently pick:

> "Conflict on `API.yaml.<key>`:
>   API.yaml has: `<a>`
>   Interview state has: `<b>` (set at <timestamp>)
> Which should I keep?"

Always preserve **unrelated keys** in the existing YAML files even if
you don't recognise them. The validator's `extra="allow"` config means
custom keys are tolerated.

## Writing the files

For `API.yaml`:

- Inline YAML comments on each top-level key (use `API.schema.yaml` as
  a template).
- Updated `metadata.last_updated` (ISO-8601 UTC) and
  `metadata.session_id`.
- `metadata.status`:
  - Set to `"complete"` only when:
    1. all required fields are filled,
    2. the validator passes with `[OK]`,
    3. feature coverage passes,
    4. surface coverage passes,
    5. entity-link check passes
       (or the validator skipped these because `api_kind: none`).
  - Set to `"draft"` on early EXIT, when any required field is null,
    OR when any check fails.
- `api_warnings`: informational notes — uncovered PRD features,
  uncovered UX surfaces, unresolved primary_entity references,
  low-confidence answers, merge conflicts, dropped optional themes
  (the now/skip/todo gates).

For each `API__<resource_id>.yaml`:

- Inline comments on top-level keys.
- Updated metadata (`last_updated`, `session_id`).
- `metadata.status: complete` only when all required resource fields
  are filled (`resource_id`, `base_path`, `traces_prd_features`,
  `traces_ux_surfaces`, `endpoints` — each endpoint with
  `operation_id`, `method`, `path`, `summary`, `responses`) AND the
  user explicitly approved in theme 10 step e.

## Running the validator

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/API.yaml
```

The validator does five things in one pass:

1. Schema-validates `docs/API.yaml`.
2. Schema-validates every `docs/API__*.yaml` sibling.
3. **Feature coverage**: every entry in
   `PRD.functional_requirements.must_have_features` (parsed as `F-NNN`)
   appears in at least one resource's `traces_prd_features`, OR is
   listed in `API.yaml.non_api_features`.
4. **Surface coverage**: every data-bearing UX surface appears in at
   least one resource's `traces_ux_surfaces`. A surface is
   "data-bearing" if its `surface_type` is in
   `{screen, page, tab, modal, dialog, drawer, panel, cli_command,
   flow_step, other}` (types like `toast`, `empty_state`, `overlay`
   are display-only and ignored).
5. **Entity-link check**: every `primary_entity` value (whether on
   a resource_inventory item or in a per-resource yaml) exists in
   `DATA-MODEL.yaml.entities`. Skipped (with a printed warning) if
   `DATA-MODEL.yaml` is absent.

All three coverage / link checks are skipped when `api_kind: none`.

Exit codes:

| Code | Meaning | What the agent does |
|---|---|---|
| 0 (`[OK]`) | API.yaml is complete, all resources valid, all enabled checks pass | ✓ Proceed to Phase 8. |
| 0 (`[DRAFT]`) | Draft — schema valid, possibly missing required fields or coverage | Inform user; proceed to Phase 8 (pointer still injected). |
| 1 (`[FAIL]`) | Schema invalid, OR `status: complete` but required fields missing, OR `status: complete` but a check failed | Show field-level errors verbatim. Offer via `AskUserQuestion`: fix now, or accept `status: draft`. Re-run validation after re-entry. |
| 2 | Cannot read/parse one of the files | Surface to user (missing file, bad YAML, permission error). Do not retry silently. |
| 3 | Missing dependency | Validator prints `pip install` instructions. Ask the user to install and re-run; do NOT auto-install. |

**Downstream-agent contract**: downstream skills/agents MUST reject
the API artifacts if `API.yaml.metadata.status != "complete"` OR if
the validator exits non-zero. Document this in CLAUDE.md if the user
asks.

## Coverage-check details

### Feature coverage

The validator reads `docs/PRD.yaml`, extracts every
`functional_requirements.must_have_features` entry, and parses out
the `F-NNN` prefix (case-insensitive). A feature is **covered** when
at least one resource lists the `F-NNN` (verbatim, ignoring
description text) in its `traces_prd_features` list OR when the
F-NNN is listed in `API.yaml.non_api_features`.

If `docs/PRD.yaml` is missing, the validator continues without the
feature coverage check (prints a warning).

Uncovered features:

1. Appear in the validator's output ("PRD F-NNN feature(s) with no
   resource trace").
2. Should be written to `API.yaml.api_warnings` by the agent during
   Phase 7 *before* validation runs
   (`"coverage: feature '<F-NNN>' has no resource trace"`).
3. Force `API.yaml.metadata.status: draft`.

### Surface coverage

The validator walks `docs/UX__*.yaml` files. For each surface, it
checks `surface_type`:

- Data-bearing (covered by this check):
  `screen`, `page`, `tab`, `modal`, `dialog`, `drawer`, `panel`,
  `cli_command`, `flow_step`, `other`.
- Display-only (ignored by this check):
  `toast`, `empty_state`, `overlay`.

A data-bearing surface is **covered** when at least one resource
lists its `surface_id` in `traces_ux_surfaces`.

Uncovered surfaces follow the same warnings + draft-forcing rules as
features.

### Entity-link check

For every resource (in the inventory and in each per-resource yaml),
the validator checks that `primary_entity` exists in
`DATA-MODEL.yaml.entities`. The check accepts two DATA shapes:

```yaml
# Shape A — map keyed by entity name
entities:
  User: { ... }
  Order: { ... }

# Shape B — list with `name` per item
entities:
  - name: User
  - name: Order
```

`primary_entity: null` is always valid (cross-cutting resources like
`/search` or `/health`).

If `DATA-MODEL.yaml` is missing, the entity-link check is skipped
with a printed warning. The agent should refuse to set
`metadata.status: complete` in that case unless the user has been
warned and explicitly accepts the gap.

## CLAUDE.md pointer (Phase 8)

On validation exit code 0 (either `[OK]` or `[DRAFT]`), call
`set_claude_md_pointer.py` (bundled with this skill) to inject or
update the skill's bullet inside the shared `## SDLC Documents`
section of the project-root `CLAUDE.md`. The script is deterministic —
do not write to `CLAUDE.md` by hand.

**Bullet format** (exactly as produced by the pointer script):

```
- `docs/API.yaml` (+ `docs/API__<resource>.yaml`): API contract — endpoints, request/response DTOs (projecting DATA entities), auth, errors, events. Load when implementing endpoints, clients, or SDKs. Last updated by `sdlc-api` on <ISO-8601 timestamp>.
```

**Rules** (mirrored from CLAUDE.md project conventions):

- If `CLAUDE.md` does not exist → create it containing only the
  `## SDLC Documents` heading and this bullet.
- If `CLAUDE.md` exists but the `## SDLC Documents` section does not →
  append a blank line, the heading, and this bullet at the end.
- If the section exists and a bullet that contains BOTH
  `` `docs/API.yaml` `` AND `` `sdlc-api` `` already exists → update
  the timestamp only; do not duplicate.
- If the section exists but no matching bullet → append the bullet as
  the last line of the section.
- Never reorder or modify the user's existing CLAUDE.md content.
- **Never touch other sdlc-* skills' bullets** (e.g. `sdlc-prd`,
  `sdlc-ux`, and `sdlc-data` bullets must be left exactly as they
  were).

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
  *"API spec written: `docs/API.yaml` plus N resource files. CLAUDE.md
  pointer updated. The downstream `sdlc:arch` skill can now consume
  these artifacts."*

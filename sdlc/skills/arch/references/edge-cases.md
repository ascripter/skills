# Edge cases

Unusual situations the skill may encounter, and how to handle them.

## Legacy state from old `architecture` skill

If `.architecture-skill/state.yaml` is present, ignore it. Print a
one-time advisory:

```
[info] Found legacy state at .architecture-skill/state.yaml — this
file is no longer used. You may safely delete .architecture-skill/.
```

Do NOT auto-migrate state contents. The user should re-bootstrap from
the current `docs/PRD.yaml` by running `/sdlc-arch` (no args).

## Project-root `PRD.yaml` exists but no `docs/PRD.yaml`

Emit `MSG_PRD_MISSING` and abort. Do not auto-migrate the file. The
user should run the upgraded `/sdlc-prd` which writes `docs/PRD.yaml`.

```
No docs/PRD.yaml found. Call /sdlc-prd first to define product
requirements.
```

## `/sdlc-arch -d` without prior `docs/ARCH.yaml`

All dependency-family invocations are classified as sub-node for
preflight purposes. Step 0.5 will fire `MSG_SUBNODE_MISSING(docs/ARCH.yaml)`
and abort. The user must run `/sdlc-arch` (no args) first to bootstrap
the root architecture.

## `docs/UX.yaml` or `docs/DATA.yaml` is empty

Passes the existence check in Step 0.5. Schema validation for those
files will be added when `/sdlc-ux` and `/sdlc-data` ship.

## Stale `.tmp` files in `docs/`

Left behind by a crashed atomic write. Safe to delete manually. The
next successful write will overwrite them.

## Multiple discovered architecture sources that disagree

If bootstrap (Step 1b) finds e.g. a `docs/ARCH.yaml` *and* a project-root
`ARCHITECTURE.md` that list different containers, surface the conflict
explicitly using the `conflict-resolution` template from
`references/prompt-templates.yaml`. Ask the user which source wins
**before** mutating state.

## State file says `mode: CREATE` but node already exists in graph

This can happen if a prior run wrote the state file but the artifact
write failed. On resume, detect the inconsistency and switch to EDIT
mode automatically, noting the discrepancy to the user:

```
[info] State says CREATE but <node-path> already has content.
Switching to EDIT mode.
```

## Existing artifact has schema violations

Detected during Step 1b ingestion. Report the violation to the user
but do not block ingestion — old content is read tolerantly. Offer to
fix the violation in the current session by running the corrected
interview at that node's level.

## `validate_artifacts.py` exit 2 during Step 0.5 (ARCH.yaml sub-node check)

Missing `pyyaml` or `jsonschema`. Emit the soft-fail warning and
continue — this matches Step 4b's soft-fail policy:

```
[warning] validate_artifacts: missing dependency. ARCH.yaml validation
skipped. Continuing without schema check.
```

Do NOT abort on exit 2 during the ARCH.yaml sub-node check.

## User invokes `/sdlc-arch` in a fresh repo with no `docs/` directory

`Path("docs/PRD.yaml").exists()` returns false. Emit `MSG_PRD_MISSING`
and abort. The skill does not auto-create `docs/`.

# Bootstrap: Step 1b details

This reference covers the blank-start block, user-response handling, and
edge cases for Step 1b (bootstrap when no usable state exists).

## Blank-start block

Emit verbatim when no usable architecture content is found:

```
No architecture files found. Expected:
  docs/ARCH.yaml
  docs/ARCH__*.yaml

Options:
  RETRY  — re-scan after you add files
  ASK    — start a fresh interview
  EXIT   — quit without changes
```

## Response handling

| Input | Action |
|---|---|
| `RETRY` | Re-run Step 1b from the top. |
| `ASK` | Proceed to Step 3 at the root/context level (CREATE mode). |
| `EXIT` or `QUIT` | Exit cleanly with no state change. |
| Anything else | Emit `Not understood. EXIT triggered.` and stop. |

## Discovery search order

Search these locations in order, stopping when usable matches are found:

1. `docs/` — primary location for sdlc-arch artifacts.
2. `./` — project root (e.g. `ARCHITECTURE.yaml`, `ARCH.yaml`).
3. `doc/`, `project/`, `orga/`, `meta/` — common alternative doc dirs.

Look for files whose names or contents indicate architecture, spec, or
design intent (keywords: `container`, `component`, `c4-level`,
`architecture`, `system`, `service`, etc.).

## Conflict handling

If multiple discovered sources disagree (e.g. one lists 4 containers,
another lists 7), surface the conflict explicitly using the
`conflict-resolution` template from `references/prompt-templates.yaml`.
Ask the user which source wins **before** mutating state. Never silently
average or pick one without asking.

## Legacy state from old `architecture` skill

If `.architecture-skill/state.yaml` exists, ignore it for bootstrap
purposes. Print a one-time advisory (see `references/preflight.md`) and
continue as if no state were present. Do NOT auto-migrate: schemas match
but the PRD may be newer, and the user may want to re-bootstrap from
scratch.

## Schema violations in ingested docs

Old artifacts read during bootstrap are read tolerantly. A schema
violation in legacy content is reported to the user but does not block
ingestion. Validation (Step 4b) only runs on writes.

## Initial write on successful bootstrap

After deriving the knowledge graph and confirming edges with the user,
write:

- `docs/ARCH.yaml` (root context artifact, `c4-level: context`).
- `.claude/skills-state/sdlc-arch.state.yaml` (initial state, `mode: CREATE`).

Validate both immediately via Step 4b.

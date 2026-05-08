# Preflight: required upstream artifacts

This reference contains the full abort-message catalog and exit-code
mapping for Step 0.5. Only the four most common messages are inlined in
SKILL.md; consult this file for the complete set.

## Invocation classification

| Invocation form | Kind |
|---|---|
| `/sdlc-arch` (no args) | root |
| `/sdlc-arch <container>` | sub-node |
| `/sdlc-arch <container> <component>` | sub-node |
| `/sdlc-arch <container> <component> <code>` | sub-node |
| `/sdlc-arch -d` | sub-node (requires ARCH.yaml) |
| `/sdlc-arch -d <container>` | sub-node |
| `/sdlc-arch -d [<container>] --auto` | sub-node |

All dependency-family invocations are sub-node: `-d` without a prior
`docs/ARCH.yaml` is meaningless and should be blocked.

## Always-required: docs/PRD.yaml checks

### sdlc-prd validate_prd.py exit codes

| Exit | Meaning |
|---|---|
| 0 | Valid — proceed |
| 1 | Schema invalid |
| 2 | File unreadable / YAML parse error |
| 3 | Missing dependency (pydantic v2 or pyyaml) |

### Abort messages

**PRD missing (no file):**
```
No docs/PRD.yaml found. Call /sdlc-prd first to define product
requirements.
```

**PRD invalid schema (exit 1):**
```
docs/PRD.yaml doesn't validate the schema. Run /sdlc-prd to fix.
(validator output below)
<stderr from validate_prd.py>
```

**PRD unreadable / parse error (exit 2):**
```
docs/PRD.yaml exists but could not be read or parsed.
Run /sdlc-prd to recreate it.
(validator output below)
<stderr from validate_prd.py>
```

**PRD validation dependencies missing (exit 3):**
```
PRD validation requires pydantic v2 and pyyaml. Install with:
  pip install 'pydantic>=2' pyyaml
Re-run /sdlc-arch after installing.
```

## Sub-node only: sibling artifact checks

`docs/UX.yaml` and `docs/DATA.yaml` are checked for existence only —
their schemas don't yet exist. An empty file passes.

### validate_artifacts.py exit codes (for ARCH.yaml check)

| Exit | Meaning |
|---|---|
| 0 | Valid — proceed |
| 1 | Schema violation |
| 2 | Missing dependency (pyyaml or jsonschema) — warn and continue |
| 3 | Bad invocation (internal error) |

### Abort messages

**Sibling artifact missing:**
```
Sub-node invocation requires upstream SDLC artifacts. Missing: <path>
Complete upstream skills first:
  docs/PRD.yaml  -> /sdlc-prd
  docs/ARCH.yaml -> /sdlc-arch  (root invocation, no arguments)
  docs/UX.yaml   -> /sdlc-ux    (skill not yet implemented)
  docs/DATA.yaml -> /sdlc-data  (skill not yet implemented)
```

**ARCH.yaml invalid schema (exit 1):**
```
docs/ARCH.yaml doesn't validate the architecture schema.
Run /sdlc-arch (root, no arguments) to fix it.
(validator output below)
<stderr from validate_artifacts.py>
```

**ARCH.yaml validation deps missing (exit 2):**
```
[warning] validate_artifacts: missing dependency. ARCH.yaml validation
skipped. Continuing without schema check.
```
(do NOT abort — soft-fail matches Step 4b policy)

**ARCH.yaml validator bad invocation (exit 3):**
```
Internal error: validate_artifacts.py rejected its own invocation.
This is a skill bug — please report.
```

## Edge cases

**project-root `PRD.yaml` exists but no `docs/PRD.yaml`:**
Emit `MSG_PRD_MISSING` and abort. Do NOT auto-migrate. The user should
run the upgraded `/sdlc-prd` which will write `docs/PRD.yaml`.

**`docs/UX.yaml` or `docs/DATA.yaml` is empty:**
Passes the existence check. Schema validation will be added when
`/sdlc-ux` and `/sdlc-data` ship.

**Legacy state at `.architecture-skill/state.yaml`:**
Ignored. The new skill reads only `.claude/skills-state/sdlc-arch.state.yaml`.
If the legacy file is detected, print a one-time advisory:
```
[info] Found legacy state at .architecture-skill/state.yaml — this
file is no longer used. You may safely delete .architecture-skill/.
```
Do NOT auto-migrate state contents. The user should re-bootstrap from
the current `docs/PRD.yaml`.

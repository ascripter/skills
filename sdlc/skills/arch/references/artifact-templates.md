# Artifact templates

Per-tier YAML templates for sdlc-arch output files. Use these as
authoring crib sheets. Authoritative schemas live in
`references/artifact-schemas/*.schema.json` and are enforced at Step 4b.

All output files are **pure YAML** — no markdown prose, no commentary.
Every artifact carries `updated-at:` (ISO 8601, UTC) bumped on every
write and `updated-by: sdlc-arch`.

## Root / context — `docs/ARCH.yaml`

```yaml
doc-kind: architecture
c4-level: context
node-path: []
updated-by: sdlc-arch
updated-at: <ISO8601>
system:
  name:
  purpose:
boundaries:
  in-scope: []
  out-of-scope: []
actors: []
external-systems: []
quality-attributes: []
deployment-topology:
data-residency:
secrets-management:
sla-targets: []
architecture-pattern:
containers: []
```

## Container — `docs/ARCH__<container>.yaml`

```yaml
doc-kind: architecture
c4-level: container
container:
  canonical:
  aliases: []
node-path: [<container>]
updated-by: sdlc-arch
updated-at: <ISO8601>
overview:
responsibilities: []
technology:
persistence:
failure-modes: []
scaling:
security:
observability:
ownership:
components: []
```

## Component + code — `docs/ARCH__<container>__<component>.yaml`

```yaml
doc-kind: architecture
c4-level: component
container:
  canonical:
  aliases: []
component:
  canonical:
  aliases: []
node-path: [<container>, <component>]
updated-by: sdlc-arch
updated-at: <ISO8601>
overview:
responsibilities: []
failure-modes: []
code:
  - canonical:
    aliases: []
    kind: interface | class | function | handler | job | workflow | schema | event | api-endpoint | query | command
    summary:
    inputs: []
    outputs: []
    invariants: []
    errors: []
    side-effects: []
    observability: []
    auth:
    versioning:
    notes:
    # split-file: <basename>.yaml   # set when this code unit is split out
```

`status` is **not** stored on `code:` entries — node status lives
exclusively in `.claude/skills-state/sdlc-arch.state.yaml`. Artifact
files hold prose and structural data only.

## Split code unit (optional) — `docs/ARCH__<container>__<component>__<code>.yaml`

Only created when a code unit is large enough that keeping it in the
component file would make that file unwieldy (see size thresholds below).

```yaml
doc-kind: architecture
c4-level: code
container:
  canonical:
  aliases: []
component:
  canonical:
  aliases: []
code:
  canonical:
  aliases: []
  kind: <one of the kinds above>
node-path: [<container>, <component>, <code>]
updated-by: sdlc-arch
updated-at: <ISO8601>
summary:
inputs: []
outputs: []
invariants: []
errors: []
side-effects: []
observability: []
auth:
versioning:
notes:
```

When a code unit is split out, the parent component's `code:` array
keeps only a stub: `canonical`, `aliases`, `kind`, and a `split-file:`
field whose value is the basename of the split file. The full prose
lives in the split file.

## Soft cap: when to split

The skill warns when a component artifact exceeds **40 KB** *or*
**800 lines** (whichever first). It does not auto-split — it suggests
the user pick which `code:` entry to extract, then performs the move
on the next write of that component. Splitting is opt-in per code unit.

## Output mapping rules

- Root containers → entries in `containers[]` (each with `canonical`
  and `aliases`).
- Container components → entries in `components[]` (each with
  `canonical` and `aliases`).
- Component code units → entries in `code[]` of the component file,
  *or* a `split-file:` stub plus a separate code-level file when the
  unit is split out.
- `node-path` always uses canonical kebab-case identifiers.
- The component file name joins container and component canonical
  names with double underscore (`__`); a split code file appends
  another `__<code>`.
- Artifact files contain prose-style content only. All typed
  relationships live as edges on the source node in
  `.claude/skills-state/sdlc-arch.state.yaml`. Do not add a
  `dependencies` field to artifact files.

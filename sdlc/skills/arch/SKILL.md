---
name: arch
description: >
  Manual architecture-authoring skill for C4-style spec-driven
  development, downstream of sdlc-prd. Use /sdlc:arch [container]
  [component] [code] to create, refine, or resume machine-readable
  architecture specs and state for the current repository. Use
  /sdlc:arch -d [container] [--auto] to re-derive typed dependency
  edges from existing artifacts. Reads docs/PRD.yaml and (for sub-node
  invocations) docs/ARCH.yaml, docs/UX.yaml, docs/DATA.yaml as
  preconditions.
user-invocable: true
disable-model-invocation: true
model: opusplan
effort: xhigh
allowed-tools: Read, Write(docs/ARCH.yaml), Write(docs/ARCH__*.yaml), Write(.claude/skills-state/sdlc-arch.state.yaml), Write(.claude/skills-state/sdlc-arch.derivation-report-*.yaml), Bash, Glob, Grep
---

# sdlc-arch

A manual, repo-local skill for capturing and maintaining a C4-style
architecture description as scoped, schema-bound YAML files plus a
persistent knowledge graph that survives across sessions.

## Why this exists

Architecture docs drift, balloon into prose, or never get written. This
skill produces small YAML artifacts (one per container or
container-component pair, plus optional per-code-unit splits), a typed
dependency graph, and a state file that tracks each node's
`defined | wip | complete` status. Future agent runs read these
artifacts directly — they should not have to reconstruct knowledge from
conversation history.

The skill is **manual-only** (`disable-model-invocation: true`). It will
only run when the user explicitly types `/sdlc:arch`.

The skill is **downstream of sdlc-prd**: it requires a validated
`docs/PRD.yaml` before running (Step 0.5 below). The only other
host-project assumption is a writable `docs/` directory and an optional
Python 3 + pyyaml + jsonschema for post-write artifact validation.

## Invocation contract

Two invocation families:

**Interview family** — drive an interview to author or refine a node.
`$ARGUMENTS` is a whitespace-separated list of up to three positional
node tokens:

| Token count | Active level                                  |
|-------------|-----------------------------------------------|
| 0           | root/context                                  |
| 1           | container                                     |
| 2           | container, component                          |
| 3           | container, component, code                    |
| > 3         | invalid — abort                               |

**Dependency-derivation family** — re-derive edges from existing
artifacts. Triggered by the `-d` or `--dependencies` flag as the first
token. Optional second token scopes derivation to a single container
subtree. Optional `--auto` flag skips the confirmation prompt:

| Form                                         | Scope                                |
|----------------------------------------------|--------------------------------------|
| `/sdlc:arch -d`                              | whole graph, interactive             |
| `/sdlc:arch -d <container>`                  | container subtree, interactive       |
| `/sdlc:arch -d --auto`                       | whole graph, no prompt; emit report  |
| `/sdlc:arch -d <container> --auto`           | container subtree, no prompt; report |

### Step 0 — Echo signature, validate

Always emit the signature block exactly once. Each line is a bullet:

```
- /sdlc:arch
- /sdlc:arch <container>
- /sdlc:arch <container> <component>
- /sdlc:arch <container> <component> <code>
- /sdlc:arch -d
- /sdlc:arch -d <container>
- /sdlc:arch -d [<container>] --auto
```

If invocation is **valid**, replace the leading `-` of the matching
line with `→` and bold that whole line. Continue with Step 0.5.

If invocation is **invalid**, prepend a single header line above the
unmodified signature block and stop:

```
✗ Wrong invocation: <reason>
```

Validation rules:

- Interview family: 0–3 non-flag arguments.
- Dependency family: first token is `-d` or `--dependencies`; optional
  second token is a container name; optional trailing `--auto`.
- Each non-flag argument matches `^[a-z][a-z0-9]*(-[a-z0-9]+)*$` *after*
  alias normalization (see `## Alias normalization`). Inputs in other
  forms (e.g. `WebFrontend`, `web_frontend`) are normalized first; the
  normalized form is used for the rest of the run.
- Common reasons: `more than three positional arguments`,
  `name does not match pattern`, `unknown flag`.

## Processing flow

### Step 0.5 — Preflight: required upstream artifacts

**Invocation kind**:
- *Root*: interview-family with zero positional args.
- *Sub-node*: interview-family with 1+ args, OR any dependency-family
  invocation (including bare `/sdlc:arch -d` — that needs
  `docs/ARCH.yaml` to be meaningful).

**Always required** — run for every invocation:

1. If `docs/PRD.yaml` does not exist → abort:
   ```
   No docs/PRD.yaml found. Call /sdlc:prd first to define product
   requirements.
   ```
2. Run `python "${CLAUDE_SKILL_DIR}/../prd/validate_prd.py" --path docs/PRD.yaml`:
   - exit 0 → proceed.
   - exit 1 → abort: `docs/PRD.yaml doesn't validate the schema. Run /sdlc:prd to fix.` (include validator stderr).
   - exit 2 → abort: `docs/PRD.yaml exists but could not be read or parsed. Run /sdlc:prd to recreate it.`
   - exit 3 → abort: `PRD validation requires pydantic v2 and pyyaml. Install them, then retry.`

**Additional checks for sub-node invocations only**:

3. For each of `docs/ARCH.yaml`, `docs/UX.yaml`, `docs/DATA.yaml`: if
   missing → abort:
   ```
   Sub-node invocation requires upstream SDLC artifacts. Missing: <path>
   Complete upstream skills first:
     docs/PRD.yaml  -> /sdlc:prd
     docs/ARCH.yaml -> /sdlc:arch  (root invocation, no arguments)
     docs/UX.yaml   -> /sdlc-ux    (skill not yet implemented)
     docs/DATA.yaml -> /sdlc-data  (skill not yet implemented)
   ```
4. Schema-validate `docs/ARCH.yaml` via
   `python "${CLAUDE_SKILL_DIR}/scripts/validate_artifacts.py" docs/ARCH.yaml`:
   - exit 0 → proceed.
   - exit 1 → abort: `docs/ARCH.yaml doesn't validate the architecture schema. Run /sdlc:arch (no arguments) to fix it.`
   - exit 2 → warn "validation skipped (deps missing)" and continue.

Note: `docs/UX.yaml` and `docs/DATA.yaml` are checked for existence
only — their schemas don't yet exist.

Full exit-code mapping, all abort messages, and edge cases →
`references/preflight.md`.

### Step 1 — Load context

1. Read `CLAUDE.md` (if present).
2. Read every file under `.claude/rules/` that has **no YAML
   frontmatter**. These are general rule files that inform tone and
   conventions; they are not architecture artifacts.
3. Try to read `.claude/skills-state/sdlc-arch.state.yaml`.

If the state file exists and is non-empty, use it as the source of truth
for the architecture knowledge graph and proceed to Step 2.

### Step 1b — Bootstrap (only if no usable state)

1. Search `docs/` first, then the fallbacks `./`, `doc/`, `project/`,
   `orga/`, `meta/`. Look for files whose names or contents indicate
   architecture, spec, or design intent.
2. If multiple sources disagree, surface the conflict and ask the user
   which source wins **before** mutating state. Use the
   `conflict-resolution` template from `references/prompt-templates.yaml`.
3. If usable content is found, derive the knowledge graph (containers,
   components, code units, aliases, per-node `status`) only as deeply
   as the evidence supports. Normalize all discovered names to
   kebab-case canonicals using the rule in `## Alias normalization`.
4. Run the **edge-derivation procedure** (Step 3-alt) on the newly
   built graph and present derived edges for confirmation before writing.
5. Write the initial `docs/ARCH.yaml` and
   `.claude/skills-state/sdlc-arch.state.yaml`.
6. If no usable content is found, emit the **blank-start block** and
   handle user response (`RETRY`, `ASK`, `EXIT`).

Full blank-start block text, response handling, and edge cases →
`references/bootstrap.md`.

### Step 2 — Resolve the active node-path

Build the active node-path from the validated arguments after alias
resolution (see `## Alias normalization`). Aliases must always resolve
to the canonical (kebab-case) name stored in the graph; **never store
an alias as a path component**.

- Full node-path exists in the graph → **EDIT mode**. Print a one-line
  edit confirmation naming the canonical path.
- Leaf is missing but its parent exists → **CREATE mode**. Print a
  one-line create confirmation naming the canonical path.
- Both leaf and parent are missing → emit a clear error that names the
  missing parent and stop.

### Step 2b — Load scoped artifacts

Read only the YAML artifacts on the path from root to the active node.
Compute paths from canonical names using the path-derivation rule in
`## State schema`:

- Always: `docs/ARCH.yaml`
- Container level and below: `docs/ARCH__<container>.yaml`
- Component and code level: `docs/ARCH__<container>__<component>.yaml`
- If a code unit has been split out (parent stub has `split-file:`):
  also load `docs/ARCH__<container>__<component>__<code>.yaml`.

Do not load unrelated container or component files. Lean context is
the point — siblings can drift from each other and that is fine.

### Step 3 — CREATE or EDIT

Drive an interview using the inventory for the active node level.
Load only the relevant prompt template
(`references/prompt-templates.yaml`), the relevant question inventory
(`references/question-inventories.yaml`), and the matching taxonomy
entry — not every reference file.

The interview never asks the user to enumerate edges. Edges are always
**derived then confirmed** at the end of the interview (see Step 3c).

#### CREATE
- Identify the mandatory questions for this node level.
- Ask only those still unanswered, in batches of 3–5. Number them
  consecutively for display, even if the underlying inventory order
  has gaps from skipped questions.
- After each batch, evaluate sufficiency. If gaps remain, ask targeted
  follow-ups until each mandatory question is resolved.
- When every mandatory question is answered, proceed to Step 3c, then
  mark the node `complete`.

#### EDIT
- Reflect existing knowledge for the active node back to the user first.
- Ask which parts are still valid, obsolete, or partly valid. Number
  the questions consecutively.
- Preserve confirmed-valid content byte-identically. Discard obsolete
  content. Continue as in CREATE for any remaining gaps.
- After content is settled, proceed to Step 3c.

#### Status semantics
- `defined` — node exists by name only; no clarified content.
- `wip` — node has partial clarified content; interview incomplete.
- `complete` — every required question for the node is answered
  **and** the user has confirmed the derived edge set.

#### Abort semantics
At any point during Step 3 the user may type `EXIT` or `QUIT`.

- Before any clarification is given for the active node → save with
  `defined`.
- After some clarification but before the interview is complete → save
  with `wip` and write/update the scoped YAML artifact with the partial
  content collected so far. Skip Step 3c.

### Step 3c — Edge derivation and confirmation

After mandatory questions are settled (CREATE) or content is reconciled
(EDIT), derive edges for the active node and present them for
confirmation.

1. Collect candidate edges by scanning the active node's freshly-written
   content plus the artifacts already loaded in Step 2b. For each free-text
   field (`overview`, `responsibilities`, code `summary` / `notes`):
   - Match canonical names and aliases of other graph nodes (apply the
     normalization rule in `## Alias normalization` to both the
     scanned token and the candidate canonical).
   - Classify the relationship by surrounding verbs/keywords using
     `references/edge-vocabulary.yaml`. That file lists exemplar verbs
     and disambiguators per edge type.
2. Resolve each candidate's `to` to the most specific existing graph
   node (see **Endpoint level rules**).
3. Diff candidates against the active node's existing `edges:` list.
4. Present the diff as a numbered list, e.g.:

   ```
   I derived these edges for api-gateway:
     1. calls            → user-service/auth-controller
     2. reads            → redis-cache
     3. depends_on       → config-store
     4. publishes        → audit-log

   Confirm all, or edit:
     - "remove 2, 4"
     - "add: subscribes_to billing-events"
     - "retype 3 as calls"
   ```

5. Apply the user's response. Empty input, `yes`, or `confirm` accepts
   all derived edges as-is.
6. After confirmation, run the **decomposition-refinement check**: if
   the active node was just newly decomposed (children added), scan
   inbound edges across the graph that point at the active node's
   parent and ask whether each should be re-pointed at one of the new
   children. Batch in groups of 3–5.

### Step 3-alt — `-d` / `--dependencies` mode

This mode skips the interview entirely.

1. Determine scope: whole graph if no container token; otherwise the
   subtree rooted at the named container.
2. For every node in scope, run candidate-edge collection and resolution
   from Step 3c (1–2).
3. Diff against currently stored edges in the affected nodes.
4. If `--auto`:
   - Write all derived changes immediately.
   - Emit a report file at
     `.claude/skills-state/sdlc-arch.derivation-report-<ISO8601>.yaml`
     listing adds, removes, and retypes per node.
5. Otherwise:
   - Present the diff per node, in the format from Step 3c (4).
   - User confirms or edits per node.
   - Write only confirmed changes.
6. Skip Step 4 status updates — `-d` mode never changes node `status`,
   only edges.

### Step 4 — Write (atomic)

1. Compute the target path(s) for the active node from the
   path-derivation rule (`## State schema`).
2. Render the new content for each target file in memory.
3. **Atomic write** — for every target file, including
   `.claude/skills-state/sdlc-arch.state.yaml`:
   - Write the new content to `<path>.tmp` in the same directory.
   - Rename `<path>.tmp` over `<path>` (`os.replace` semantics —
     atomic on every modern filesystem).
   - On any error mid-write, the original file is intact. The `.tmp`
     file may be left behind for inspection; the next write overwrites
     it.
4. Update `.claude/skills-state/sdlc-arch.state.yaml`:
   - bump `updated-at` (ISO 8601, UTC)
   - update `mode` and `current-pointer` (canonical path, no aliases)
   - update the `status` of touched nodes
5. **Untouched nodes must remain byte-identical** in both
   `.claude/skills-state/sdlc-arch.state.yaml` and any scoped
   artifact. Never rewrite content you have not touched.
6. Confirm to the user with the file path(s) written and the new node
   status.

### Step 4b — Validate

After writing, validate every file touched in Step 4 against the JSON
Schema bundled with the skill:

```
python "${CLAUDE_SKILL_DIR}/scripts/validate_artifacts.py" <path-1> [<path-2> ...]
```

The validator dispatches on filename (`sdlc-arch.state.yaml`) or
`c4-level` (`context | container | component | code`) to the matching
schema in `references/artifact-schemas/`.

- Exit 0 → success. Confirm to the user.
- Exit 1 → schema violation. Roll back: replace the just-written file
  with the pre-write content saved before Step 4 (skill keeps an
  in-memory copy of every replaced file for the duration of the
  write). Report the violations to the user and stop without updating
  state.
- Exit 2 → Python or `pyyaml` / `jsonschema` not available. Emit a
  one-line warning that validation was skipped and continue without
  rolling back. Validation is a safety net, not a hard requirement.

The validator also supports `--self-test` to validate bundled minimal
fixtures — useful when checking the schemas themselves are healthy.

## State schema

File: `.claude/skills-state/sdlc-arch.state.yaml`

The state file is a versioned YAML mapping. Top-level fields: `version`
(`"1"`), `mode` (`CREATE | EDIT`), `current-pointer` (canonical path
string), `updated-at` (ISO 8601 UTC), and a `graph.root` node tree
where each node carries `kind`, `status` (`defined | wip | complete`),
`edges:` (outbound typed edges), and `children:` (recursive).

Authoritative structure: `references/artifact-schemas/state.schema.json`.

State rules:

- Every `current-pointer` and `canonical` value uses canonical
  identifiers — never aliases. Canonicals are kebab-case
  (`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`).
- Aliases live alongside canonical names but never replace them in path
  positions.
- Untouched nodes stay unchanged on every write.
- Each node owns its outbound edges in its own `edges:` list. The `from`
  side is implicit; only `type`, `to`, and optional `note` are stored.
- An inbound view ("what points at me?") is computed on demand by
  walking the graph and filtering by `to`.

### Path derivation

The on-disk path of a node's owning artifact is **computed**, not
stored. The skill never persists `file:` fields on nodes:

| Node                                  | Path                                                       |
|---------------------------------------|------------------------------------------------------------|
| root (context)                        | `docs/ARCH.yaml`                                           |
| `<c>`                                 | `docs/ARCH__<c>.yaml`                                      |
| `<c>/<cmp>`                           | `docs/ARCH__<c>__<cmp>.yaml`                               |
| `<c>/<cmp>/<code>` (default)          | same file as `<c>/<cmp>` — entry inside its `code:` array |
| `<c>/<cmp>/<code>` (split, opt-in)    | `docs/ARCH__<c>__<cmp>__<code>.yaml`                       |

Joining a multi-part name uses double underscore (`__`) as the
delimiter; each part is the canonical kebab-case identifier as stored.

### Edge type vocabulary

Seven types: `depends_on`, `calls`, `reads`, `writes`, `publishes`,
`subscribes_to`, `implements`. Each produces a distinct codegen
implication. Do not extend this list without an architectural reason.

Hierarchical relationships (`contains`, `owns`) are **not** edges —
they are encoded by the `children:` structure of the graph.

Full verb-to-type mapping and disambiguators: `references/edge-vocabulary.yaml`.

### Endpoint level rules

- Edge endpoints (`to`) and the implicit `from` may only resolve to a
  container, component, or code node. The root/context node is never
  an edge endpoint. Externals interact via `actors:` in the context
  artifact.
- An edge always points at the **most specific existing graph node**
  that matches the user's intent. If the target container has no
  components defined yet, the edge points at the container. When that
  container is later decomposed, the decomposition-refinement check in
  Step 3c offers to re-point such edges at a child.
- Mixed-level edges are allowed (e.g. a container calling a component
  in another container) so long as both endpoints resolve to existing
  graph nodes.

## Alias normalization

User input is normalized to kebab-case for matching and validation.
The canonical, kebab-case identifier as stored in the taxonomy or graph
is what gets persisted. Normalization is applied to `$ARGUMENTS` on
invocation and to any candidate node name encountered during interviews
or derivation.

Summary of 6-step algorithm: CamelCase split → acronym split → lowercase
→ punctuation/space collapse → double-dash collapse → strip
leading/trailing dashes.

Full algorithm with examples: `references/alias-normalization.md`.

## Artifact format

All output files are **pure YAML** — no markdown prose, no commentary.
Every artifact carries a top-level `updated-at:` field (ISO 8601, UTC)
bumped on every write. `updated-by:` is always `sdlc-arch`.

Per-tier YAML templates (root/context, container, component+code,
split-code), soft-cap / output-mapping rules, and field semantics:
`references/artifact-templates.md`.

Authoritative shapes are enforced by
`references/artifact-schemas/*.schema.json` and validated at Step 4b.

## Architecture pattern selection (brief)

Do not hard-bias toward any single pattern. Consider team count and
ownership boundaries, independent deployment needs, expected scale
asymmetry, domain complexity, external integrations, async workflow
needs, plugin/extensibility needs, ops maturity, and observability
tolerance.

For AI-built projects, also consult the `ai-builder-considerations:`
section in the pattern matrix. Load `references/pattern-selection.yaml`
only when actively selecting or revisiting a pattern at the context
level. Narrative selection guidance: `references/pattern-selection.md`.

## Existing-doc ingestion rules

- Read `.claude/rules/` general rule files (no frontmatter) for context.
  Do not use `.claude/rules/` as an artifact write target — artifacts
  live in `docs/`.
- Prefer explicit architecture / spec / design docs when present.
- If multiple docs disagree, ask the user which to trust **before**
  mutating state, using the literal `conflict-resolution` template.
- During bootstrap, infer only what the evidence supports: containers,
  components, code-level units when clearly named, aliases, and
  `defined | wip | complete` per node. Edges are produced by Step 1b's
  call into the edge-derivation procedure (Step 3-alt), not invented
  inline.
- Do not over-infer. Missing evidence stays as missing evidence — leave
  the node `defined` rather than guess.
- Validation (Step 4b) runs **only on writes**. Old artifacts read
  during bootstrap are read tolerantly — a schema violation in legacy
  content is reported but does not block ingestion.

## Example session

See `references/example-session.md` for a full `/sdlc:arch` session
walkthrough showing Step 0 signature output, a container-level
interview, edge derivation, and confirmation.

## Reference index

Load reference files lazily, only when relevant to the active node and
phase. Heavy data (taxonomies, question inventories, pattern matrix,
schemas) deliberately lives outside this file to keep context lean.

| File                                             | When to load                                                            |
|--------------------------------------------------|-------------------------------------------------------------------------|
| `references/preflight.md`                        | Step 0.5 — full abort-message catalog and exit-code mapping.            |
| `references/bootstrap.md`                        | Step 1b — blank-start block, RETRY/ASK/EXIT handling, edge cases.      |
| `references/c4-guidance.md`                      | When deciding what belongs at the active C4 level.                      |
| `references/container-taxonomy.yaml`             | When naming or interviewing about a container.                          |
| `references/component-taxonomy.yaml`             | When naming or interviewing about a component.                          |
| `references/question-inventories.yaml`           | At the start of every interview phase.                                  |
| `references/pattern-selection.yaml`              | Only at root/context level when selecting an architecture pattern.      |
| `references/pattern-selection.md`                | Narrative selection guidance; load with `pattern-selection.yaml`.       |
| `references/prompt-templates.yaml`               | When entering any phase — provides the prompt skeleton for that phase.  |
| `references/ai-directed-notation.md`             | When reading or writing process-flow notation in any reference file.    |
| `references/edge-vocabulary.yaml`                | At Step 3c, to classify candidate edges by verb / phrase.               |
| `references/alias-normalization.md`              | When unsure about normalization algorithm or edge cases.                |
| `references/artifact-templates.md`               | When authoring a new node — per-tier YAML templates and size rules.    |
| `references/artifact-schemas/*.json`             | At Step 4b — JSON Schema validation of just-written artifacts.          |
| `references/example-session.md`                  | When the user asks for help or an example walkthrough.                  |
| `references/edge-cases.md`                       | When encountering unusual situations (legacy state, empty files, etc.). |

---
name: data
description: >
  Launch in empty context. Create or update DATA-MODEL.yaml for a software
  product across six storage paradigms (relational, document, key_value, graph,
  vector, file_native). Reads docs/PRD.yaml and any docs/UX*.yaml as upstream
  inputs, scans pre-fill candidates, recommends a storage paradigm from PRD
  signals and asks the structural paradigm/monorepo/bounded-contexts questions,
  then routes a resume-aware thematic interview down the paradigm-appropriate
  path (with a per-entity drill-down for the critical `entities` theme),
  persists session state for resumability, and writes + validates
  docs/DATA-MODEL.yaml for downstream agent consumption (api, arch, test).
  Trigger only on /sdlc:data or a direct natural-language request for the data
  model — do not auto-trigger from generic chat. ONLY stop when no open
  questions remain or the user types EXIT.
user-invocable: true
disable-model-invocation: true
model: opus
effort: high
allowed-tools: Read Write(CLAUDE.md) Write(docs/DATA-MODEL.yaml) Write(.claude/skills-state/sdlc-data.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-data

Guides the user through a structured interview that produces a validated
`docs/DATA-MODEL.yaml` at the project root, so downstream AI agents (api,
arch, test, deploy) have a single unambiguous source of persistent-data
truth.

## What this skill does (at a glance)

1. **Resume check** → load existing state if any (otherwise scan from scratch).
2. **Scan inputs** → read `docs/PRD.yaml` (required) and every `docs/UX*.yaml`
   (required); build pre-fill map.
3. **Entity-candidate discovery** → propose a draft entity list early.
4. **Structural questions** → **storage paradigm** (agent recommends from PRD
   signals; user confirms) → monorepo (inherited from PRD)? → bounded contexts?
   → polyglot persistence? The paradigm decision drives everything downstream.
5. **Pre-fill confirmation** → theme by theme, each `⚠ inferred` confirmed
   individually (hallucination guard).
6. **Theme interview (paradigm-routed)** → run only the themes whose
   `applies_to_paradigms` includes the selected paradigm, PLUS the paradigm's
   own analogue themes from `references/paradigms/<paradigm>.md`. Required
   themes always run; optional themes are gated now/skip/todo. Importance tiers
   (`med | high | critical`) control batching. The `entities` theme is the lone
   `critical` (and lone `synthesis: true`) theme — full per-entity drill-down
   (with the paradigm-appropriate field shape) followed by a dynamic
   scope-completeness sweep across ALL upstream ID families (ENT, FR, WKF, JTB,
   UX surfaces).
7. **Write + validate** → merge into `docs/DATA-MODEL.yaml`, run
   `validate_schema.py` (Pydantic + **paradigm-gated** cross-checks: required
   fields, relationship/edge/composition/cross-reference integrity, field
   references, vector_config/identity_conventions/key_value_design substance,
   classification integrity, bounded-context partition, ID-prefix format
   (WRN/FR/SCR/WKF), feature coverage, volume-vs-scale gate; mode-mismatch is
   enforced by the Pydantic model itself).
8. **CLAUDE.md pointer + close** → inject the pointer block, mark state
   `complete`.

State is persisted **after every confirmed batch and after every per-entity
drill-down step**, so the user can `EXIT` at any time without losing
progress, even mid-entity.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `data-questions.yaml` | The full question inventory, grouped by theme. |
| `DATA-MODEL.schema.yaml` | Human-readable canonical schema for `docs/DATA-MODEL.yaml`. |
| `validate_schema.py` | Pydantic v2 validator + cross-checks, called after every write. |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector, called in Phase 8. |
| `references/paradigms/<paradigm>.md` | **One file per storage paradigm** (relational, file-native, document, key-value, graph, vector). Each holds: "When to recommend" heuristics (read in Phase 4 to form the recommendation), the paradigm's entity-field shape, and its analogue themes/questions (read on entering Phase 6 once the paradigm is locked). Read ONLY the file for the selected paradigm. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, EXIT semantics, importance-tier flows. Read on entering Phase 6. |
| `references/entity-discovery.md` | Heuristics for deriving entity candidates from PRD features + UX surfaces. Read in Phase 3. |
| `references/submodel-and-context-sweep.md` | Exhaustive sub-model decomposition (recurse every entity's field types into first-class `sub_model` entries — the cure for shallow models) + the bounded-context partition reconciliation run before `status: complete`. Read on entering the `entities` theme (Phase 6) and again in Phase 7. |
| `references/pre-fill-sources.md` | Explicit PRD/UX-field → DATA-MODEL-field map. Read in Phase 3 + Phase 5. |
| `references/polyglot-persistence.md` | Guidance for multi-store designs (incl. cross-paradigm secondary stores). Read when the user opts into polyglot in Phase 4. |
| `references/merge-validate.md` | Merge logic for existing DATA-MODEL.yaml, validator recovery, CLAUDE.md pointer rules. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations (entity rename, mode switches, mass import, missing upstreams). Read whenever the happy path doesn't fit. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/DATA-MODEL.yaml` (project root) | Output artifact consumed by downstream agents. |
| `.claude/skills-state/sdlc-data.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer block injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the
free-text field of any `AskUserQuestion` call to abort the interview. State
is *always* saved automatically after each confirmed batch — `EXIT` simply
marks the session `status: aborted` and stops.

There is no `SAVE` command — saving is implicit.

## The 8-phase flow

### Phase 1 — Resume check

Before doing anything else, check for `.claude/skills-state/sdlc-data.state.yaml`:

- If it exists with `status: in_progress`, ask:
  > "I found an unfinished `sdlc:data` session from `<last_updated>`. Would
  > you like to **resume**, **restart** (discard previous answers), or
  > **discard** (delete state and exit)?"
- If `status: complete` or `status: aborted` and `docs/DATA-MODEL.yaml`
  exists, treat this as an update flow — see Phase 7's *merge* behavior.
- If no state file, continue to Phase 2.

### Phase 2 — Scan inputs

**Slice large docs, don't slurp.** If `docs/INDEX.yaml` exists, the project was
bootstrapped by `/sdlc:setup`. Use it to read large upstream docs by slice:
`PRD.yaml` is routinely 1000+ lines, and on the merge flow your own
`DATA-MODEL.yaml` is the largest artifact in the tree. Look a symbol up in
`INDEX.yaml` (or run `python .claude/sdlc/docs_index.py --show <symbol>`) and
`Read` only its `[start, end]` range; resolve a whole top-level block via its
`sections.<file>.<key>` range. This keeps the scan within budget on big
projects — exactly the case this skill produces. Fall back to whole-file reads
when `INDEX.yaml` is absent. Protocol: `.claude/rules/sdlc-docs-access.md`.

Required upstream artifacts:

1. **`docs/PRD.yaml`** — fail fast and inform the user if missing. Suggest
   running `/sdlc:prd` first.
2. **`docs/UX.yaml`** — strongly recommended (used for surface coverage and
   entity-field discovery). If missing, warn the user; offer to continue
   without UX context but note that downstream `api` will have weaker
   surface-coverage.
3. **`docs/UX__*.yaml`** — every sibling file is read for `validation_rules`,
   `components.content_slots`, and `interactions.effects`, which seed
   entity-field candidates.

Also scan:

- Existing `docs/DATA-MODEL.yaml` (for merge flow).
- Schema-like files in `db/`, `migrations/`, `prisma/`, `schema.prisma`,
  `*.sql`, `models/`, `entities/` — extract entity names verbatim where
  obvious (mark as `✓ found`).
- Lockfiles, binaries, and node_modules/venv directories — skip.

Build the pre-fill map (see `references/pre-fill-sources.md` for the full
mapping table). Tag each candidate:

- **`✓ found`** — value is a direct quote/value from a file (e.g.
  `PRD.security_compliance.encryption_at_rest: true` → `data_classification.encrypted_at_rest_default: true`).
- **`⚠ inferred`** — derived from signals (e.g. `PRD.data_model.key_entities: [User]` →
  candidate entity name `User`, but no fields yet).

**Upstream-change detection (re-runs).** If `docs/DATA-MODEL.yaml` already
exists and carries `metadata.upstream_provenance`, this is a re-run: for each
upstream artifact (`docs/PRD.yaml`, `docs/UX.yaml`), compare the recorded
`sha256` to its current hash (from `docs/INDEX.yaml.generated_from[<file>]`,
else `sha256(bytes)[:16]`). For every changed upstream, classify the delta
(added / removed / modified ids) and run the **delta-review pass before the
entity interview** per `sdlc/skills/ux/references/upstream-reconciliation.md`
(CLAUDE.md §7). This supersedes the older `session_id`-only stale-PRD check —
a content hash also catches hand-edits to an upstream yaml, which `session_id`
does not. If every upstream is unchanged, proceed to the merge flow without a
delta-review. Fresh runs (no prior `docs/DATA-MODEL.yaml`) skip this step.

### Phase 3 — Entity-candidate discovery

This is the most novel and most hallucination-prone phase. The skill
proposes a **draft entity list** before any deep interview begins, so the
user can correct course early. Sources of candidates, in priority order:

1. **`PRD.data_model.key_entities`** — direct names (PascalCase'd if not
   already). Tag `✓ found`.
2. **`PRD.functional_requirements.must_have_features`** — extract the
   nouns from each FR-NNN feature using lightweight heuristics (see
   `references/entity-discovery.md`). Tag `⚠ inferred`.
3. **`UX__<surface>.yaml.layout` + `validation_rules` + `components.content_slots`** —
   forms imply entities; list items imply entities; filters imply entities.
   Tag `⚠ inferred`.
4. **Schema files on disk** (Prisma, SQL, `models/`) — if present, those
   names are authoritative. Tag `✓ found`.

Present the draft to the user:

> "Based on PRD + UX, I see these entity candidates:
>
>   ✓ User           (from PRD.data_model.key_entities)
>   ✓ Project        (from PRD.data_model.key_entities)
>   ⚠ Task           (inferred from FR-001 'Add a task in under 3 seconds')
>   ⚠ Tag            (inferred from UX__dashboard form field 'tags')
>
> Add, remove, or rename anything before we go deep on each one?"

Persist the confirmed list to `state.defined_entities`. **Critical rule**:
each `⚠ inferred` candidate must be confirmed individually — no batch-accept
shortcuts.

### Phase 4 — Structural questions

These determine *the shape of DATA-MODEL.yaml*, not its content.

Two patterns coexist here and the convention matters:

- **Yaml-less structural questions** (monorepo, bounded_contexts,
  audit-columns preliminary) have no entry in `data-questions.yaml`
  because they are meta — they describe the document's shape rather
  than its content. Phase 4 hard-codes their prompts.
- **Yaml-backed structural questions** (polyglot) have an entry in
  `data-questions.yaml` under their natural theme (e.g. `persistence`)
  AND get asked in Phase 4. Phase 6 sees them already-answered and
  skips the duplicate.

Ask in order:

0. **Storage paradigm** — THE foundational decision; everything downstream
   routes off it. Six paradigms: `relational | document | key_value | graph |
   vector | file_native`.

   **The agent recommends first.** Before asking, derive a recommendation
   from PRD signals and present it at **position 1** with a one-line
   rationale (the position-1 recommendation pattern, not a silent default —
   the user still confirms or overrides). The signals (data volume,
   relationship density, embedding/semantic-search needs, query shape,
   deployment footprint, and any explicit `PRD.data_model.storage_preferences`)
   and their mapping to paradigms live in each paradigm reference's
   **"When to recommend"** section — **read
   `references/paradigms/<candidate>.md`** for the heuristics before forming
   the recommendation. Run this as a `critical`-style mini-decision:
   propose → one-line rationale → user picks. Persist
   `state.storage_paradigm`; write `persistence.paradigm`,
   `persistence.paradigm_confidence`, `persistence.paradigm_rationale`.
   Frozen for the project's lifetime once chosen (a later change is an
   explicit restart of the data model — see `references/edge-cases.md`).

   Once locked, **load `references/paradigms/<paradigm>.md`** — it defines the
   entity-field shape and the analogue themes you'll run in Phase 6.

0b. **Storage topology** — the axis ORTHOGONAL to the paradigm (the family).
   Right after the paradigm is locked, recommend `persistence.topology` —
   *where/how* the store runs: `local_embedded | networked_server |
   cloud_managed | serverless | in_memory | other`. The same family runs
   across topologies, so this is a separate decision, not implied by the
   paradigm. Derive the recommendation from PRD signals: single-user / CLI /
   desktop + bounded volume + no concurrent writers ⇒ `local_embedded`;
   multi-tenant SaaS or a server runtime ⇒ `networked_server` /
   `cloud_managed`; spiky load + low-ops ⇒ `serverless`; cache/ephemeral-only
   ⇒ `in_memory`. Present at position 1 with a one-line rationale; the user
   confirms or overrides. Write `persistence.topology`,
   `persistence.topology_confidence`, `persistence.topology_rationale`. It's
   optional — if the user is genuinely undecided, leave it null and append a
   `WRN-NNN`. The concrete provider (RDS vs Cloud SQL vs self-managed) is
   finalized later at the deploy stage; topology only pins the deployment
   shape the data model assumes.

1. **Monorepo mode** — inherited from `PRD.metadata.monorepo`. Show as
   pre-filled and ask the user to confirm only if PRD signals conflict
   (rare). (In monorepo mode each product may pick its own paradigm —
   ask the paradigm question per product.)
2. **Bounded contexts** — opt-in. Ask:
   > "Do you want to group entities under DDD-style bounded contexts (e.g.
   > `auth: { entities: [...] }`, `billing: { entities: [...] }`)? Default:
   > no — keep `entities` as a flat dict."
   If the user opts in, ask for context names and assign each confirmed
   entity to exactly one context. Persist `state.bounded_contexts_enabled`
   and the assignment map.
3. **Polyglot persistence** — pre-fill from `PRD.data_model.storage_preferences`.
   If multiple stores are listed, default to `polyglot: true` and ask the
   user to confirm. See `references/polyglot-persistence.md` for the
   secondary-store interview script. (Yaml-backed: the `polyglot` entry
   under the `persistence` theme is consumed here, not in Phase 6.)
4. **Audit-columns preliminary** — `audit_and_lifecycle` is theme 9 in
   `data-questions.yaml`, but its `audit_columns` answer (created_at /
   updated_at / created_by / updated_by / deleted_at) influences every
   per-entity drill-down in theme 3 (`entities`). Ask up-front, in Phase
   4, with a strong default:
   > "Add `created_at` and `updated_at` to every entity by default?
   > (Per-entity opt-out is possible. We'll revisit the full audit
   > picture — soft delete, archive — in theme `audit_and_lifecycle`.)"
   Persist the answer to `state.partial_answers.audit_and_lifecycle.
   audit_columns`. The full theme later refines it.

Persist all structural answers to state before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme** (skipping `entities` — that
gets its own treatment in Phase 6). For each theme:

1. **Display** the themed block as a summary (read-only preview) so the
   user can see all pre-fills together:

   ```
   ## Persistence (pre-filled)

     ✓ primary_store          : postgres                 [from PRD.data_model.storage_preferences]
     ⚠ polyglot               : true                     [inferred from secondary store: redis]
       secondary_stores       : (not pre-filled — will ask in Phase 6)
     ⚠ file_blob_store        : s3                       [inferred from regulatory_requirements: gdpr → audit log retention]
   ```

2. **Confirm via AskUserQuestion**, one structured call per `⚠ inferred`
   item — never bulk-accept. The candidate sits at position 1 with the
   `"(Recommended) "` prefix; the user must explicitly select it or pick
   another option. This is the position-1 hallucination guard from
   `references/interview-mechanics.md`.

3. **Batch-accept `✓ found` items** with a single AskUserQuestion
   multi-select call ("which of these found values should I keep
   verbatim?") — `✓ found` items come from direct quotes upstream, so
   bulk acceptance is appropriate here, with an "uncheck to edit"
   escape hatch.

The free-text shortcuts `confirm` / `ok` listed in the *Quick reference*
table below are accepted when the user types them into the "Other"
field of an AskUserQuestion call — they are not chat-mode commands.

**Critical rule** (hallucination guard): `⚠ inferred` items must NOT be
batch-accepted. Each one needs an explicit selection or correction in
its own AskUserQuestion call. Pre-filled inferences are where wrong
requirements sneak in unnoticed.

Write the confirmed values into the state file. Set
`<field>_confidence: confirmed` for explicitly confirmed items,
`<field>_confidence: inferred` for accepted-as-is inferences.

### Phase 6 — Theme interview (paradigm-routed)

Walk the themes in the order defined by `data-questions.yaml`. Use
`AskUserQuestion` as the canonical asking channel.

#### Paradigm routing (do this first)

The selected `state.storage_paradigm` decides which themes run:

1. **Universal + applicable `data-questions.yaml` themes** — run a theme only
   if its `applies_to_paradigms` list contains the selected paradigm (or is
   `[all]`). Themes whose list omits the paradigm are **skipped silently** —
   do NOT offer them as a now/skip/todo gate. (E.g. for `vector` you skip
   `relationships`, `indexes_and_queries`, `integrity_and_constraints`,
   `id_strategy`, `migrations_and_evolution`, `transactions_and_consistency`.)

2. **Paradigm analogue themes** — read `references/paradigms/<paradigm>.md` and
   run the analogue themes it defines. These replace the skipped relational
   themes with the paradigm's own structural questions:

   | paradigm     | analogue themes (from the reference file)                          |
   |--------------|--------------------------------------------------------------------|
   | relational   | (none — uses the data-questions.yaml relational themes directly)   |
   | document     | `composition`, `cross_references` (id links between documents)     |
   | key_value    | `key_value_design` (partition/sort keys, GSIs)                     |
   | graph        | `edges`, `graph_config` (traversal patterns)                       |
   | vector       | `vector_config` (embedding model, dims, distance, ANN index)       |
   | file_native  | `identity_conventions`, `composition`, `cross_references`, `serialization_conventions` |

   Wherever `cross_references` runs (document / file_native), close the theme
   with the **gate-clause sweep** (`references/paradigms/file-native.md` →
   "Gate-clause sweep"): every `Entity.field` that an upstream-named
   referential/coverage gate queries must have a cross_references row or an
   explicit `WRN-NNN` carve-out, and non-id-family relations (composite
   tuples, paths) get their resolution rule declared. An edge table that
   self-describes as exclusive but lacks rows for fields the gates read makes
   those gates mechanism-only.

3. **Entity field shape** — when drilling each entity in the `entities` theme,
   use the field-attribute shape the paradigm reference specifies (relational:
   `type/nullable/unique/primary_key/references/on_delete`; file_native:
   `pydantic_type` + `description`, no primary_key; graph: node properties;
   vector: `payload_fields` + one `embedding: true` field; key_value: fields +
   key design captured in `key_value_design`).

   **Decompose, don't skim.** For every entity, recurse into its field types:
   any field whose type is a custom model (directly, in a `list[...]`/`dict[...]`,
   or `Optional[...]`) names a **sub-model that must exist as its own
   `entities.<Name>` entry** — define it and recurse into *its* fields, until
   every leaf is a scalar, an enum, or a reference to another first-class entity.
   This is the cure for shallow models (a `features: list[FeatureSpec]` whose
   `FeatureSpec` is never defined). After the entity scope-completeness sweep,
   run the dedicated **sub-model pass** described in
   `references/submodel-and-context-sweep.md` (Part A) so no referenced model is
   left undefined.

#### Required vs optional themes

- **Required themes** (`required: true`): run the theme's questions until
  every required question is answered.
- **Optional themes** (`required: false`): before asking any questions,
  offer a gate:
  > "Theme: **\<name\>** — N questions. \<one-line description\>.
  > Address now, skip, or mark as todo?"
  - **now** → run the theme's questions.
  - **skip** → record under `skipped_themes` in state, move on.
  - **todo** → append `"TODO: address theme <name>"` to
    `data_warnings`, move on.

#### Conditional promotion

If `PRD.data_model.data_volume_estimate ∈ {terabytes, petabytes}` AND the
selected paradigm includes `scale_and_retention` in its
`applies_to_paradigms` (relational/document/key_value), the
`scale_and_retention` theme is promoted to required regardless of its
default. The agent re-evaluates promotion rules at every theme boundary.
(For graph/vector/file_native the volume gate does not apply — the validator
skips it for those paradigms.)

#### Tiered question flow (within a theme)

Each question in `data-questions.yaml` carries an `importance` field
(`med | high | critical`) that controls how the agent runs it:

- **`med`** (default): batch with up to 3 sibling `med` questions from the
  same theme into one `AskUserQuestion` call. `⚠ inferred` candidate at
  position 1.
- **`high`**: runs as its **own mini-section** — never batched. For
  scalars: agent drafts a full answer, shows it, user approves or iterates
  (max 3 rounds). For list[string] fields: per-item with one clarifying
  challenge round each.
- **`critical`** (only `entities`): full per-entity state machine — propose
  → challenge → fields → relationships → indexes → traces → final approval
  → next entity. Each entity is examined before being added. The
  per-entity questions use a `entity.<field>` prefix on `schema_path` that
  the agent rewrites per entity (e.g. `entity.fields` →
  `entities.User.fields` when drilling User). Because the `entities`
  theme is also `synthesis: true`, after the per-entity loop closes the
  agent runs a **dynamic scope-completeness sweep** that reflects on:
  (a) the draft entity list itself; (b) every upstream ID family that
  could imply an entity (PRD `ENT-NNN` key_entities, `FR-NNN` features,
  `WKF-NNN` workflows, `JTB-NNN` jobs, UX `SCR-NNN` surfaces with
  data I/O); (c) project-type heuristics. Surfaces concrete candidate
  entities — not categories — via one multi-select `AskUserQuestion`;
  cap of 2 sweep passes; anti-padding rule. See
  `references/entity-discovery.md` "Scope-completeness sweep" for the
  full procedure.

Order within a theme: run all `med` questions first (in 2–4-question
batches), then each `high`/`critical` question as its own mini-section in
the order they appear in `data-questions.yaml`.

**Read `references/interview-mechanics.md` before running any
`high`/`critical` question** for the exact AskUserQuestion prompts,
iteration caps, EXIT-mid-flow rules, and the per-entity state machine.

The two non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended option**
   in their `AskUserQuestion` call. They cannot be silently accepted — the
   user must explicitly pick or correct. This is the hallucination guard.
2. State is written after **every confirmed batch, mini-section, or
   per-entity step** — not at theme boundaries.

### Phase 7 — Write & validate

**Before writing, when bounded contexts are enabled, run the bounded-context
reconciliation** (`references/submodel-and-context-sweep.md`, Part B): every
entity — including every `sub_model` promoted in Phase 6 — must appear in
exactly one `bounded_contexts.<family>.entities` list, and every name listed
there must be a real entity. Compute orphans / phantoms / duplicates, resolve
each with the user (orphans default to their `category`-implied context, usually
a one-click batch), and repeat until the partition is clean. This is the same
check `validate_schema.py` runs — doing it here means the validator never reports
"entity X is not assigned to any context" at write time (the failure mode that
piled up dozens of orphans in manual runs).

Write or merge `docs/DATA-MODEL.yaml` at the project root, then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/DATA-MODEL.yaml
```

For full merge logic (conflict handling, entity renames, field removal,
deletion confirmation), type discipline when writing nested entity blocks,
and the exit-code recovery flow → see `references/merge-validate.md`.

When writing the file: inline YAML comments on top-level keys, updated
`metadata.last_updated` and `metadata.session_id`, and a (re)written
`metadata.upstream_provenance` snapshot — one entry per upstream consumed
(`docs/PRD.yaml`, `docs/UX.yaml`), each `{file, session_id, last_updated,
sha256}` (`sha256` from `docs/INDEX.yaml.generated_from`, else
`sha256(bytes)[:16]`). Replace-on-write, not append-only. See CLAUDE.md §7.

Set `metadata.status`:

- `"complete"` — only when all required fields are filled and the validator
  passes with `[OK]`.
- `"draft"` — on early EXIT or when any required field is still null, or
  when a cross-check (feature coverage, relationship integrity,
  classification integrity) reports problems.

If the validator returns `[FAIL]` because required fields are missing
despite `status: complete`, ask the user via `AskUserQuestion` to either
fill them in now or accept `status: draft`.

### Phase 8 — CLAUDE.md pointer & close

On successful validation (`[OK]` or `[DRAFT]`), call
`set_claude_md_pointer.py` to inject or update this skill's bullet inside
the shared `## SDLC Documents` section of the project root `CLAUDE.md`.
Create `CLAUDE.md` with the section if missing.

For the bullet format, detection rule, and append behavior → see
`references/merge-validate.md`.

**Refresh the navigation index.** `DATA-MODEL.yaml` is the largest artifact in
the tree, so a current `docs/INDEX.yaml` matters most here. If
`.claude/sdlc/docs_index.py` exists (the project ran `/sdlc:setup`), run
`python .claude/sdlc/docs_index.py` after writing the file so downstream
`api`/`arch` can slice it immediately. The setup hook also does this, but a hook
added mid-session only activates next session. Harmless no-op if not installed.

After the CLAUDE.md write succeeds: set `status: complete` in the state
file (do not delete it — it's an audit trail), and tell the user where the
artifacts live.

## Session state file

Path: `.claude/skills-state/sdlc-data.state.yaml`

Schema:

```yaml
session_id: <uuid4 string>
skill_version: "1.1"
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted
storage_paradigm: null  # relational | document | key_value | graph | vector |
                        # file_native. Chosen in Phase 4; frozen for the
                        # project. In monorepo mode use storage_paradigm_by_product.
storage_paradigm_by_product: {}  # slug → paradigm (monorepo mode only)
monorepo: false      # mirrors DATA-MODEL metadata; inherited from PRD
products: []         # populated only when monorepo: true; list of product slugs
bounded_contexts_enabled: false
bounded_contexts_map: {}     # entity_name → context_name (when enabled)
polyglot_persistence: false
pre_fill_confirmed: false
completed_themes: []
skipped_themes: []
todo_themes: []
pending_themes: []
current_theme: null
current_entity: null         # which entity is mid-deepdive in theme 3
defined_entities: []         # list of {name, status: proposed|draft|confirmed|dropped, source}
dropped_entity_candidates: []  # so we don't re-propose ones the user rejected

# Per-family ID counters (single-product mode). Each entry is the last-assigned
# integer for that family — increment, format as <PREFIX>-{:03d}, then persist.
# This skill emits only the WRN family; the data model does not introduce a
# new entity-level ID family (entity names are dict keys, and PRD's ENT-NNN
# is consumed verbatim, not regenerated).
last_ids: {}        # e.g. {WRN: 3}

# Per-product ID counters (monorepo mode only). Same shape as last_ids, keyed
# by product slug. Each product carries an independent WRN id space.
last_ids_by_product: {}  # e.g. {billing: {WRN: 1}, notifications: {WRN: 2}}

partial_answers: {}          # mirrors DATA-MODEL.yaml structure incrementally
```

Rules:

- Generate `session_id` as a UUID4 on first creation.
- Update `last_updated` on every write.
- Write the file **after every confirmed batch, mini-section, and per-entity
  step**, including pre-fill confirmations and Phase 3 entity-list
  confirmation.
- On user `EXIT`: set `status: aborted`, write current `partial_answers`,
  confirm to user that state was saved, then stop.
- On Phase 8 completion: set `status: complete` but keep the file.
- The validator ignores this file — it validates only `docs/DATA-MODEL.yaml`.

**Source of truth on resume:**

- `docs/DATA-MODEL.yaml` (if present) is the on-disk source of truth for
  *answers*.
- The state file is the source of truth for *interview progress*.
- On resume: load `docs/DATA-MODEL.yaml` first as the baseline, then layer
  the state's `partial_answers` on top.
- If they conflict on the same key, ask the user which to keep — never
  silently overwrite.

## Edge cases

For unusual situations (missing PRD, missing UX, existing DATA-MODEL.yaml
without state file, conflicting scan signals, entity rename mid-flow,
relationship integrity failures, mass entity import from schema files,
mid-interview abort, very large projects, write-permission errors,
hallucination-guard violation attempts) → see `references/edge-cases.md`.

## Style of conversation

The interview is potentially long, especially the per-entity drill-down.
Keep it humane:

- Use the user's terminology as soon as they introduce it.
- Keep AskUserQuestion batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme boundary and at each entity boundary
  ("That's User done — 5 fields, 2 relationships, 3 indexes. Next: Task,
  which I've drafted as 4 fields. Review and add?").
- Always make multiple-choice the path of least resistance.
- After all themes are done, congratulate the user briefly and move to
  write/validate. Do not repeat the entire summary back at them.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 entity list as-is. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs it to `data_warnings`. |

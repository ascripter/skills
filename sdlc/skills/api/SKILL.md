---
name: api
description: >
  Explicitly invoked skill. Creates or updates docs/API.yaml plus one
  docs/API__<resource>.yaml per API resource, consumed by downstream
  coding agents (arch → test → task → deploy). Trigger only on /sdlc:api
  or a direct natural-language request to start the API skill — never
  auto-trigger from generic API chatter.
user-invocable: true
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read Write(CLAUDE.md) Write(docs/API.yaml) Write(docs/API__*.yaml) Write(.claude/skills-state/sdlc-api.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-api

Guides the user through a structured interview that produces a validated
`docs/API.yaml` (global API contract) plus one
`docs/API__<resource>.yaml` per API resource, so downstream coding agents
have an unambiguous machine-readable description of every endpoint, DTO,
auth scheme, error envelope, and event channel they need to implement.

## What this skill does (at a glance)

1. **Resume check** → load existing state if any.
2. **Scan inputs** → read `docs/PRD.yaml`, `docs/UX.yaml` (+ all
   `UX__*.yaml`), and `docs/DATA-MODEL.yaml`. Run each upstream skill's
   validator. Exit early if any input is missing, invalid, or not
   `metadata.status: complete`.
3. **Structural questions** → confirm `api_kind`
   (`rest | graphql | grpc | mixed | none`) and `transport_styles`. If
   the user picks `none`, skip the rest of the interview and write a
   minimal API.yaml.
4. **Pre-fill confirmation** → theme by theme, each `⚠ inferred`
   confirmed individually.
5. **Theme interview** → required themes always run; optional themes
   gated now/skip/todo. Theme 8 (`resource_inventory`) and theme 10
   (`per_resource_deepdive`) run as `critical` `synthesis: true`
   per-item drill-downs — every resource is examined, confirmed, and
   traced back to PRD features (FR-NNN) + UX surfaces (SCR-NNN) +
   optionally PRD workflows (WKF-NNN) + a DATA entity (by name).
   After theme 8's per-item loop closes, the agent runs a dynamic
   **scope-completeness sweep** drawing on every upstream ID family;
   see `references/resource-discovery.md`.
6. **Write & validate** → merge into `docs/API.yaml` and write all
   `docs/API__<resource>.yaml` (every endpoint carries a stable
   `id: OPR-NNN` assigned by the writer), then run `validate_schema.py`
   (Pydantic + ID-prefix format checks (WRN/FR/SCR/WKF/OPR) +
   feature/surface coverage + entity-link checks).
7. **CLAUDE.md pointer + close** → call `set_claude_md_pointer.py`,
   mark state `complete`.

State is persisted **after every confirmed batch and after every
per-resource deep-dive**, so the user can `EXIT` at any time without
losing progress.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `api-questions.yaml` | Full question inventory grouped by theme. |
| `API.schema.yaml` | Human-readable canonical schema for `docs/API.yaml`. |
| `API__RESOURCE.schema.yaml` | Human-readable canonical schema for `docs/API__<resource>.yaml`. |
| `validate_schema.py` | Pydantic v2 validator (API.yaml + every API__*.yaml + coverage + entity-link checks). |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector, called in Phase 8. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, EXIT handling, conditional promotions. Read on entering Phase 6. |
| `references/resource-discovery.md` | How to enumerate resources from DATA entities + PRD features + UX surfaces; per-resource state machine. Read whenever theme 8 or 10 is active. |
| `references/openapi-embedding.md` | OpenAPI 3.1 subset supported, forbidden keywords, cross-file `$ref` rule, DTO-vs-entity discipline. Read whenever theme 10 is active. |
| `references/async-and-events.md` | When to populate the `events` block, payload conventions, delivery guarantees. Read whenever theme 9 is active. |
| `references/merge-validate.md` | Merge logic for `API.yaml` and per-resource yamls, the three coverage checks, CLAUDE.md pointer rules. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations and how to handle them. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/API.yaml` (project root) | Global API contract consumed by downstream agents. |
| `docs/API__<resource>.yaml` (project root) | One file per API resource. `<resource>` is kebab-case. |
| `.claude/skills-state/sdlc-api.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer bullet injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the
free-text field of any `AskUserQuestion` call to abort. State is saved
after every confirmed batch and after every per-resource deep-dive, so
progress is never lost — `EXIT` simply marks the session
`status: aborted` and stops.

There is no `SAVE` command — saving is implicit.

## The 8-phase flow

### Phase 1 — Resume check

Before doing anything else, check for
`.claude/skills-state/sdlc-api.state.yaml`:

- If it exists with `status: in_progress`, ask:
  > "I found an unfinished API session from `<last_updated>`. Would you
  > like to **resume**, **restart** (discard previous answers), or
  > **discard** (delete state and exit)?"
- If `status: complete` or `status: aborted` and `docs/API.yaml`
  exists, treat this as an update flow — see
  `references/merge-validate.md`.
- If no state file, continue to Phase 2.

### Phase 2 — Scan inputs

`sdlc:api` does NOT re-interview anything that already lives in
`docs/PRD.yaml`, `docs/UX.yaml`, or `docs/DATA-MODEL.yaml`. Read these
files at startup and validate each via its upstream skill.

**Slice, don't slurp.** When `docs/INDEX.yaml` exists (the project ran
`/sdlc:setup`), read the large upstreams **by line range via the index**:
look the needed section/symbol up in `INDEX.yaml` (`sections` /
`symbols`, or `python .claude/sdlc/docs_index.py --show <symbol>`) and
`Read` only that slice — the extraction lists below name exactly which
blocks each upstream contributes. Fall back to a whole-file read only
when `INDEX.yaml` is absent or the doc is genuinely small. See
`.claude/rules/sdlc-docs-access.md`.

1. **`docs/PRD.yaml`** — required.

   ```bash
   python sdlc/skills/prd/validate_schema.py --path docs/PRD.yaml
   ```

   - If exit code ≠ 0 or `metadata.status != "complete"` → stop. Print
     a clear warning telling the user to complete the PRD first
     (`/sdlc:prd`).
   - Extract the fields the API skill needs:
     - `security_compliance.auth_model` → preliminary `auth.schemes`
     - `users_personas.primary_users` + `secondary_users` →
       preliminary `auth.roles`
     - `functional_requirements.must_have_features` (FR-NNN list) →
       feature-coverage source of truth
     - `functional_requirements.integrations_required` →
       preliminary `external_dependencies`
     - `technical_constraints.runtime_platform` → narrows `api_kind`
       (e.g. `cli` → strong default `api_kind: none`)
     - `non_functional_requirements.scalability ∈ {large, hyperscale}`
       → strong hint for `pagination.strategy: cursor` and stricter
       `rate_limiting` defaults (per_user + per_ip together).
     - `non_functional_requirements.performance_targets` → verbatim
       rationale for `rate_limiting.burst` / `sustained` values.
     - `non_functional_requirements.reliability: mission_critical` →
       hint for `errors.retry_semantics` (5xx + 429 with Retry-After).
     - `metadata.monorepo` + `products: <slug>:` → if true, the API
       skill runs the interview **per product** and writes one
       `API.yaml` per product slug. (See `references/edge-cases.md`.)

2. **`docs/UX.yaml`** + all `docs/UX__<surface>.yaml` — required.

   ```bash
   python sdlc/skills/ux/validate_schema.py --path docs/UX.yaml
   ```

   - Same `status: complete` and exit-code-0 gate as PRD.
   - Extract:
     - `surface_family` → hint for `api_kind` (cli → likely `none`)
     - Every surface's `surface_id`, `surface_type`, `interactions`,
       `validation_rules` → surface-coverage source of truth; agent
       infers candidate resources from surfaces with data I/O
     - `navigation_model.top_level_nodes` → hints for base_path
       grouping (e.g. `/dashboard` → `dashboard` resource)

3. **`docs/DATA-MODEL.yaml`** — required.

   ```bash
   python sdlc/skills/data/validate_schema.py --path docs/DATA-MODEL.yaml
   ```

   - Same `status: complete` and exit-code-0 gate as PRD/UX. If the file
     is absent → stop. Print:
     > "Cannot start the API interview — `docs/DATA-MODEL.yaml` is
     > missing. Run `/sdlc:data` first."
   - Extract the fields the API skill needs:
     - `entities` keys (PascalCase) → candidate axis for
       `resource_inventory` (one resource per primary entity by default).
     - `entities` keys → pool of valid `primary_entity` references
       (the entity-link check fails any reference that's not in this set).
     - `entities` keys → source of truth for
       `$ref: data-model://<EntityName>` in per-resource schemas. See
       `references/openapi-embedding.md`.
     - `id_strategy.scheme` → path-parameter `format` for `{id}` segments
       (`uuid_v4|uuid_v7|ulid` → `format: uuid`; `serial_int|bigserial`
       → `type: integer`; `nanoid|natural_key` → `type: string`).
     - `data_classification.pii_fields` + `regulated_fields` +
       `encrypted_at_rest` → authoritative "omit from public DTOs"
       list. DTOs MUST omit these fields by default; the user can opt
       a field back in per resource with an explicit confirmation.
     - `audit_and_lifecycle.soft_delete: true` → DELETE endpoints
       become soft-delete (status 204 + the row stays). Default is
       hard-delete.
     - `enums_and_lookups.enums` → pre-fill DTO `enum:` constraints
       wherever a DTO field maps to one of these enums.
     - `bounded_contexts` (when present) → propose grouping resources
       by context (one tag group per context). Cross-context references
       still go via `data-model://` $refs.
     - `indexes_and_queries.access_patterns` → pre-fill list endpoints
       (one per pattern) and the `pagination.stable_sort_field` hint
       when the pattern's `fields` list ends in a monotonic column.

4. Existing `docs/API.yaml` and `docs/API__*.yaml` — if present, treat
   as the merge baseline (Phase 7).

5. Optional context files at project root: `README*`, any existing
   `openapi.yaml`/`openapi.json`, `*.openapi.*`. Quote findings in
   pre-fill rationale.

Build the pre-fill map exactly as `sdlc:prd` and `sdlc:ux` do,
classifying each candidate as `✓ found` (direct quote from PRD/UX/DATA
or local file) or `⚠ inferred` (derived).

**Upstream-change detection (re-runs).** If `docs/API.yaml` already exists and
carries `metadata.upstream_provenance`, this is a re-run: for each upstream
artifact (`docs/PRD.yaml`, `docs/UX.yaml`, `docs/DATA-MODEL.yaml`), compare the
recorded `sha256` to its current hash (from
`docs/INDEX.yaml.generated_from[<file>]`, else `sha256(bytes)[:16]`). For every
changed upstream, classify the delta (added / removed / modified ids) and run
the **delta-review pass before the theme interview** per
`sdlc/skills/ux/references/upstream-reconciliation.md` (CLAUDE.md §7). If every
upstream is unchanged, proceed to the merge flow without a delta-review. Fresh
runs (no prior `docs/API.yaml`) skip this step.

### Phase 3 — Idea capture (lightweight)

Unlike `sdlc:prd`, this skill does NOT need to capture a free-text idea
brief — PRD, UX, and DATA together fully describe the product. Quote it
back briefly:

> "Working from `docs/PRD.yaml`, `docs/UX.yaml`, and
> `docs/DATA-MODEL.yaml`. Product: `<name>` — `<one_liner>`. Surface
> family: `<surface_family>`. `<N>` PRD features, `<M>` UX surfaces,
> `<K>` DATA entities. Starting the API interview. Type anything to add
> framing context, or `ok` to proceed."

If the user types extra context, store it verbatim in `state.idea_text`.

### Phase 4 — Structural questions

These determine the *shape* of the API output:

1. **`api_kind`** — `rest | graphql | grpc | mixed | none`.
   - Derived from `PRD.technical_constraints.runtime_platform` and
     `UX.surface_family`:
     - `runtime_platform: cli` AND `surface_family: cli` →
       strongly recommend `none`
     - `surface_family: web | mobile | mixed` → strongly recommend
       `rest`
     - Server / browser_extension / desktop with backend → ask the user
   - Always surface the recommendation as `⚠ inferred` position-1
     option; user must confirm or pick another.

2. **(only if `api_kind == none`)** Capture `rationale` (one sentence)
   and **skip to Phase 7**. Write a minimal `API.yaml` with
   `api_kind: none`, `rationale`, empty `resource_inventory`, no
   `API__*.yaml` files. Coverage + entity-link checks are skipped.

3. **`transport_styles`** — multi-select from `rest, graphql, grpc,
   websocket, server_sent_events, webhooks_out`. Pre-fill: `[rest]` is
   the default when `api_kind: rest`; offer `websocket` or
   `server_sent_events` if any UX surface mentions real-time updates.

4. **(only if `transport_styles` includes `websocket`,
   `server_sent_events`, or `webhooks_out`)** Promote theme
   `events_async` to required.

Persist these to state under `api_kind:`, `rationale:`,
`transport_styles:` before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme**. Same rules as `sdlc:prd`
and `sdlc:ux`:

- `✓ found` items can be batch-accepted with `ok`.
- `⚠ inferred` items must be confirmed or corrected one by one. No
  batch-acceptance. **This is the hallucination guard.**

Write confirmed values to state with the right `_confidence` value:
`confirmed` (explicit pick or typed answer) or `inferred` (`⚠`
accepted as-is).

### Phase 6 — Theme interview

Walk the themes in this order (canonical order from
`api-questions.yaml`):

1. `api_kind_and_styles` — required (asked in Phase 4 above).
2. `versioning` — required.
3. `auth` — required.
4. `errors` — required.
5. `pagination` — required.
6. `idempotency` — required.
7. `rate_limiting` — required.
8. **`resource_inventory`** — required, `synthesis: true`. CRITICAL tier.
   Per-item drill-down (see `references/resource-discovery.md`). Build
   the inventory of resources and trace each to PRD features + UX
   surfaces + a DATA entity.
9. **`events_async`** — `required_if: transport_styles includes
   websocket | server_sent_events | webhooks_out`.
10. **`per_resource_deepdive`** — required, `synthesis: true`.
    CRITICAL tier. For each resource defined in theme 8, run a
    per-resource mini-interview that fills out the per-resource yaml
    (endpoints, DTO schemas, primary_entity, traces).
11. `external_dependencies` — optional (now/skip/todo gate).
12. `sdk_and_clients` — optional (now/skip/todo gate).

Required questions can never be `todo`'d. They must be answered, set to
`null` (writing a note to `api_warnings`), or the user must `EXIT`.

After all themes are addressed, set `suggestion_phase_done: true` in
state.

#### Within a theme: tiered question flow

Same tier mechanics as `sdlc:prd` and `sdlc:ux` — see
`references/interview-mechanics.md` for batch format and
`references/resource-discovery.md` for the `critical` per-resource
state machine.

Tier assignments (set in `api-questions.yaml`):

- Theme 8 (`resource_inventory`) → `critical` per item — every
  resource is examined, named, given a base_path, and traced back to
  PRD features + UX surfaces + a DATA entity.
- Theme 10 (`per_resource_deepdive`) → `critical` per resource — for
  each resource, run the full per-resource mini-interview (endpoints
  / schemas / primary_entity / traces).
- Themes 3, 4, 5, 6 → `high` (agent drafts; user iterates).
- Remainder → `med` (batched 2–4 per `AskUserQuestion` call).

**Read `references/resource-discovery.md` before running theme 8 or 10.**
**Read `references/openapi-embedding.md` before running theme 10.**
**Read `references/async-and-events.md` before running theme 9.**

The two non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended
   option** in their `AskUserQuestion` call. They cannot be silently
   accepted — the user must explicitly pick or correct.
2. State is written after **every confirmed batch, every mini-section,
   and every per-resource deep-dive completion**.

#### Conditional promotions (`required_if`)

Some questions in `api-questions.yaml` are conditionally required:

| Question / theme | Becomes required when |
|---|---|
| `api_kind_and_styles.rationale_for_none` | `api_kind == 'none'` |
| `api_kind_and_styles.transport_styles` | `api_kind != 'none'` |
| `events_async` (whole theme) | `transport_styles` includes `websocket`, `server_sent_events`, or `webhooks_out` |
| `pagination.default_page_size`, `max_page_size` | `pagination.strategy != 'none'` |
| `pagination.stable_sort_field` | `pagination.strategy == 'cursor'` |

Re-evaluate at the start of each new theme batch.

### Phase 7 — Write & validate

Write or merge `docs/API.yaml` and write every
`docs/API__<resource>.yaml` in one consistent batch (so that the
resource inventory and the per-resource files always agree).

When writing, (re)write `metadata.upstream_provenance`: one entry per upstream
artifact consumed this run (`docs/PRD.yaml`, `docs/UX.yaml`,
`docs/DATA-MODEL.yaml`), each `{file, session_id, last_updated, sha256}` with
`sha256` from `docs/INDEX.yaml.generated_from` (else `sha256(bytes)[:16]`).
Replace-on-write (not append-only). See CLAUDE.md §7.

Then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/API.yaml
```

The validator also walks `docs/API__*.yaml` siblings and runs three
checks (all skipped when `api_kind: none`):

1. **Feature coverage**: every PRD `must_have_features` `FR-NNN` must
   appear in some resource's `traces_prd_features` OR in
   `API.yaml.non_api_features`. Uncovered features are appended to
   `api_warnings` and force `status: draft`.
2. **Surface coverage**: every data-bearing UX surface (see
   `references/merge-validate.md` for the type list) must appear in
   some resource's `traces_ux_surfaces`. Uncovered surfaces force
   `status: draft`.
3. **Entity-link check**: every `primary_entity` value must exist in
   `DATA-MODEL.yaml.entities`. Unresolved entities force
   `status: draft`. Skipped if `DATA-MODEL.yaml` is absent (with a
   warning).

For full merge logic and the exit-code recovery flow, see
`references/merge-validate.md`.

When writing files: inline YAML comments on top-level keys, updated
`metadata.last_updated` and `metadata.session_id`.

Set `metadata.status`:
- `"complete"` — only when all required fields are filled, the validator
  passes with `[OK]`, AND all three checks pass (or are skipped due to
  `api_kind: none`).
- `"draft"` — on early EXIT, when any required field is null, or when
  any check fails.

### Phase 8 — CLAUDE.md pointer & complete

On successful validation (`[OK]` or `[DRAFT]`), call
`set_claude_md_pointer.py` to inject or update this skill's bullet
inside the shared `## SDLC Documents` section of the project root
`CLAUDE.md`. Create `CLAUDE.md` with the section if missing.

Bullet format (the pointer script produces this exact text):

```
- `docs/API.yaml` (+ `docs/API__<resource>.yaml`): API contract — endpoints, request/response DTOs (projecting DATA entities), auth, errors, events. Load when implementing endpoints, clients, or SDKs. Last updated by `sdlc-api` on <ISO-8601 timestamp>.
```

For the bullet detection rule and append behavior, see
`references/merge-validate.md`.

After the CLAUDE.md write succeeds: set `status: complete` in the state
file (keep the file — audit trail), then **refresh the navigation
index** (`python .claude/sdlc/docs_index.py`; no-op if the project never
ran `/sdlc:setup` — the freshly-installed hook isn't active until the
next session, so the explicit refresh keeps `INDEX.yaml` current now).
Close by telling the user where the artifacts live and what comes next:

> API contract complete. Next: `/sdlc:arch` (system architecture; it
> consumes `docs/API.yaml` and warns if it's absent — yours is now in
> place).

## Session state file

Path: `.claude/skills-state/sdlc-api.state.yaml`

Schema (extends the baseline state schema from CLAUDE.md):

```yaml
session_id: <uuid4 string>
skill_version: "1.1"
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted

# Phase 4 — structural answers (mirror API.yaml top-level)
api_kind: null              # rest | graphql | grpc | mixed | none
rationale: null             # populated only when api_kind == "none"
transport_styles: []        # populated only when api_kind != "none"

idea_text: null             # optional extra context user typed in Phase 3
pre_fill_confirmed: false
suggestion_phase_done: false
completed_themes: []
skipped_themes: []
todo_themes: []
pending_themes: []
current_theme: null
current_resource: null      # which resource_id is mid-deepdive (theme 10)

# Per-family ID counters (single-product mode). Each entry is the
# last-assigned integer for that family — increment, format as
# <PREFIX>-{:03d}, then persist. This skill emits two families:
#   WRN — api_warnings entries.
#   OPR — per-endpoint stable id (lives on each endpoint as `id`).
last_ids: {}                # e.g. {WRN: 3, OPR: 17}

# Per-product ID counters (monorepo mode only). Same shape as last_ids,
# keyed by product slug. Each product carries an independent WRN/OPR id space.
last_ids_by_product: {}     # e.g. {billing: {WRN: 1, OPR: 8}, notifications: {WRN: 0, OPR: 3}}

# Resource registry — one entry per defined resource
defined_resources:          # extension over the baseline state schema
  - resource_id: <kebab>
    base_path: </v1/...>
    status: defined          # defined | draft | confirmed
    file_path: docs/API__<slug>.yaml
    primary_entity: null     # PascalCase DATA entity NAME; set during theme 8
    traces_prd_features: []  # FR-NNN ids; set during theme 8
    traces_ux_surfaces: []   # SCR-NNN ids; set during theme 8
    traces_prd_workflows: [] # WKF-NNN ids; optional; set during theme 8

dropped_resource_candidates: []   # records of dropped candidates (so resume
                                  # doesn't re-propose)

partial_answers: {}         # mirrors API.yaml structure incrementally
partial_resources: {}       # mirrors per-resource yamls incrementally,
                            # keyed by resource_id
```

Rules:

- Generate `session_id` as a UUID4 on first creation.
- Update `last_updated` on every write.
- Write the file **after every confirmed batch** and **after every
  per-resource deep-dive completion**.
- On user `EXIT`: set `status: aborted`, write current
  `partial_answers` and `partial_resources`, confirm to user, stop.
- On Phase 8 completion: set `status: complete`, keep the file.
- The validator ignores this file — it validates only `docs/API.yaml`
  and the resource yamls.

**Source of truth on resume:**

- `docs/API.yaml` + the existing `docs/API__*.yaml` files (if present)
  are the on-disk source of truth for *answers*.
- The state file is the source of truth for *interview progress*.
- On resume: load the on-disk yamls first as the baseline, then layer
  `partial_answers` and `partial_resources` on top.
- If they conflict on the same key, ask the user which to keep —
  never silently overwrite.

## Edge cases

For unusual situations (PRD/UX/DATA missing or in draft, surface with
no obvious resource, DATA entity deleted mid-session, conflicting auth
across resources, mid-interview transport_style change, validation
failures, write-permission errors, very large APIs, monorepo mode) →
`references/edge-cases.md`.

## Style of conversation

The interview can be long, especially for products with many resources.
Keep it humane:

- Use the user's terminology as soon as they introduce it.
- Keep `AskUserQuestion` batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme boundary
  (*"Auth done — next: errors. RFC 7807 envelope strongly recommended."*).
- For theme 10 (per-resource deep-dive), announce each resource before
  diving in (*"Now: `users` resource (5 endpoints expected, primary
  entity User)."*).
- Always make multiple-choice the path of least resistance.
- For the `resource_inventory` and `per_resource_deepdive` themes,
  explicitly call out that candidates were synthesized from DATA + PRD
  + UX — don't pretend they came from nowhere.
- After all themes are done, congratulate the user briefly and move to
  write/validate. Do not repeat everything back at them.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 framing summary. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs it to `api_warnings`. |

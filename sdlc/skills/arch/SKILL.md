---
name: arch
description: >
  Explicitly invoked skill. Two modes: (a) /sdlc:arch — system architecture
  (pattern + container inventory + cross-container edges) written to
  docs/ARCH.yaml; (b) /sdlc:arch <container> — per-container deep-dive
  (tech stack, deployment, components, internal edges) written to
  docs/ARCH__<container>.yaml. A third form, /sdlc:arch -d [<container>],
  re-derives the typed edge graph from API.yaml + DATA-MODEL.yaml + UX.yaml
  without re-running the interview. A fourth form, /sdlc:arch --next,
  auto-advances: it resolves to system mode when no ARCH.yaml exists, to the
  next not-yet-drilled container otherwise, and reports completion once every
  drillable container has its file. Trigger only on /sdlc:arch or a direct
  natural-language request to start the architecture skill — never
  auto-trigger from generic architecture chatter. Reads docs/PRD.yaml,
  docs/UX.yaml (+ UX__*), docs/DATA-MODEL.yaml as required preconditions
  and refuses to run if any of these is missing or its metadata.status !=
  complete. docs/API.yaml (+ API__*) is optional — absent means a warning
  is shown before anything else and the user confirms whether to continue.
user-invocable: true
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read Write(CLAUDE.md) Write(docs/ARCH.yaml) Write(docs/ARCH__*.yaml) Write(.claude/skills-state/sdlc-arch.state.yaml) Write(.claude/skills-state/sdlc-arch.derivation-report-*.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-arch

Guides the user through a structured interview that produces a validated
`docs/ARCH.yaml` (system architecture: pattern, container inventory, identity
and auth strategy, cross-container edges) plus one
`docs/ARCH__<container>.yaml` per container (per-container deep-dive: tech
stack, deployment, observability, ownership, internal components and edges).
Downstream agents — `test`, `task`, `deploy` — consume these artifacts to
generate test strategies, implementation tasks, and deployment configs.

## What this skill does (at a glance)

The skill runs in **one of three modes**, dispatched on the invocation form —
plus a `--next` resolver that picks the right mode for you:

| Invocation                  | Mode                      | Output                                  |
|-----------------------------|---------------------------|------------------------------------------|
| `/sdlc:arch`                | system interview          | `docs/ARCH.yaml`                         |
| `/sdlc:arch <container>`    | container interview       | `docs/ARCH__<container>.yaml`            |
| `/sdlc:arch -d`             | edge re-derivation, system| `docs/ARCH.yaml` (edges only)            |
| `/sdlc:arch -d <container>` | edge re-derivation, one   | `docs/ARCH__<container>.yaml` (edges only)|
| `/sdlc:arch --next`         | resolver → one of the above| (whatever the resolved form produces)   |

Interview modes follow the canonical 8-phase flow (see "Phase 1 — Resume
check" through "Phase 8 — CLAUDE.md pointer & close" below). The `-d` mode
skips the interview and runs only edge derivation + confirmation.

State is persisted **after every confirmed batch and after every per-item
deep-dive**, so the user can `EXIT` at any time without losing progress.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `arch-questions.yaml` | Question inventory; each theme tagged with `mode: system | container`. |
| `ARCH.schema.yaml` | Human-readable canonical schema for `docs/ARCH.yaml`. |
| `ARCH__CONTAINER.schema.yaml` | Human-readable canonical schema for `docs/ARCH__<container>.yaml`. |
| `validate_schema.py` | Pydantic v2 validator (ARCH.yaml + every ARCH__*.yaml + 4 cross-checks). |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector, called in Phase 8. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, EXIT semantics, importance-tier flows. Read on entering Phase 6. |
| `references/container-discovery.md` | How to seed the container inventory from PRD + UX + DATA + API. Read in Phase 3 of system mode. |
| `references/component-discovery.md` | How to seed components from API resources + UX surfaces owned by a container. Read in Phase 3 of container mode. |
| `references/edge-derivation.md` | How API + DATA + UX seed the typed edge graph; -d mode rules. Read at Phase 6's edge-synthesis theme and at every -d invocation. |
| `references/pattern-selection.md` | Narrative pattern guidance. Load with the YAML matrix. |
| `references/pattern-selection.yaml` | Trimmed matrix: pattern × {best-when, tradeoffs, disqualifiers, ai-builder-considerations}. |
| `references/container-taxonomy.yaml` | Container archetypes × {aliases, common-responsibilities, suggested-components}. |
| `references/component-taxonomy.yaml` | Component archetypes × {aliases, typical-responsibilities, typical-edges}. |
| `references/merge-validate.md` | Merge logic for existing artifacts, the 4 cross-checks, CLAUDE.md pointer rules. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations and their handling. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/ARCH.yaml` (project root) | System-level output artifact. |
| `docs/ARCH__<container>.yaml` (project root) | Per-container output artifact. |
| `.claude/skills-state/sdlc-arch.state.yaml` | Session state for resumability. |
| `.claude/skills-state/sdlc-arch.derivation-report-<ISO8601>.yaml` | Optional report after a -d run. |
| `CLAUDE.md` (project root) | Pointer bullet injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the free-text
field of any `AskUserQuestion` call to abort. State is *always* saved after
each confirmed batch — `EXIT` simply marks the session `status: aborted`
and stops.

There is no `SAVE` command — saving is implicit.

## Invocation dispatch

After reading the `$ARGUMENTS` string, classify the invocation.

**`--next` resolver (runs before the classification below).** If the first
token is `--next` (no other positional args), resolve it to one of the concrete
forms, then proceed exactly as that form:

1. **An in-progress sub-session exists** (any `sessions[*]` with
   `status: in_progress`) → resume it. `--next` means "continue the
   architecture work"; never skip past unfinished work. Phase 1 handles the
   resume prompt.
2. **No `docs/ARCH.yaml`** (or it has no `containers`) → resolve to **system
   mode** (as if `/sdlc:arch`).
3. **`docs/ARCH.yaml` exists with a drillable container that is drilled but
   INTERNALLY INCOMPLETE** → resolve to **container mode** to *resume its
   deep-dive* (as if `/sdlc:arch <container_id>`), announcing it as "drilled but
   incomplete". "Drilled" must mean *internally complete*, not merely
   *file-exists*: a `docs/ARCH__<cid>.yaml` that exists but has
   `metadata.status != complete`, OR that the validator flags with a work_unit
   integrity (#21) or FR→work_unit coverage (#22) error, is **not** done — it is
   the exact state two successive backfill passes ended in silently. Detect it by
   running `python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/ARCH.yaml`
   and reading its output: a container whose file is draft, or that appears in a
   "cross-check 21" / "cross-check 22" error line, is incomplete. Resume the
   first such container in **drill order** (below).
4. **`docs/ARCH.yaml` exists with a drillable container still UNDRILLED** →
   resolve to **container mode** for the next one (as if
   `/sdlc:arch <container_id>`). A container is **drillable** if container mode
   would actually author a file for it: `external: false` AND `archetype` not in
   the storage/infra set (`primary-database`, `secondary-database`, `cache`,
   `blob-store`, `search-index`, `message-bus`) AND not `external-service` —
   exactly the set container mode aborts on (see `references/edge-cases.md` →
   "External / data-store containers"). A drillable container is **undrilled**
   if it has no `file_path` and no `docs/ARCH__<container_id>.yaml` on disk.
   Pick the first undrilled drillable container in **drill order** (below).
5. **Every drillable container has its `ARCH__<container>.yaml` AND each is
   internally complete** (status complete, no #21/#22 error) → print and abort:
   > "All containers are already specified. To change one explicitly, invoke
   > `/sdlc:arch <container-name>`. Otherwise the architecture is fully
   > specified — go on with `/sdlc:test`."

   Do NOT reach this message while any drilled file is draft or carries a #21/#22
   error — that is rule 3's "drilled but incomplete", which must be resumed first.

Before launching a resolved container interview, confirm the target with one
`AskUserQuestion` so `--next` never silently drops the user into a long
interview:
> "`<k>` of `<n>` drillable containers fully specified. Next: `<id>`
> (`<archetype>`) — `<undrilled ⇒ start | drilled but incomplete ⇒ resume its
> deep-dive>`. Start it, pick a different container, or stop?"

Options: `"Start <id>"` / `"Pick another"` / `"Stop"`. On "Pick another", list
the remaining undrilled drillable container_ids and let the user choose. On
"Stop", exit cleanly without changing state.

**Drill order.** When several drillable containers are undrilled, author them
dependency-first so cross-container external edges can resolve to real
components: order by ascending count of outgoing `depends_on` + `calls` edges
in `ARCH.yaml.edges` (dependencies before dependents), tie-broken by
`ARCH.yaml.containers[]` definition order. On a dependency cycle or no edges,
fall back to plain definition order. This is a soft quality heuristic, not a
correctness requirement — `-d` mode re-derives edges afterward regardless of
the order chosen. Persist the resolved order to
`state.sessions.system.drill_order` so `--next` is deterministic across
sessions; recompute it only when the container set changed.

`--next` does not combine with `-d`: `/sdlc:arch -d --next` (either order) is an
unknown-flag error (rule 4 below).

Otherwise, classify a non-`--next` invocation:

1. **`-d` (or `--dependencies`) first token** → **edge-derivation mode**.
   - `/sdlc:arch -d` → re-derive cross-container edges in `docs/ARCH.yaml`.
   - `/sdlc:arch -d <container>` → re-derive internal edges in
     `docs/ARCH__<container>.yaml`. `<container>` must exist in
     `ARCH.yaml.containers[].container_id`; if not, list valid container_ids
     and abort.
   - Skip to **Phase 7-D** (edge derivation).
2. **No arguments** → **system interview mode**. Output: `docs/ARCH.yaml`.
3. **One argument that is not `-d`** → **container interview mode**.
   The argument is interpreted as a `container_id`. It MUST exist in
   `ARCH.yaml.containers[].container_id`; if not, list valid container_ids
   and abort.
   Output: `docs/ARCH__<container>.yaml`.
4. **More than one positional argument, or unknown flag** → print
   the four valid invocations and abort.

The skill **never** modifies a different mode's output. Container mode
will not touch `docs/ARCH.yaml` — except two narrow, mechanical writes:
setting `containers[<id>].file_path` on first completion, and **appending
system edges its external_edges imply** (the roll-up rule S6 — the
validator's cross-check #24 blocks `complete` while a container-sourced
edge has no system row; see `references/edge-derivation.md` → "Roll-up at
container-mode write"). System mode will not touch any `docs/ARCH__*.yaml`.
Cross-references go through the state file plus the already-on-disk
artifacts read at Phase 2.

## Pre-flight API check (runs before everything else)

Before the resume check (Phase 1), do one filesystem lookup:

```bash
ls docs/API.yaml 2>/dev/null
```

**If `docs/API.yaml` is absent**, immediately show this message via `AskUserQuestion` before reading any other input:

> ⚠ No API spec found (`docs/API.yaml` is missing). Is this a project without an API layer? If not, please abort and run `/sdlc:api` first.

Options: `"Yes, this project has no API — continue"` / `"No — I need to abort and run /sdlc:api first"`.

If the user chooses to abort, stop immediately. If they confirm no API, record `api_present: false` in the active sub-session state and continue to Phase 1.

**If `docs/API.yaml` is present**, record `api_present: true` and proceed directly to Phase 1 with no message.

## The 8-phase flow (interview modes)

The phases are the same for both system mode and container mode, but the
themes differ. The mode-specific themes are listed at the end of the
relevant phase under **System themes** / **Container themes**.

### Phase 1 — Resume check

Check for `.claude/skills-state/sdlc-arch.state.yaml`:

- If it exists with `status: in_progress` and the same **mode** as the
  current invocation (and, for container mode, the same `container_id`),
  ask:
  > "I found an unfinished sdlc:arch session (`<mode>` mode<, container=X>) from
  > `<last_updated>`. Would you like to **resume**, **restart** (discard previous
  > answers), or **discard** (delete state and exit)?"
- If `status: in_progress` but a *different* mode/container is requested,
  warn the user and offer to start a new session alongside the existing one.
  The state file holds a `sessions:` map keyed by `mode|container_id` —
  multiple modes can live in the same file (see "Session state file").
- If `status: complete` or `aborted` and the target output yaml exists, treat
  this as an update flow — see `references/merge-validate.md`. In container mode,
  re-validate the existing `docs/ARCH__<cid>.yaml` first: if it is on-disk
  `complete` but the validator flags a work_unit (#21) or FR→work_unit (#22)
  error, it is **drilled but incomplete** — say so and resume the deep-dive
  (fill the missing `work_units` / push each FR to a callable / record a
  `work_units_waiver`) rather than treating it as finished.
- If no state file, continue to Phase 2.

### Phase 2 — Scan inputs

The architecture skill never re-asks anything already in the upstream
artifacts. Read them once at startup and validate each via its upstream
skill's validator.

**Slice large docs, don't slurp.** `arch` reads the most upstream context of
any skill — `PRD.yaml` (1000+ lines) and especially `DATA-MODEL.yaml` (commonly
several thousand). If `docs/INDEX.yaml` exists (the project ran `/sdlc:setup`),
read these by slice: look an entity/FR/section up in `INDEX.yaml` (or
`python .claude/sdlc/docs_index.py --show <symbol>`) and `Read` only its
`[start, end]` range; resolve a whole block via its `sections.<file>.<key>`
range. Validate each upstream file with its validator (below), then pull only
the slices you actually need — do not load `DATA-MODEL.yaml` whole to find a few
store ids or entity names. Fall back to whole-file reads when `INDEX.yaml` is
absent. Protocol: `.claude/rules/sdlc-docs-access.md`.

Required upstream artifacts (all three MUST exist with `metadata.status:
complete`):

1. `docs/PRD.yaml` — validated via `python sdlc/skills/prd/validate_schema.py --path docs/PRD.yaml`.
2. `docs/UX.yaml` + every `docs/UX__*.yaml` — validated via `python sdlc/skills/ux/validate_schema.py --path docs/UX.yaml`.
3. `docs/DATA-MODEL.yaml` — validated via `python sdlc/skills/data/validate_schema.py --path docs/DATA-MODEL.yaml`.

If any validator exits non-zero, or any artifact has `metadata.status !=
complete`, **stop**. Print a clear message naming the offending file and
the upstream skill the user should run.

Optional upstream artifact:

4. `docs/API.yaml` + every `docs/API__*.yaml` — validated via `python sdlc/skills/api/validate_schema.py --path docs/API.yaml`. Only read and validate if `api_present: true` (set in the pre-flight check). If absent, API-sourced pre-fills are simply skipped; note the absence in `arch_warnings` (WRN-NNN).

**Read `PRD.conventions` (if present).** The PRD may carry a binding
`conventions` block. Honour it before writing anything:

- `conventions.artifact_ids` — tells you which ID families exist and
  what each prefix means. Consult it before emitting or referencing any
  `FR-NNN` / `WKF-NNN` / `WRN-NNN`; never invent an id in an upstream
  family, never renumber one.
- `conventions.nfr_propagation` (or similar) — may map specific NFR
  fields to the downstream decisions they must drive. If it names
  arch-level decisions (pattern choice, scaling, deployment shape),
  treat those mappings as inputs to Phase 4, not as free choices.
- Any other bucket whose `binding: true` — surface it and respect it.

**Monorepo handling (v1.0):** if `PRD.metadata.monorepo: true` AND
`PRD.products` is non-empty, the skill stops and warns that
multi-product mode is deferred to a future version. The user may
proceed against one product at a time in single-product mode (a warning
is appended to `arch_warnings`). See `references/edge-cases.md` →
"Monorepo mode — DEFERRED to a future major version".

**System mode** additionally reads:
- existing `docs/ARCH.yaml` (merge baseline).
- existing `docs/ARCH__*.yaml` files (read-only — to seed the container set
  if `ARCH.yaml` is missing or empty).
- `README*`, `architecture.*`, `design.*`, any existing diagrams under
  `docs/` for hints.

**Container mode** additionally reads:
- `docs/ARCH.yaml` (REQUIRED — the `<container>` argument is validated
  against it).
- existing `docs/ARCH__<container>.yaml` (merge baseline).

For both modes, build the **pre-fill map** classifying each candidate as
`✓ found` (direct quote from upstream) or `⚠ inferred` (derived).
Inferred items are the hallucination guard and must be confirmed one by
one in Phase 5.

For *what* to pre-fill from which upstream field, see
`references/container-discovery.md` (system mode) and
`references/component-discovery.md` (container mode).

**Upstream-change detection (re-runs).** If the active mode's output already
exists and carries `metadata.upstream_provenance`, this is a re-run: for each
upstream artifact (`docs/PRD.yaml`, `docs/UX.yaml`, `docs/DATA-MODEL.yaml`, and
`docs/API.yaml` when `api_present`), compare the recorded `sha256` to its
current hash (from `docs/INDEX.yaml.generated_from[<file>]`, else
`sha256(bytes)[:16]`). For every changed upstream, classify the delta
(added / removed / modified ids) and run the **delta-review pass before the
theme interview** per `sdlc/skills/ux/references/upstream-reconciliation.md`
(CLAUDE.md §7). System mode compares against `ARCH.yaml`'s provenance; container
mode against the specific `ARCH__<container>.yaml`'s — so a container drilled
long after the system interview is reconciled against whatever upstream state
*it* was built on. If every upstream is unchanged, proceed to the merge flow
without a delta-review. Fresh outputs skip this step. See also
`references/edge-cases.md` → "When an upstream changes after ARCH exists".

### Phase 3 — Inventory seeding (mode-specific)

Architecture is fundamentally about decomposition. Both modes start by
proposing a draft inventory so the user can correct early.

**System mode — container inventory:**

Source candidates, in priority order:

1. **API.yaml + API__*.yaml** — every `api_kind != none` API implies a
   backend container. Resources grouped by `tags` or by `bounded_context`
   hint at multiple backend services. Tag `✓ found`. **Skip if
   `api_present: false`** (no API layer confirmed in pre-flight check).
2. **UX.yaml.surface_family** — `web | mobile | desktop | cli |
   browser_extension | mixed` → frontend container(s). Tag `✓ found`.
3. **DATA-MODEL.yaml.persistence.*_stores** — every store ≈ a candidate
   container (database, cache, blob store, search index). Tag `✓ found`.
4. **PRD.functional_requirements** — FR-NNN features mentioning scheduled
   work, batch ingestion, ETL, notifications, AI agents, third-party
   integrations → worker / scheduler / integration containers. Tag
   `⚠ inferred`.
5. **PRD.security_compliance.auth_model** — `oauth2`/`sso` →
   identity-provider container (external by default, internal only if PRD
   says so). Tag `⚠ inferred`.

Present the draft. Each `⚠ inferred` candidate gets its own AskUserQuestion
call. Persist confirmations to `state.sessions[system].defined_containers`.
Record the `FR-NNN` that seeded each operational candidate (Pass 4) so it
becomes the container's `implements_requirements` in Phase 6 — this is the
only place an API-less feature (e.g. a nightly job) becomes traceable.
`container_inventory` is a `critical synthesis: true` theme: after the
per-item loop closes in Phase 6, run the **scope-completeness sweep**
(seed from ALL upstream ID families). See
`references/container-discovery.md` for the full algorithm + the sweep.

**Container mode — component inventory:**

Source candidates, in priority order:

1. **API__<resource>.yaml files owned by this container** — each resource
   maps to one component by default (e.g. `users` resource →
   `users-controller` + `users-service` + `users-repository`, or a single
   `users` component if the user prefers a flat layout). Tag `✓ found`.
2. **UX__<surface>.yaml files owned by this container** (frontend
   containers only) — each surface ≈ a view component. Tag `✓ found`.
3. **Container archetype** (from system mode → container-taxonomy) —
   suggested components per archetype (e.g. `backend-api` →
   routing/auth-middleware/repository-layer/use-cases). Tag `⚠ inferred`.
4. **DATA persistence bindings** — if this container binds to redis or
   blob store, propose `cache-client` / `blob-client` components. Tag
   `⚠ inferred`.
5. **Build-time deliverables named in claimed FRs** — schema/model layers,
   repo `tools/` validators, `templates/`, shipped content packs → propose
   `schema_model` / `dev_tool` / `content_asset` components whose
   `code_location` covers the FR-named paths (see
   `references/component-discovery.md` → Pass 6). Runtime-only seeding
   misses this class entirely. Tag `⚠ inferred`.

Present the draft as in system mode. Persist to
`state.sessions[container|<id>].defined_components`. `component_inventory`
is also a `critical synthesis: true` theme — run the scope-completeness
sweep after the per-item loop. See `references/component-discovery.md`.

### Phase 4 — Structural questions

Mode-specific scalars that determine the *shape* of the output:

**System mode:**

1. **`architecture_pattern.pattern`** — one of: `monolith | modular_monolith
   | microservices | event_driven | hexagonal | serverless | plugin |
   pipeline | other`. Pre-fill heuristics from PRD:
   - `non_functional_requirements.scalability ∈ {large, hyperscale}` →
     `microservices | event_driven` candidates.
   - Single small team + simple domain → `monolith | modular_monolith`.
   - Many event-y features in PRD (notifications, queues, ETL) →
     `event_driven`.
   Present as `⚠ inferred` recommendation; load
   `references/pattern-selection.yaml` and `pattern-selection.md` to
   surface the 2–3 top candidates with `best-when` / `tradeoffs`.
2. **`identity_and_auth.identity_provider`** — `external_oidc | internal |
   none`, and `token_strategy` — `jwt | session | api_key | mtls | none`.
   Pre-fill from `PRD.security_compliance.auth_model` and
   `API.auth.schemes`.

**Container mode:**

1. **`tech_stack.language` + `framework` + `runtime_version`** — pre-fill
   from `PRD.technical_constraints.runtime_platform` /
   `preferred_languages`. Show as `⚠ inferred`.
2. **`deployment.shape`** — `container | serverless | static | managed_service
   | long_running_service | scheduled_job`. Pre-fill from container archetype.

Persist all structural answers to state before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme**. Same rules as `sdlc:prd` and
`sdlc:api`:

- `✓ found` items can be batch-accepted with `ok`.
- `⚠ inferred` items must be confirmed or corrected **one by one** in
  their own AskUserQuestion call. No batch-acceptance. This is the
  hallucination guard.

Write confirmed values to state with `<field>_confidence: confirmed` (explicit
pick) or `inferred` (`⚠` accepted as-is).

### Phase 6 — Theme interview

Walk the themes in the order defined by `arch-questions.yaml`. Themes are
tagged with `mode: system | container`; load only the themes for the active
mode.

#### System themes (when `/sdlc:arch` was invoked)

1. `architecture_pattern` — `high` (asked in Phase 4 as a structural scalar;
   theme adds rationale + tradeoff_notes + ai_builder_notes).
2. `identity_and_auth` — `high` (same).
3. `container_inventory` — `critical` per item, `synthesis: true`. For each
   container: archetype, purpose, `owns_api_resources`, `owns_ux_surfaces`,
   `persistence`, `implements_requirements` (FR-NNN features **and** NFR-NNN
   non-functionals the container is the home of), `traces_prd_workflows`
   (WKF-NNN), `deployment_unit`, ownership, change_cadence. Each container's
   status walks `defined → draft → confirmed`. After the per-item loop,
   run the scope-completeness sweep (see `references/container-discovery.md`).
   Every PRD must-have `FR-NNN` must end up in some container's
   `implements_requirements` or in `non_container_features` — Phase 7's
   feature-coverage check enforces this.
4. `cross_container_edges` — `critical` synthesis. The agent derives the edge
   graph from API + DATA + UX (see `references/edge-derivation.md`), then
   presents it for confirmation/edit. **The user is never asked to enumerate
   edges from scratch** — derivation is the path of least resistance.

#### Container themes (when `/sdlc:arch <container>` was invoked)

1. `tech_stack` — `high` (asked in Phase 4 as a structural scalar; theme
   adds package_manager, build_tool, key_libraries).
2. `persistence_bindings` — `med` (pre-filled from system-level
   `containers[id].persistence`). User confirms or refines.
3. `deployment` — `high` (asked in Phase 4 as a structural scalar; theme
   adds scaling, regions, replicas, scheduling).
4. `observability` — `med` (logs / metrics / traces / alerts).
5. `ownership` — `med` (team, change_cadence, on_call_rotation).
6. `failure_modes` — `high` per item.
7. `security_concerns` — `med`.
8. `component_inventory` — `critical` per item, `synthesis: true`. Run the
   scope-completeness sweep after the per-item loop (see
   `references/component-discovery.md`).
9. `per_component_deepdive` — `critical` per component. Mirrors
   `sdlc:api`'s `per_resource_deepdive`: for each component, an interview
   fills `component_id`, `archetype`, `purpose`, `responsibilities`,
   `code_location`, `work_units`, `inputs`, `outputs`, `failure_modes`,
   `traces_api_resources` / `traces_ux_surfaces` / `traces_data_entities`,
   and `implements_requirements` (FR-NNN / NFR-NNN) / `traces_prd_workflows`
   (WKF-NNN) where applicable. A component's `implements_requirements` must
   be a subset of its parent container's. `code_location` (the component →
   code-module seam) is drafted from the component's archetype + the
   container's source layout (`importance: high` mini-section); downstream
   `task` grounds each task's `target_files` in it, so don't leave it vague
   for non-trivial components. `work_units` (the component → code seam) is the
   list of named method/function-level **callables** this component exposes,
   drafted per archetype (`importance: high`): one per owned API operation /
   entity CRUD verb / behaviour the responsibilities imply — enumerate the
   PUBLIC / contract-bearing callables (not every private helper), each with a
   `name` (the callable, unique within the component — no id family) + `summary`
   (+ optional traces and a defer-or-declare `inputs`/`output`/`raises`/
   `signature` contract). Downstream `task` slices **exactly one atomic task per
   work_unit** (its `target_symbol` = the work_unit name), so a component with no
   work_units yields no implementation task. See
   `references/component-discovery.md` → "Deriving code_location" and
   "Deriving work_units".
   **Emit work_units block-style** — one field per line under each `- name:`
   entry; do NOT write flow-style one-liner mappings (`- {name: x, summary: y}`).
   Block-style is diff-reviewable and robust to any line-oriented tooling
   downstream. On an update flow, normalize any existing flow-style entries you
   encounter to block-style. **Non-trivial components must not be left unbacked:**
   a component whose archetype is outside the plumbing set
   (`config_loader`/`serializer`/`observability_bootstrap`/`error_handler`) AND
   which carries `implements_requirements` or a traced contract must declare
   `work_units` — or, if it genuinely has none (realized purely by wiring), record
   an explicit `work_units_waiver: <reason>` alongside `work_units: []`. Without
   one, the validator blocks `complete` (cross-check #21) rather than letting
   downstream `task` silently seed no implementation task. **Push every FR down to
   a callable:** each FR-NNN in a component's `implements_requirements` must appear
   in at least one of that component's `work_units[].implements_requirements`
   (cross-check #22) — else `task` has no atomic task that actually builds the
   feature. Waive per component with `work_units_waiver` when an FR is realized
   purely by wiring.
10. `internal_and_external_edges` — `critical` synthesis (see
    `references/edge-derivation.md`). Once components carry `code_location`,
    keep the call graph **layering-legal**: a `calls`/`reads`/`writes` edge
    between *peer* components (same layer / sibling archetype) is realized by
    a runtime composition root, NOT a direct sideways import — retarget it
    through the composing component or flag a `WRN-NNN`. See
    `references/edge-derivation.md` → "Edges vs imports".

#### Tier mechanics

Each question carries an `importance: med | high | critical` field. Tier
flows are identical to `sdlc:api` and `sdlc:data` — see
`references/interview-mechanics.md` for the AskUserQuestion prompts,
iteration caps, and per-item state machines.

The two non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended option**
   in their `AskUserQuestion` call. They cannot be silently accepted.
2. State is written after **every confirmed batch, mini-section, and
   per-item deep-dive completion** — not at theme boundaries.

### Phase 7 — Write & validate

Write or merge the active mode's output yaml:

- System mode → `docs/ARCH.yaml`. Per-container files are NOT created
  here. They are stubs only — referenced from `containers[].file_path`
  if and only if the container has been drilled-down via container mode.
- Container mode → `docs/ARCH__<container>.yaml`. Also, on first
  completion of a container interview, update
  `docs/ARCH.yaml.containers[id].file_path` to point to the new file,
  and bump `ARCH.yaml.metadata.last_updated`. Additionally, when this
  container's `external_edges` imply system edges that `ARCH.yaml.edges`
  lacks, present the missing rows as a confirmation diff and **append**
  them (roll-up rule S6; cross-check #24 blocks `complete` otherwise —
  see `references/edge-derivation.md`). These are the only mutations
  container mode may make to `ARCH.yaml`; it never edits or removes
  existing entries.

When writing, (re)write the active output's `metadata.upstream_provenance`:
one entry per upstream artifact consumed this run (`docs/PRD.yaml`,
`docs/UX.yaml`, `docs/DATA-MODEL.yaml`, and `docs/API.yaml` when present), each
`{file, session_id, last_updated, sha256}` (`sha256` from
`docs/INDEX.yaml.generated_from`, else `sha256(bytes)[:16]`). Replace-on-write
(not append-only). System mode writes it on `ARCH.yaml`; container mode on the
`ARCH__<container>.yaml` it just authored. See CLAUDE.md §7.

Then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/ARCH.yaml
```

The validator validates `docs/ARCH.yaml` plus every sibling
`docs/ARCH__*.yaml` and runs the cross-check suite below (all enabled
in both modes). Coverage, trace, and ID-format failures force
`metadata.status: draft`; the upstream-status and external-container
checks emit warnings only.

**Coverage** (block complete):

1. **API-resource coverage** — every API resource appears in some
   container's `owns_api_resources`.
2. **UX-surface coverage** — every data-bearing UX surface appears in
   some container's `owns_ux_surfaces`.
3. **DATA-store coverage** — every primary/secondary store in
   `DATA-MODEL.yaml.persistence.*` appears in some container's
   `persistence`.
4. **PRD feature coverage** — every PRD `must_have_features` `FR-NNN`
   appears in some container's `implements_requirements` OR in
   `non_container_features`. Skipped if `docs/PRD.yaml` is absent.

**ID-prefix formats** (block complete):

- `WRN-NNN` on every `arch_warnings` entry (system + each container).
- `FR-NNN` or `NFR-NNN` on every `implements_requirements`; `FR-NNN` on
  `non_container_features`.
- `WKF-NNN` on every `traces_prd_workflows`.
- PRD-trace existence: every `FR-NNN`/`NFR-NNN` / `WKF-NNN` resolves to a
  PRD id (FR→functional_requirements, NFR→non_functional_requirements);
  a component's `implements_requirements` ⊆ its parent container's.

**Edge integrity** (block complete):

4. **Edge endpoint integrity** — every edge `to` resolves to an existing
   container (system-level edges) or `<container_id>/<component_id>`
   (container-level external edges) or `<component_id>` (container-level
   internal edges).
5. **Edge via_\* resolution** — every `via_resource_id` / `via_unit`
   (internal edges → a `work_units[].name` on the `to` component) /
   `via_operation_id` (external edges → an API operation) / `via_channel_id` /
   `via_entity` (when set) resolves to an upstream artifact. Typos in `via_*`
   are blocking errors.

**Container/component consistency** (block complete):

6. **Container ↔ system consistency** — `api_surface`, `ux_surface`,
   `persistence_bindings` ⊆ parent container's `owns_*` / `persistence`.
7. **Deployment compatibility** — `deployment.shape` is in the allowed
   set for the parent's `deployment_unit` (see `ARCH__CONTAINER.schema.yaml`).
8. **Component trace integrity** — every `traces_api_resources`,
   `traces_api_operations`, `traces_ux_surfaces`, `traces_data_entities`
   entry on a component resolves to its upstream artifact AND
   (for api/ux) is contained in the parent container's `owns_*`.
9. **`file_path` integrity** — every `containers[].file_path` resolves
   to a file on disk, and every sibling `docs/ARCH__*.yaml` is
   referenced by some `containers[].file_path`.
9a. **Component `work_units` integrity & FR coverage (#21/#22 — block
    `complete`)** — per-unit integrity (unique `name` within the component,
    non-empty `summary`, `traces_api_operation`/`implements_requirements`/
    `touches_entities` subsets), PLUS two coverage gates: **#21** — a
    non-trivial component (non-plumbing archetype carrying
    `implements_requirements` or a traced contract) with **no** `work_units`
    and **no** `work_units_waiver` blocks `complete`; **#22** — every FR-NNN in
    a component's `implements_requirements` must appear in one of that
    component's `work_units[].implements_requirements` (waivable via
    `work_units_waiver`). work_units are read by a real YAML parse (block- or
    flow-style entries both count), never a line-grep.
9b. **Work_unit DEFER-OR-DECLARE contract (#23 — block `complete`)** — a
    work_unit with no `traces_api_operation` must declare ALL of `inputs`,
    `output`, `raises` (explicit empties count: `inputs: []`, `raises: []`,
    `output: "None"`); a unit that traces an API operation may defer to that
    schema. Waiver-aware like #21/#22. This is what stops the emitter from
    filling only trace fields and leaving every interface contract empty.
9c. **Container→system edge roll-up (#24 — block `complete`)** — every
    container file's `external_edges[]` entry must have a corresponding
    `ARCH.yaml.edges` row ({from: that container, to: target container,
    same type}). Container mode appends missing rows at Phase 7 (with
    confirmation); system `-d` proposes them as ADDs (rule S6).

**Non-blocking warnings**:

10. **External-container files** — if an `ARCH__<id>.yaml` exists for a
    container with `external: true`, the validator warns (file should
    not exist).
11. **Upstream status awareness** — if any of `PRD.yaml` / `UX.yaml` /
    `DATA-MODEL.yaml` / `API.yaml` has `metadata.status != "complete"`,
    the validator emits a warning. (The skill itself refuses to run in
    that case, but a downstream agent re-running the validator alone
    will see the warning.)
12. **Component `code_location` coverage** — a non-trivial component
    (non-plumbing archetype, carrying at least one trace) with no
    `code_location` emits a warning: downstream `task`/codegen will have to
    infer its file placement. Non-blocking (placement can be deferred), but
    filling it is what makes autonomous downstream codegen hold.
13. **Component `work_units` waiver notice** — a non-trivial component that
    declares no work_units but records a `work_units_waiver` is surfaced as a
    non-blocking warning (so a reviewer sees the waiver), and the container-level
    "FR(s) unreachable through any work_unit" roll-up is printed as advisory
    context. The blocking half of #21/#22 lives in item 9a above. A `calls`
    internal edge's `via_unit` resolves against a `work_units[].name` on the
    edge's `to` component; an external edge's `via_operation_id` resolves against
    an API operation; an external edge's `via_unit` resolves against the
    `<container>/<component>` target's work_units (sibling-container calls with
    no API between them).
14. **FR-named deliverable path coverage (#25, advisory)** — a concrete repo
    path named in a claimed FR's text that no component's `code_location`
    covers is warned about: a build-time deliverable (schema layer, `tools/`,
    `templates/`, shipped content) with no owning component can never be
    scheduled by `task`.
15. **api_consumers mirror (#26, advisory)** — an external `calls` edge with
    `via_resource_id` not mirrored in the container's `api_consumers[]` is
    warned about.

For merge logic, the recovery flow on `[FAIL]`, and the CLAUDE.md pointer
rules → see `references/merge-validate.md`.

Set `metadata.status`:

- `"complete"` — only when all required fields are filled, the validator
  passes with `[OK]`, AND every cross-check passes (coverage, edge/trace
  integrity, container/system consistency, ID-prefix formats, edge roll-up
  #24, and — in container mode — component `work_units` integrity + FR
  coverage #21/#22 + interface contracts #23).
  A container file that is on-disk `complete` but that the validator flags with
  a #21/#22/#23 error is **not** done: it is "drilled but incomplete" and
  `--next` will route back to resume its deep-dive.
- `"draft"` — on early EXIT, when any required field is null, or when
  any cross-check fails.

### Phase 7-D — Edge re-derivation (-d mode only)

This phase replaces Phases 3–6 when invocation starts with `-d`.

1. Determine scope:
   - `/sdlc:arch -d` → re-derive cross-container edges in
     `docs/ARCH.yaml`.
   - `/sdlc:arch -d <container>` → re-derive internal + external edges
     in `docs/ARCH__<container>.yaml`. `<container>` must exist in
     `ARCH.yaml.containers[].container_id`; if not, list valid
     container_ids and abort.
2. Run candidate-edge collection per `references/edge-derivation.md`:
   parse API.yaml resources, DATA store bindings, UX surface usage, and
   any free-text `overview`/`purpose` fields for canonical name matches.
   In system scope, also run roll-up rule S6: read every drilled
   container file's `external_edges` and propose missing system rows as
   ADDs. In container scope, sweep `via_unit` backfill over ALL `calls`
   edges — internal AND external-to-sibling — not just the
   intra-container ones.
3. Diff the derived edge set against the currently-stored edges in the
   affected nodes.
4. Present the diff for each node as a numbered list (add / remove /
   retype), e.g.:

   ```
   I derived these edges for `backend-api`:
     KEEP   1. calls           → identity-provider
     ADD    2. reads/writes    → primary-postgres
     RETYPE 3. depends_on → publishes  → notification-bus
     REMOVE 4. depends_on      → legacy-batch-runner
   Confirm all, or edit: "remove 2", "add: subscribes_to billing-events", ...
   ```

5. Apply confirmed changes; write only the affected file(s). Edge-only
   writes never change `metadata.status` — only edges and `last_updated`.
   If prose in the touched file (`overview`, notes, header comments)
   restates a count the edit just changed ("12 edges", "5 containers"),
   refresh or delete it in the same write — see
   `references/merge-validate.md` → "Derived-count refresh".
6. Write a derivation report to
   `.claude/skills-state/sdlc-arch.derivation-report-<ISO8601>.yaml`
   listing additions / removals / retypes per node.
7. Re-run the validator (Phase 7) to confirm edge endpoint integrity.

### Phase 8 — CLAUDE.md pointer & close

Call `set_claude_md_pointer.py` to inject or update this skill's bullet
in the shared `## SDLC Documents` section of the project-root
`CLAUDE.md`. Create the section if missing.

Bullet format (the pointer script produces this text):

```
- `docs/ARCH.yaml` (+ `docs/ARCH__<container>.yaml`): System architecture — pattern, container inventory, identity/auth, and per-container components + typed edges. Load when implementing containers, planning tests, or generating tasks. Last updated by `sdlc-arch` on <ISO-8601 timestamp>.
```

For bullet detection and append behavior, see
`references/merge-validate.md`.

**Refresh the navigation index.** If `.claude/sdlc/docs_index.py` exists (the
project ran `/sdlc:setup`), run `python .claude/sdlc/docs_index.py` after
writing `docs/ARCH.yaml` and its per-container files so `docs/INDEX.yaml`
reflects the new content right away (the setup hook also does this, but a hook
added mid-session only activates next session). Harmless no-op if not installed.

After the CLAUDE.md write succeeds: set the active session's `status:
complete` in the state file (keep the file as audit trail), tell the
user where the artifacts live, and point at what comes next:

> This container's architecture is complete. Run `/sdlc:arch --next` for
> the next undrilled container, or `/sdlc:test` once every container is
> specified (it consumes `docs/ARCH.yaml` + the per-container files).

## Session state file

Path: `.claude/skills-state/sdlc-arch.state.yaml`

Unlike single-mode skills, arch keeps **per-mode sub-sessions** in a single
file. Each invocation reads or writes one entry under `sessions:`:

```yaml
# changelog:
#   1.2 (2026-07-03): work_units cross-check #21 upgraded to BLOCKING for
#     non-trivial components (waivable via work_units_waiver); new #22 FR->work_unit
#     coverage cross-check; work_units emit block-style; "drilled" now means
#     internally complete (#21/#22), so --next resumes drilled-but-incomplete
#     containers instead of counting them as specified.
#   1.1: per-component work_units (#21), code_location (#20), upstream provenance.
session_file_version: "1"
skill_version: "1.2"
last_updated: <iso8601>

sessions:
  system:                       # /sdlc:arch
    session_id: <uuid4>
    started_at: <iso8601>
    last_updated: <iso8601>
    status: in_progress         # in_progress | complete | aborted
    mode: system
    pre_fill_confirmed: false
    last_ids: {}                # writer-managed counters for families this
                                # sub-session emits, e.g. {WRN: 2}. Increment,
                                # format as <PREFIX>-{:03d}, then persist.
                                # ARCH.yaml's arch_warnings own this WRN space.
    completed_themes: []
    skipped_themes: []
    todo_themes: []
    pending_themes: []
    current_theme: null
    current_container: null     # during the container_inventory drill-down
    defined_containers:         # list of {container_id, archetype, status: proposed|draft|confirmed|dropped, source}
      []
    drill_order: []             # resolved by `--next`: container_ids in the order
                                # to drill (dependency-first, definition-order
                                # tiebreak). Recomputed only when the container
                                # set changes. See "Invocation dispatch" → Drill order.
    dropped_container_candidates: []
    partial_answers: {}         # mirrors docs/ARCH.yaml structure

  "container|backend-api":      # /sdlc:arch backend-api
    session_id: <uuid4>
    started_at: <iso8601>
    last_updated: <iso8601>
    status: in_progress
    mode: container
    container_id: backend-api
    pre_fill_confirmed: false
    last_ids: {}                # this container file's WRN (arch_warnings) space,
                                # e.g. {WRN: 2}. work_units carry NO id family
                                # (addressed as (component, name)), so no OPN counter.
    completed_themes: []
    skipped_themes: []
    todo_themes: []
    pending_themes: []
    current_theme: null
    current_component: null     # during the component_inventory drill-down
    defined_components: []
    dropped_component_candidates: []
    partial_answers: {}         # mirrors docs/ARCH__backend-api.yaml structure
```

Rules:

- Generate `session_id` as a UUID4 on first creation of each sub-session.
- Update the top-level `last_updated` and the sub-session `last_updated`
  on every write.
- Write the file **after every confirmed batch, mini-section, and per-item
  step**, including pre-fill confirmations and Phase 3 inventory
  confirmation.
- On user `EXIT`: set the *active* sub-session's `status: aborted`, write
  `partial_answers`, confirm to user, stop. Other sub-sessions are
  untouched.
- On Phase 8 completion: set the active sub-session's `status: complete`;
  keep the file.
- **Warning IDs (`WRN-NNN`):** every `arch_warnings` entry (in `ARCH.yaml`
  and in each `ARCH__<container>.yaml`) is formatted `"WRN-NNN: <message>"`.
  The counter is writer-managed in the active sub-session's
  `last_ids.WRN`. There is no interview question for warnings — append them
  at write time (uncovered items, `todo` gates, low-confidence notes) and
  bump the counter. **Reconcile on resume:** if the on-disk file already
  contains a higher `WRN-NNN` than `last_ids.WRN`, sync the counter to
  `max(on_disk, state)` before appending the next warning, so EXIT/resume
  never produces gaps or duplicates.
- **`metadata.changelog`** is append-only, most-recent first; add one line
  per write (`"<version> (<YYYY-MM-DD>): <summary>"`). The validator only
  type-checks it.
- The validator ignores this file — it validates only `docs/ARCH.yaml`
  and the sibling per-container yamls.

**Source of truth on resume:**

- `docs/ARCH.yaml` (and any existing `docs/ARCH__<container>.yaml`) is the
  on-disk source of truth for *answers*.
- The state file is the source of truth for *interview progress*.
- On resume: load the on-disk yamls first as the baseline, then layer the
  sub-session's `partial_answers` on top.
- If they conflict on the same key, ask the user which to keep — never
  silently overwrite.

## Edges — the typed vocabulary

The edge graph is the **unique value** this skill adds over PRD/UX/DATA/API.
Edges are typed and directional. Seven types:

| Type            | Codegen implication                                            |
|-----------------|----------------------------------------------------------------|
| `depends_on`    | Hard build-time / startup dependency.                          |
| `calls`         | Synchronous request (HTTP/RPC/function).                       |
| `reads`         | Read access to a data store / cache / blob.                    |
| `writes`        | Write access to a data store / cache / blob.                   |
| `publishes`     | Emits events to a bus / queue / channel.                       |
| `subscribes_to` | Consumes events from a bus / queue / channel.                  |
| `implements`    | Realizes an abstract interface or contract.                    |

Hierarchical relationships (`contains` / `owns`) are NOT edges — they
are encoded by the document structure (`containers[].components[]`).

For verb-to-type mappings and derivation rules, see
`references/edge-derivation.md`.

## Edge cases

For unusual situations (PRD/UX/DATA/API missing or in draft, container
with no API/UX/DATA evidence, component split across containers,
container rename mid-session, edge to non-existent node, monorepo mode,
write-permission errors, very large systems) → `references/edge-cases.md`.

## Style of conversation

The architecture interview can be long. Keep it humane:

- Use the user's terminology as soon as they introduce it.
- Keep `AskUserQuestion` batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme boundary and at each container /
  component boundary ("That's `backend-api` done — 5 components, 12
  internal edges, 3 external. Next: `web-frontend`.").
- For system mode's `container_inventory` and container mode's
  `component_inventory`, explicitly call out that candidates were
  synthesized from PRD + UX + DATA + API — don't pretend they came from
  nowhere.
- Always make multiple-choice the path of least resistance. Auto-derived
  edges are confirmable in bulk; user-typed enumerations are a fallback
  for edge cases.
- After all themes are done, congratulate briefly and move to write &
  validate. Do not repeat everything back at them.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 inventory as-is. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs a `WRN-NNN` entry to `arch_warnings`. |
| `confirm all` | Accept all derived edges in an edge-confirmation diff. |

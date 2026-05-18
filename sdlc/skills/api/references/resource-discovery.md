# Resource discovery — how to enumerate, name, and deep-dive resources

Read this when entering **theme 8 (`resource_inventory`)** or **theme
10 (`per_resource_deepdive`)**. Both are `critical` per-item flows;
this file is the source of truth for how the agent drives them.

The core idea: **a resource is the smallest cohesive unit of the API
that operates on (typically) one DATA entity**. For a REST API that
usually means "all endpoints under a shared `base_path`". For GraphQL
it's the Query/Mutation root for one entity. For gRPC it's one
`service` definition.

A resource always has an `id`, a `base_path`, a `primary_entity`
(unless cross-cutting like `/search`), endpoints, and traces back to
PRD features + UX surfaces.

## Step 1 — Generate the candidate list

The candidate set is the union of three axes:

1. **DATA entities** (the primary axis). For each entity in
   `DATA-MODEL.yaml.entities`, propose one CRUD resource:
   - `User` entity → `users` resource at `/v1/users`
   - `Order` entity → `orders` resource at `/v1/orders`
2. **PRD features that don't map 1:1 to an entity**. Cross-entity
   workflows often deserve their own endpoint group:
   - PRD feature "Bulk-import tasks from CSV" →
     `imports` resource at `/v1/imports` (no single primary entity)
   - PRD feature "Search across projects + tasks" →
     `search` resource at `/v1/search` (primary_entity: null)
3. **UX surfaces with data I/O** that imply endpoints the entity list
   misses:
   - UX surface `dashboard` that displays aggregated stats →
     `dashboard` resource at `/v1/dashboard` (read-only summary)
   - UX surface `notifications` panel →
     `notifications` resource at `/v1/notifications`

Don't try to be exhaustive — the user will add, remove, or rename
resources during the per-item drill-down. Aim for a starter inventory
that:

- Covers every DATA entity with at least one resource (or has the user
  consciously opt the entity out as "internal").
- Covers every UX surface with data I/O (or is in the planned
  `non_api_surfaces` opt-out, if any).
- Covers every PRD `F-NNN` feature (or is in the planned
  `non_api_features` opt-out).

## Step 2 — Generate `resource_id`s and `base_path`s

`resource_id` is kebab-case, unique within the project, short
(≤ 32 chars). `base_path` typically starts with the version prefix
(`/v1/` if versioning is path-based) and continues with the resource
name in plural-noun form.

Rules:

- Derive `resource_id` from the dominant entity name in singular or
  plural — `users`, `orders`, `invoices`. Plural for REST conventions;
  singular when the resource fronts a single instance like
  `current-user` or `health`.
- For cross-cutting resources, use a single descriptive noun:
  `search`, `health`, `metrics`, `imports`.
- `base_path` should be lowercase and kebab-case where applicable
  (`/v1/saved-searches` not `/v1/savedSearches`).
- Renames during the interview are fine — update the
  `state.defined_resources` entry and the (unwritten) deep-dive
  partial in one move. If the resource yaml has already been written
  under the old id, ask the user before deleting it.

## Step 3 — Per-resource state machine (theme 8)

For each candidate resource, run one mini-section that confirms
identity (id, base_path, primary_entity, traces) but does NOT yet do
the endpoints/schemas deep-dive — that's theme 10.

### State machine

Each resource progresses through three states tracked in
`state.defined_resources[i].status`:

| state | meaning |
|---|---|
| `defined`   | id + base_path + primary_entity + traces known, no endpoints yet |
| `draft`     | deep-dive in progress (theme 10) |
| `confirmed` | deep-dive complete + user approved |

Theme 8 produces a list of `defined` resources. Theme 10 walks that
list and transitions each from `defined` → `draft` → `confirmed`.

### Per-item flow for theme 8

For each candidate resource from step 1:

#### a) Propose

```
header: "Resource N"
question: "Resource #N — confirm or revise?"
options:
  - { label: "⚠ <inferred id> at <base_path> (entity: <primary_entity>)", description: "⚠ <one-sentence purpose>. Traces PRD F-IDs: <ids>. Serves UX surfaces: <ids>. Confirm or correct in text field." }
  - { label: "Rename / change base_path",  description: "Type a different resource_id (kebab-case) or base_path in the text field." }
  - { label: "Change primary_entity",      description: "Type the DATA entity name this resource fronts, or 'null' for cross-cutting." }
  - { label: "Drop this candidate",        description: "Remove it from the inventory — no resource will be created." }
```

On accept → record `{ resource_id, base_path, primary_entity,
status: defined, file_path: docs/API__<resource_id>.yaml,
traces_prd_features: [<F-IDs>], traces_ux_surfaces: [<surface_ids>] }`
in `state.defined_resources`, persist state.

On rename / base_path change → re-run step a with the new values.

On drop → record the dropped candidate in
`state.dropped_resource_candidates` (so the agent knows not to
re-propose on resume). Don't write the file.

#### b) Confirm traces

If the proposed traces miss a PRD feature you'd expect, or if the user
is likely to add resources beyond what the agent inferred, ask one or
two targeted clarifying `AskUserQuestion` calls — one for features,
one for surfaces (both `multiSelect: true`):

```
header: "Features?"
question: "Which PRD F-NNN features does '<resource_id>' implement?"
options:
  - { label: "<F-001: description>",          description: "<verbatim PRD must_have_features entry>" }
  - { label: "<F-003: description>",          description: "<verbatim PRD must_have_features entry>" }
  - { label: "Other (type)",                  description: "Type the F-NNN id(s) verbatim from PRD.functional_requirements.must_have_features." }
  - { label: "None — internal-only resource", description: "This resource doesn't implement any PRD F-NNN. (Will be flagged in api_warnings unless an explicit reason is captured.)" }
multiSelect: true
```

```
header: "Surfaces?"
question: "Which UX surfaces does '<resource_id>' serve?"
options:
  - { label: "<surface-id-1>",                description: "<surface_type>; <one-line description>" }
  - { label: "<surface-id-2>",                description: "<surface_type>; <one-line description>" }
  - { label: "Other (type)",                  description: "Type a UX surface_id verbatim." }
  - { label: "None — internal-only resource", description: "Surface coverage will not credit this resource for any UX surface." }
multiSelect: true
```

#### c) Next or end

When the candidate list is exhausted, ask:

```
header: "More?"
question: "Add another resource, or wrap up the inventory?"
options:
  - { label: "Add another (I'll suggest)",   description: "I'll propose a candidate from any uncovered DATA entity / PRD feature / UX surface." }
  - { label: "Add my own",                   description: "Type a resource_id + base_path + primary_entity in the text field." }
  - { label: "Done — wrap up inventory",     description: "Move on to per-resource deep-dive." }
```

**Caps**: soft 15 resources, hard 25. Above the hard cap, refuse
politely and suggest splitting the product into multiple products
(monorepo mode) or pushing some resources to a later phase.

### Coverage hint at end of theme 8

Before finishing theme 8, run the three coverage checks softly (no
validator yet, just heuristics):

- For each PRD `F-NNN` in `must_have_features`: is it traced?
- For each data-bearing UX surface (see
  `references/merge-validate.md` for the type list): is it traced?
- For each DATA entity: is it the `primary_entity` of some resource?

If any are missing, tell the user which ones and ask:

```
header: "Coverage?"
question: "These items aren't covered by any resource yet:\n - F-IDs: <ids>\n - UX surfaces: <ids>\n - DATA entities: <names>\nAdd resources for them now?"
options:
  - { label: "Add resource(s) now",          description: "I'll propose one per uncovered item." }
  - { label: "Mark uncovered F-IDs as non_api_features", description: "They become UI-only / batch / internal — recorded in API.yaml.non_api_features." }
  - { label: "Leave gap — record in api_warnings", description: "The items will be listed in api_warnings and API.yaml will save as draft." }
  - { label: "Edit existing traces",         description: "Re-open an existing resource to add the missing trace(s)." }
```

This is the soft coverage check. The hard checks happen in
`validate_schema.py` (Phase 7).

## Step 4 — Per-resource deep-dive (theme 10)

For each resource in `state.defined_resources` (in order they were
defined), run the deep-dive. The deep-dive is the `critical` per-item
flow that writes the per-resource yaml.

### State transition

When the deep-dive starts for a resource, set its status to `draft`
and seed `state.partial_resources[<resource_id>]` with the known
identity (`resource_id`, `base_path`, `primary_entity`,
`traces_prd_features`, `traces_ux_surfaces`) plus empty values for the
rest.

When the deep-dive completes (after step e final approval), flip
status to `confirmed`, write the resource yaml to disk
(`docs/API__<resource_id>.yaml`), and move the contents from
`state.partial_resources` into a permanent slot.

### Per-resource mini-interview (5 steps)

For each resource:

#### a) Announce + identity recap

Print to the chat:

> "Now: `<resource_id>` at `<base_path>` (primary entity:
> `<primary_entity>`). Traces F-IDs `<F-IDs>` and UX surfaces
> `<ids>`. 4 questions to fill in endpoints, DTO schemas, and confirm
> traces."

(No `AskUserQuestion` here — it's a banner.)

#### b) Endpoints

Propose the canonical CRUD set adapted to the resource's verbs:

- `list-<resource>` — `GET <base_path>` — returns paginated list
- `get-<resource>` — `GET <base_path>/{id}` — returns one
- `create-<resource>` — `POST <base_path>` — creates one
- `update-<resource>` — `PUT <base_path>/{id}` or `PATCH` — updates
- `delete-<resource>` — `DELETE <base_path>/{id}` — removes

Add custom actions for any PRD feature the canonical CRUD doesn't
cover (e.g. `POST /users/{id}/reset-password` for a "reset password"
feature). The agent proposes them per-feature.

Walk endpoints per-item (high tier), confirming method/path/summary/
request DTO ref / response DTO ref / status codes / auth. Each endpoint
becomes one entry in the resource yaml's `endpoints[]`. See
`references/openapi-embedding.md` for the OpenAPI 3.1 subset
supported and how to write request/response schemas.

#### c) DTO schemas

Propose schemas based on the primary DATA entity:

- `<Entity>` — full read DTO (omit persistence-only fields)
- `<Entity>Create` — POST payload (omit server-set fields like `id`,
  `created_at`, `updated_at`)
- `<Entity>Update` — PUT/PATCH payload (all fields optional for PATCH;
  required as in Create for PUT)
- `<Entity>List` — paginated list wrapper (only when pagination is
  envelope-style rather than raw array)

Each schema includes `projects_from: <EntityName>` so downstream
agents know which DATA entity it derives from. See
`references/openapi-embedding.md` for the DTO-vs-entity discipline.

#### d) Re-confirm traces

Re-show the `traces_prd_features` and `traces_ux_surfaces` lists from
theme 8 and ask one quick `AskUserQuestion` to adjust:

```
header: "Traces ok?"
question: "These traces are recorded for `<resource_id>`. Adjust before saving?"
options:
  - { label: "Looks good",            description: "Keep traces as recorded." }
  - { label: "Add an F-ID",           description: "Type the F-NNN to add." }
  - { label: "Add a UX surface",      description: "Type the surface_id to add." }
  - { label: "Remove a trace",        description: "Type the F-NNN or surface_id to remove." }
```

#### e) Final approval

Print the drafted per-resource yaml (or a compact summary if it's
long) and ask:

```
header: "Approve?"
question: "Approve `<resource_id>` as drafted?"
options:
  - { label: "Approve — write to disk",       description: "Save docs/API__<resource_id>.yaml and continue." }
  - { label: "Iterate — type changes",        description: "Use the text field to describe what to change. The agent will re-draft." }
  - { label: "Skip for now — keep as draft",  description: "Move on to the next resource; this one stays status: draft and the file is NOT written." }
```

On approve: write the resource yaml, flip status to `confirmed`,
persist state.

On iterate: re-enter step b/c/d with the user's revision context.
After 3 iterations on a single resource, write the current draft and
add an `api_warnings` entry naming the resource.

On skip: leave status `draft`, do NOT write the file (the validator
won't see it, but the entry remains in `state.defined_resources` and
`state.partial_resources` so the user can resume later).

### State-write timing

Persist state after each per-resource step (b/c/d/e), not just at the
end. This keeps EXIT cheap mid-deep-dive — the partial resource stays
in `state.partial_resources` and resumes cleanly.

## When the user EXITs mid-flow

- Mid-theme 8: write all confirmed inventory entries to
  `state.defined_resources`, drop the current candidate (it wasn't
  approved). Set `status: aborted`.
- Mid-theme 10 deep-dive on resource N: write the partial yaml
  content to `state.partial_resources[<resource_id>]`. Do NOT write
  the resource file to disk (it's incomplete). Set `status: aborted`.
  The `state.defined_resources[N].status` stays `draft`.

On resume, the agent picks up at the partial resource — it explicitly
asks the user *"Resume mid-deep-dive of `<resource_id>`?"* before
re-entering theme 10.

## Naming and renaming resources mid-flow

If the user renames a resource during theme 10:

1. If no file has been written yet → just update the id everywhere
   (`state.defined_resources`, `state.partial_resources`,
   `state.current_resource`).
2. If the file already exists → ask the user:
   *"Rename `docs/API__<old>.yaml` → `docs/API__<new>.yaml`? This will
   delete the old file."* Wait for explicit confirmation before
   deleting.

Resource ids are immutable post-completion only by convention — the
user can always rename via an update interview, but each rename
forces a file move and a coverage-check re-validation.

## Soft-deletion of dropped candidates

When the user drops a candidate in theme 8 step a:

- Record `{ resource_id, reason: "dropped by user", at: <timestamp> }`
  in `state.dropped_resource_candidates`.
- Don't propose the same id again on resume.
- The dropped resource is NOT written to
  `API.yaml.resource_inventory`.

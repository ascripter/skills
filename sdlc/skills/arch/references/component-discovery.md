# Component discovery — container mode Phase 3

This file describes how to seed the **component inventory** for one
`docs/ARCH__<container>.yaml` from the upstream artifacts plus the
container's archetype (read from the parent `ARCH.yaml`). Read this on
entering Phase 3 of container mode.

## Source priority

### Pass 1 — Archetype-driven scaffold

Load the container's `archetype` from
`ARCH.yaml.containers[id].archetype`, then look up the archetype's
`suggested_components` in `container-taxonomy.yaml`. These are the
"plumbing" components most containers of this archetype have.

For example, `backend-api` typically gets:

- `routing` (`controller` archetype)
- `auth-middleware` (`middleware`)
- `repository-layer` (`repository`)
- `use-cases` (`service`)
- `validators` (`validator`)
- `serializers` (`serializer`)

These are `⚠ inferred` and need user confirmation in Phase 3.

### Pass 2 — One component per API resource

For each `resource_id` in `ARCH.yaml.containers[id].owns_api_resources`,
propose **one or two** components:

- **Default (single)**: `<resource_id>` component — `service` archetype.
  The component traces back to `API__<resource_id>.yaml`.
- **Split (controller + service + repository)**: three components per
  resource, named `<resource>-controller`, `<resource>-service`,
  `<resource>-repository`. Use this split only when the user explicitly
  prefers a layered style (Phase 3 prompt asks).

Each component's `traces_api_resources` is set to the resource_id.

### Pass 3 — One component per UX surface (frontend only)

For each `surface_id` in `ARCH.yaml.containers[id].owns_ux_surfaces`,
propose one component named `<surface_id>-view` with archetype `view`.
Trace back to `UX__<surface_id>.yaml` via `traces_ux_surfaces`.

For multi-surface flows (`UX.navigation_model.top_level_nodes` groups
surfaces under a parent), propose an additional `<top-level>-router`
component with archetype `controller`.

### Pass 4 — Persistence bindings → client components

For each store_id in `ARCH.yaml.containers[id].persistence`, propose
a client component:

| Store kind                | Component name           | Archetype     |
|---------------------------|--------------------------|---------------|
| primary database          | `<store>-client`         | `repository`  |
| cache / redis             | `<store>-client`         | `cache_client`|
| blob store / S3           | `<store>-client`         | `blob_client` |
| search index              | `<store>-client`         | `repository`  |
| message bus (publisher)   | `<bus>-publisher`        | `service`     |
| message bus (subscriber)  | `<event-id>-handler`     | `event_handler`|

The publish vs subscribe split comes from the system-level
`cross_container_edges`: if the container has a `publishes` edge to
the bus, add a publisher; if it has a `subscribes_to` edge, add a
handler per event channel.

### Pass 5 — Cross-cutting components

Always-on candidates regardless of archetype:

- `config-loader` (`service`) — every non-trivial container needs config
  parsing. Propose, but allow user to skip if config is trivial.
- `observability-bootstrap` (`service`) — OTel / metrics / logging init.
  Only propose if `observability.metrics` or `traces` is non-null in the
  Phase 6 deployment theme.
- `error-handler` (`middleware`) — for backend / web-frontend archetypes.

These are `⚠ inferred` — user confirms.

## Inferred vs found

- `✓ found` — direct evidence (API resource, UX surface, persistence
  binding).
- `⚠ inferred` — derived from archetype's `suggested_components` (Pass 1)
  or cross-cutting heuristics (Pass 5).

The hallucination guard applies: each `⚠ inferred` component is
confirmed individually.

## Presentation

```
Drafted from upstream + archetype (backend-api):

  ✓ users-controller      (controller)  traces: users
  ✓ users-service         (service)     traces: users
  ✓ users-repository      (repository)  traces: users, primary-postgres
  ✓ projects-controller   (controller)  traces: projects
  ✓ projects-service      (service)     traces: projects
  ✓ projects-repository   (repository)  traces: projects, primary-postgres
  ⚠ auth-middleware       (middleware)  — from backend-api archetype
  ⚠ error-handler         (middleware)  — from backend-api archetype
  ⚠ config-loader         (service)     — cross-cutting
  ⚠ notification-publisher (service)    — from publishes edge in ARCH.yaml

Add, rename, drop, or collapse anything? (e.g. "collapse users-controller +
users-service + users-repository into one `users` component")
```

The user controls layering depth (controller-service-repository vs flat).
Default to the upstream-suggested style, but always offer a one-line
"collapse" shortcut.

## Persisting

Persist the confirmed list to
`state.sessions[container|<id>].defined_components`:

```yaml
- component_id: <kebab>
  archetype: <enum>
  status: proposed | draft | confirmed | dropped
  source: api-resource | ux-surface | archetype-scaffold | persistence-binding | cross-cutting | user-added
  traces_api_resources: [...]
  traces_ux_surfaces: [...]
  traces_data_entities: [...]
```

After Phase 3 confirmation, Phase 6's `component_inventory` and
`per_component_deepdive` themes walk the confirmed list per-item
(critical state machines). During `per_component_deepdive`, set each
component's `implements_requirements` to the FR-NNN it realizes — this
MUST be a subset of the parent container's `implements_requirements`
(the validator enforces containment), so draw only from the features the
container itself claims.

## Deriving code_location

`code_location` is the **component → code-module seam**: the repo-relative
directory(ies) (and optionally an illustrative file) where this component's
source lives. It is filled during `per_component_deepdive` (an `importance:
high` mini-section — the agent drafts, the user approves). It is the single
highest-leverage field for autonomous downstream work: the `task` skill grounds
every task's `target_files` in the owning component's `code_location`, so if it's
vague or absent the codegen agent has to *invent* each file's placement — the
most common way a generated repo drifts from its architecture.

**Draft it from archetype + the container's source layout.** The container's
`tech_stack` (language + framework) and its conventional import layering tell you
where each archetype's code belongs. Map the component's archetype to a directory
in that layout:

| Archetype (component)                | Typical home (layered backend)     | Notes |
|--------------------------------------|------------------------------------|-------|
| `controller`                         | `src/<area>/` or `controllers/`    | one per API resource the controller owns |
| `service` / `use_case`               | `services/` / `core/`              | the bulk of behaviour |
| `repository`                         | `repositories/` / `data/`          | one per entity/store |
| `middleware` / `error_handler`       | `middleware/`                      | |
| `view`                               | `src/views/` / `app/<route>/`      | frontend; map to the surface's route |
| `api_client`                         | `clients/` / `api/`                | the SDK for a called container |
| `event_handler` / `background_worker`| `workers/` / `handlers/`           | |
| `cache_client` / `blob_client`       | `clients/`                         | |
| `config_loader` / `serializer`       | `config/` / `serialization/`       | plumbing — code_location optional |

These are *heuristics keyed to the conventional layout for the chosen stack* —
not a fixed list. Read the project's own layering signal first (a `README`, an
`architecture.*` doc, an existing `src/` tree, or a `CLAUDE.md` layering rule the
project ships) and prefer it over the table. Honour the **directory-firm,
file-illustrative** rule: a directory entry is a contract the executor must
respect; a file path is a hint it may rename.

**A component may span layers** — e.g. a runtime component that owns both its
node module and the schema it emits lists both dirs. List each directory rather
than picking one. **Reconcile with edges:** a component's `code_location` plus
the internal-edge graph is what makes every edge mechanically checkable against
the project's import layering — see `references/edge-derivation.md` → "Edges vs
imports".

When you persist a drafted component's placement to state, carry it on the
`defined_components` entry (`code_location: [...]`) so resume doesn't re-draft it.

## Deriving work_units

`work_units` is the **component → code seam**: the named method/function-level
**callables** the component exposes (C4 interface level). It is filled during
`per_component_deepdive` (an `importance: high` mini-section — the agent drafts the
full list, the user approves or edits). It is the single field that makes
**atomic, method-level task breakdown** possible downstream: the `task` skill
slices **exactly one implementation task per work_unit** (its `target_symbol` =
the work_unit `name`), so a component that declares no work_units yields no atomic
implementation task. The arch validator emits a non-blocking WARNING for a
non-trivial component with traces but no work_units (cross-check #21).

**Enumerate the contract surface, not every private helper.** A work_unit is a
PUBLIC / contract-bearing callable — one that realizes a traced contract (an API
operation, an entity's persistence, a surface's render) or sits on an
internal/external edge (something another component calls). A private helper that
no contract or edge names is an implementation detail *of* some work_unit, not a
work_unit of its own. This keeps the list at the right altitude: one codegen task
per callable another part of the system depends on.

**Never ask cold — draft from the component's archetype + its traces, then let
the user trim:**

| Component archetype | Draft one work_unit per … | Pre-fill |
|---|---|---|
| `controller` / `bff` | owned API operation | `traces_api_operation` = the `operation_id`; `implements_requirements` from the endpoint's feature; `name` = the handler (e.g. `createTask`) |
| `repository` / `cache_client` / `blob_client` | CRUD verb × traced entity (create/get/list/update/delete) | `touches_entities` = the entity |
| `service` / `use_case` / `background_worker` | behaviour implied by a responsibility, an `acceptance_criterion`, or an FR it implements | `implements_requirements` ⊆ the component's; `satisfies_acceptance` = the criterion |
| `view` | user interaction / render path | — |
| `api_client` | called remote operation | `traces_api_operation` |
| `validator` / `serializer` | the one transform it performs (often a single unit, or skip) | — |
| `middleware` / `scheduler` / `event_handler` | the wrap / tick / handle entry point | — |
| `config_loader` / `observability_bootstrap` / `error_handler` | usually **none** (plumbing) | — |

Each work_unit carries:

- `name` — the callable (method / function / `Class.method`), **unique within its
  owning component**. work_units are addressed as `(component, name)` — there is
  no id family. This name is the stable handle `task` references as a
  `target_symbol`; it IS the callable, so renaming the callable renames it.
- `summary` (one line) — required.
- Optional traces: `traces_api_operation` (⊆ API operation_ids),
  `implements_requirements` (FR/NFR ⊆ the owning component's),
  `touches_entities` (⊆ the component's `traces_data_entities`),
  `satisfies_acceptance` (the component criterion it fulfils).
- The **interface contract**, DEFER-OR-DECLARE (`inputs`, `output`, `raises`, and
  an optional concrete `signature`): a work_unit that realizes a schema-bearing
  traced contract (e.g. an API operation whose request/response schema lives in
  `API__*.yaml`) may leave these **empty and defer** to that contract; a domain
  callable with no schema-bearing upstream contract (a `service`/`use_case`
  method) **declares** them, so the independently-generated atomic tasks compose
  against a frozen interface instead of each re-guessing the signature. Fill
  `signature` only when the signature itself is the contract (a public library
  API); otherwise codegen renders it from `inputs`/`output` + the tech stack.

**Work_unit-completeness check (before closing the component).** Reflect on the
drafted units against the component's own signals: does every owned API
`operation_id` map to a work_unit? every `acceptance_criterion`? every entity the
component reads/writes (a CRUD unit)? Add the missing ones. Honour the
anti-padding rule — a `validator` with one transform has one work_unit, not five,
and a private helper is not a work_unit.

Persist the confirmed units to the `defined_components` entry
(`work_units: [...]`) so resume doesn't re-draft them. (No id counter — work_units
are name-addressed.)

## Scope-completeness sweep (synthesis theme)

`component_inventory` is a `critical synthesis: true` theme. After the
per-item loop closes, run a dynamic scope-completeness sweep (canonical
spec: `sdlc/skills/prd/references/importance-flows.md`). Reflect on:

1. **The draft component list** — are layers missing (controller without
   a service, repository without a client)? Is one component doing two
   jobs?
2. **Every upstream signal the container owns**:
   - **owned API resources / operations** — does every owned
     `resource_id` (and key `operation_id`) have a component that
     implements it?
   - **owned UX surfaces** — does every owned `surface_id` have a view
     component?
   - **persistence bindings** — does every store the container binds to
     have a client/repository component?
   - **the container's `implements_requirements` (FR-NNN)** — is every
     feature the container claims realized by at least one component?
     An FR with no component is a missing component.
   - **the container's `subscribes_to` / `publishes` edges** (from
     `ARCH.yaml`) — each needs an event-handler / publisher component.
3. **Archetype heuristics** — cross-cutting plumbing (config-loader,
   error-handler, observability-bootstrap) that's easy to forget.

Surface concrete missed **candidate components** via **one multi-select
`AskUserQuestion`**. Caps: at most **2 sweep passes**; defer leftovers
to a `WRN-NNN` `arch_warnings` entry; honour the **anti-padding rule**.

## Edge cases

- **External containers** (`external: true` in ARCH.yaml) — these never
  enter container mode. If invoked on an external container, abort with
  a message: "External container `<id>`. We model the API surface in
  ARCH.yaml but don't author internal components for external services."
- **Data-store containers** (e.g. `primary-postgres`) — these are also
  external in practice. Same abort message.
- **No upstream evidence** — if `owns_api_resources`, `owns_ux_surfaces`,
  and `persistence` are all empty for this container, fall back to the
  archetype scaffold only. Warn the user that the container is
  under-specified.

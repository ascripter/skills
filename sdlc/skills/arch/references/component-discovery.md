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
(critical state machines).

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

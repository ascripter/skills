# Edge derivation — how API + DATA + UX seed the typed edge graph

The typed edge graph is the unique value `sdlc-arch` adds over the
upstream skills. Edges are **derived from upstream artifacts**, not
enumerated by the user. The user confirms or edits a derived list.

This file is read at three points:

1. Phase 6 of system mode, theme `cross_container_edges`.
2. Phase 6 of container mode, theme `internal_and_external_edges`.
3. Every `-d` / `--dependencies` invocation (Phase 7-D).

## The seven edge types

| Type            | When to emit it                                                                              |
|-----------------|----------------------------------------------------------------------------------------------|
| `depends_on`    | Hard start-up / build-time dependency (e.g. service needs config from another at boot).      |
| `calls`         | Synchronous request (HTTP / RPC / function). The default for API-resource consumption.       |
| `reads`         | Read access to a data store / cache / blob / index.                                          |
| `writes`        | Write access to a data store / cache / blob / index.                                         |
| `publishes`     | Emits events to a bus / queue / channel.                                                     |
| `subscribes_to` | Consumes events from a bus / queue / channel.                                                |
| `implements`    | Realizes an abstract contract / interface defined elsewhere (rare — used for plugin archs).  |

`reads` and `writes` may both apply — emit two edges in that case
(don't invent a `read_write` type).

Hierarchical relationships (`contains`, `owns`) are NOT edges — they
live in the document structure (`containers[].components[]`).

## System-level derivation rules

Scope: edges between containers in `docs/ARCH.yaml`.

### Rule S1 — API consumption (`calls`)

For every resource `R` in `API.yaml.resource_inventory[]`:

- Find the producer container `P` such that `R.resource_id ∈ P.owns_api_resources`.
- For every consumer container `C` such that `C != P` AND
  any of `C`'s `owns_ux_surfaces` calls `R` (per `UX__<surface>.yaml.interactions`
  with `effect: call_api` pointing at `R`):
  emit `{ from: C, to: P, type: calls, note: "consumes <R>" }`.
- If `UX` doesn't disambiguate which surface calls which resource (the
  default), fall back to: every frontend container `calls` every backend
  container whose resources its surfaces *could* be calling. Surface this
  as a single edge per (frontend, backend) pair — the agent confirms
  during the synthesis review.

### Rule S2 — Persistence (`reads` / `writes`)

For every container `C` and every store_id `S` in `C.persistence`:

- Find the store container `T` such that `T.container_id == S` OR
  `T.archetype ∈ {primary-database, secondary-database, cache, blob-store, search-index}`
  AND `T.container_id == S`.
- Inspect `C`'s expected access pattern:
  - Backend container with API resources → `reads` + `writes` (both edges).
  - Worker / scheduler / batch container → `writes` (and `reads` if the
    feature description implies it).
  - Cache client → `reads` + `writes`.
  - Read-only replica binding → `reads` only.
- Emit one edge per access mode, both `from: C` `to: T`.

### Rule S3 — Identity (`calls`)

For every backend container `C` with `auth.schemes` mentioning JWT /
OIDC / SAML AND the system has an `identity-provider` container `IDP`:

- Emit `{ from: C, to: IDP, type: calls, note: "validates tokens" }`.

If the IDP is external (e.g. Auth0, Cognito), use
`type: calls` with `note: "external"` and ensure `IDP.external: true`.

### Rule S4 — Eventing (`publishes` / `subscribes_to`)

For every channel `CH` in `API.yaml.events.channels`:

- Find the bus container `BUS` whose archetype is `message-bus`.
- If `CH.direction == out` (server publishes): for every container `P`
  with `CH.payload_schema_ref` mentioned in its `purpose` /
  feature-coverage: emit `{ from: P, to: BUS, type: publishes }`.
- If `CH.direction == in` (server subscribes): for every container `S`
  whose archetype is `worker` / `stream-processor` AND whose features
  imply consuming `CH`: emit `{ from: S, to: BUS, type: subscribes_to }`.

When `CH` has no payload_schema_ref, infer the producer/consumer from
the channel name (e.g. `users.created` → producer is the users-owning
backend; consumer is anyone with a `worker` archetype mentioning
"notifications" or "user lifecycle").

### Rule S5 — Pattern-driven scaffolding

- `architecture_pattern.pattern == event_driven` → every backend
  container has at least one `publishes` edge to the bus (else surface
  a warning).
- `architecture_pattern.pattern == microservices` AND no gateway →
  every consumer→producer edge is `calls`. Add no implicit gateway
  unless the user confirmed one in container_inventory.

## Container-level derivation rules

Scope: `internal_edges` (component ↔ component inside one container)
and `external_edges` (component → container or component → component
in another container) in `docs/ARCH__<container>.yaml`.

### Rule C1 — Controller → service (`calls`)

For every `controller` component `K` with `traces_api_resources: [R]`:
emit `{ from: K, to: <R>-service, type: calls }` if a service
component for `R` exists.

### Rule C2 — Service → repository (`calls`)

For every `service` component `S` with `traces_data_entities: [E]`:
emit `{ from: S, to: <E>-repository, type: calls }` if a repository
component exists.

### Rule C3 — Service → cache / blob clients (`reads` / `writes`)

If a `service` component traces an entity AND the container binds a
cache / blob store: emit edges from the service to the appropriate
`*-client` component for the access mode.

### Rule C4 — Service → publisher (`calls` internally, `publishes` externally)

If the service implements an API resource that has a corresponding
event channel (per Rule S4), emit:

- internal: `{ from: <r>-service, to: notification-publisher, type: calls }`.
- external: `{ from: notification-publisher, to: <bus-container>, type: publishes }`.

### Rule C5 — Subscriber components

For every `event_handler` component:

- internal: emit `{ from: <handler>, to: <service-it-delegates-to>, type: calls }`
  if such a service exists.
- external: emit `{ from: <handler>, to: <bus-container>, type: subscribes_to }`.

### Rule C6 — Middleware → next handler (`depends_on`)

`middleware` components in backend / web-frontend archetypes
typically form a chain (logger → auth → rate-limiter → router). Emit
`{ from: <upstream>, to: <downstream>, type: depends_on }` for each
adjacent pair. Confirm chain order with the user.

### Rule C7 — Frontend view → api_client (`calls`)

For every `view` component with `traces_ux_surfaces: [SF]` AND `SF`'s
surface has `interactions[].effect: call_api`:

- internal: `{ from: <surface>-view, to: api-client, type: calls }`.
- external: `{ from: api-client, to: <backend-container>/<resource>-controller, type: calls }`
  (or just `<backend-container>` if no controller component is defined).

## Endpoint resolution

Every derived edge must resolve to an **existing graph node**:

- System-level edges' endpoints are `container_id`s.
- Container-level internal_edges' endpoints are `component_id`s
  within this container.
- Container-level external_edges' `to` is `<container_id>` or
  `<container_id>/<component_id>`. The latter is preferred whenever
  the target container has been drilled-down via container mode.

If a derivation rule would produce an edge to a non-existent node, do
**one** of three things, in priority:

1. If the target node clearly *should* exist (e.g. you've inferred
   `users-service` but the user collapsed to flat components), retarget
   to the closest existing node (`users`).
2. If the target node is missing but its container is known, target
   the container (`<container_id>` with no slash).
3. Otherwise, **drop the edge** and add a warning to `arch_warnings`.

Never invent a node to support an edge.

## Presentation as a diff

The user sees the derived edges as a numbered diff (see
`interview-mechanics.md` — Synthesis themes). They can:

- `confirm all` — accept the whole derivation.
- `remove N` — drop a specific row.
- `retype N as <type>` — change the type.
- `add: <type> <to>` — add a row not derived.
- `EXIT` — save state and stop.

## `-d` (re-derivation) mode

In `-d` mode the agent **skips the interview entirely** and runs only
edge derivation. The diff is built against the *currently stored*
edges in the target file.

Three differences vs. interview-mode derivation:

1. No `KEEP` rows that haven't changed — show only ADD / REMOVE / RETYPE.
2. After the user's confirm, write a derivation report at
   `.claude/skills-state/sdlc-arch.derivation-report-<ISO8601>.yaml`:

   ```yaml
   generated_at: <iso>
   scope: system | container/<id>
   added:
     - { from: ..., to: ..., type: ..., evidence: "..." }
   removed:
     - { from: ..., to: ..., type: ... }
   retyped:
     - { from: ..., to: ..., old_type: ..., new_type: ..., evidence: "..." }
   skipped_no_evidence:
     - { from: ..., to: ..., type: ..., reason: "no upstream signal" }
   ```

3. Edge-only writes never change `metadata.status` — they only update
   `edges`/`internal_edges`/`external_edges` and `last_updated`.

## Common pitfalls

- **Over-eager `depends_on`** — most agents reach for `depends_on` when
  unsure. Prefer the more specific verb. Only emit `depends_on` for
  hard boot-time dependencies (config service, secrets manager, IDP
  before serving traffic).
- **Symmetric `reads` + `writes`** — emit two edges, not a fictitious
  `accesses` type.
- **Edges to/from external containers** — fine. External containers
  participate in the graph but lack `ARCH__<id>.yaml` files.
- **Cycles** — allowed. Cyclic dependencies are common (services that
  call each other for cross-cutting concerns). The validator does not
  reject cycles; only surfacing them in `arch_warnings` is appropriate
  when they look unintentional.

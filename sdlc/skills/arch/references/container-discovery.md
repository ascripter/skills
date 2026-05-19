# Container discovery — system mode Phase 3

This file describes how to seed the **container inventory** for
`docs/ARCH.yaml` from the upstream artifacts (`PRD.yaml`,
`UX.yaml` + `UX__*.yaml`, `DATA-MODEL.yaml`, `API.yaml` +
`API__*.yaml`). Read this on entering Phase 3 of system mode.

The goal: present a draft container list **before** any per-container
drill-down begins, so the user can correct course early. Hallucinated
containers are the most expensive error this skill can make — every
downstream skill (test, task, deploy) propagates them.

## Source priority

Run the following passes in order. Each pass adds candidates; later
passes can refine but never silently drop earlier candidates.

### Pass 1 — Frontend containers (from `UX.yaml`)

`UX.yaml.surface_family` decides the frontend shape:

| surface_family    | Default container(s)                          |
|-------------------|-----------------------------------------------|
| `web`             | `web-frontend`                                |
| `mobile`          | `mobile-frontend`                             |
| `desktop`         | `desktop-frontend`                            |
| `cli`             | `cli`                                         |
| `browser_extension` | `browser-extension`                         |
| `mixed`           | one container per actual surface_type cluster |
| `none`            | no frontend container                         |

All surfaces from `UX__*.yaml` go into one frontend container *by default*.
Split into multiple frontend containers only when:

- Different surfaces target different platforms (e.g. web + mobile).
- A surface explicitly belongs to a different audience (admin panel vs.
  end-user app) AND the PRD has separate personas.
- The user opts to split (Phase 3 confirmation).

Tag all surfaces from a frontend container's `owns_ux_surfaces`.

### Pass 2 — Backend containers (from `API.yaml`)

If `API.yaml.api_kind != none`, propose at least one backend container.

Splitting rules:

- If `API.yaml` defines `tags` or `bounded_context` on resources, group
  resources by tag/context — each group → one backend container.
- If the architecture pattern (Phase 4 question) is `microservices` or
  `event_driven`, propose one backend container per resource group at
  the bounded-context level.
- Otherwise default to one backend container holding *all* API resources.
  Confirm with the user.

Backend containers' `owns_api_resources` are the resources from their group.

### Pass 3 — Data stores (from `DATA-MODEL.yaml`)

Every entry in `DATA-MODEL.persistence.*` becomes a container with
`external: true` unless explicitly self-hosted:

- `primary_store`: `postgres` / `mysql` / `sqlite` / `mongodb` / ... →
  one `primary-database` container.
- `secondary_stores[].kind ∈ {cache, redis, memcached}` → `cache` container.
- `secondary_stores[].kind ∈ {blob, s3, gcs}` → `blob-store` container.
- `secondary_stores[].kind ∈ {search, elastic, opensearch}` →
  `search-index` container.
- `secondary_stores[].kind ∈ {queue, kafka, sqs, pubsub}` → `message-bus`
  container.

Each data-store container has empty `owns_api_resources` and
`owns_ux_surfaces`; its `persistence` list contains *itself* (the
store_id).

### Pass 4 — Operational containers (from PRD)

Walk `PRD.functional_requirements.must_have_features` and look for
keywords that imply non-API operational work:

| Keyword cluster                          | Candidate container         |
|------------------------------------------|------------------------------|
| "scheduled", "nightly", "weekly", "cron" | `scheduler`                  |
| "batch", "import", "ETL", "ingestion"    | `worker` (batch_job)         |
| "real-time", "stream", "event"           | `stream-processor`           |
| "notification", "email", "SMS"           | `worker` (notifications) OR external |
| "AI agent", "LLM", "inference"           | `ml-inference`               |
| "webhook receiver"                       | `gateway` or merge into backend |
| "static landing page"                    | `static-site`                |

These are `⚠ inferred` candidates — surface them with the F-NNN
evidence inline ("F-014 mentions 'nightly cleanup' → `scheduler`
container?").

### Pass 5 — Identity provider (from PRD + API)

- If `PRD.security_compliance.auth_model ∈ {oauth2, sso, openid_connect}`
  AND `API.auth.schemes` contains `oauth2` or `bearer_jwt`:
  propose `identity-provider` as an *external* container by default.
  Make it internal only if the user has explicitly stated they're
  building their own.
- If `auth_model == none`: no identity container.

### Pass 6 — Gateway / BFF (from pattern + container count)

- If `architecture_pattern.pattern == microservices` AND more than 2
  backend containers exist: propose `gateway` (`api-gateway` /
  reverse proxy / ingress).
- If frontend ≥ 1 AND backend containers ≥ 2 AND the pattern hint
  suggests per-client APIs: propose `bff` (one per frontend).

These are `⚠ inferred` — never auto-add.

## Inferred vs found

Each candidate is tagged for the user:

- `✓ found` — direct evidence (UX surface, API resource, DATA store).
- `⚠ inferred` — derived from keywords/heuristics (Pass 4, 5, 6).

`⚠ inferred` candidates **must** be confirmed individually (the
hallucination guard from `interview-mechanics.md`). Bulk acceptance is
allowed only for `✓ found` items, with a per-item escape hatch.

## Presentation

The Phase 3 presentation is a numbered list plus an "Add, remove, or
rename anything?" prompt:

```
Drafted from upstream artifacts:

  ✓ web-frontend     (web-frontend)    owns: dashboard, login, settings
  ✓ backend-api      (backend-api)     owns: users, projects, files
  ✓ primary-postgres (primary-database) — DATA primary_store
  ✓ redis-cache      (cache)           — DATA secondary_store
  ⚠ scheduler        (scheduler)       — inferred from F-014 "nightly cleanup"
  ⚠ identity-provider (external)       — inferred from PRD oauth2

Add, remove, or rename anything before we go deep on each one?
```

The user can:

- `ok` → accept all `✓ found` items, then walk through `⚠ inferred`
  one-by-one.
- `drop scheduler` / `rename web-frontend to admin-ui` / `add: cdn`.
- `EXIT` → save state and stop.

Persist the confirmed list to
`state.sessions[system].defined_containers`. Each entry:

```yaml
- container_id: <kebab>
  archetype: <enum>
  status: proposed | draft | confirmed | dropped
  source: ux | api | data | prd-feature | prd-auth | pattern | user-added
```

After Phase 3 confirmation, Phase 6's `container_inventory` theme walks
the *confirmed* list per-item (critical state machine).

## Edge cases

- **Zero containers** — happens for pure-docs projects or if the user
  drops every candidate. Surface a warning and offer to EXIT.
- **Duplicate names** — the agent never silently dedupes. Surface the
  conflict and ask which to keep.
- **Container archetype mismatch** — if the user changes a container's
  archetype mid-session, recompute `suggested_components` for the
  container-mode interview on resume.

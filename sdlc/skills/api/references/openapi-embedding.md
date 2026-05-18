# OpenAPI 3.1 embedding — what's in scope, what's not

Read this when entering **theme 10 (`per_resource_deepdive`)** or
**Phase 7 (write & validate)** for any non-`none` API.

`sdlc:api` embeds OpenAPI 3.1 operation objects inside per-resource
yamls (and OpenAPI 3.1 component schemas in both per-resource yamls
and the shared `API.yaml.shared_schemas`). The full OpenAPI spec is
too permissive for downstream coding agents, so the skill works with a
deliberately constrained subset.

## Why a subset

OpenAPI 3.1 has many features aimed at human readers (Markdown
descriptions, examples galleries, server variables, callbacks, links,
discriminators, `xml`). Downstream coding agents don't need any of
these; they add ambiguity and complicate validation. The subset below
keeps everything a code generator needs and drops the rest.

## Supported OpenAPI 3.1 keywords

### Per-endpoint (inside an entry in `endpoints[]`)

Required for `status: complete`:

- `operation_id` — kebab or snake-case unique id (used by downstream
  codegen for function names).
- `method` — `GET | POST | PUT | PATCH | DELETE | HEAD | OPTIONS`.
- `path` — full HTTP path; usually starts with the resource's
  `base_path`. Surface deviations as a warning during deep-dive.
- `summary` — one-line description.
- `responses` — at least one entry; each entry is an OpenAPI response
  object with `description` + `content` (when a body is returned).

Optional:

- `description` — longer description (one paragraph max — terser is
  better for AI consumers).
- `tags` — list of strings.
- `parameters` — list of OpenAPI parameter objects; `in` ∈ `path |
  query | header` only (cookie parameters are out of scope).
- `requestBody` — OpenAPI requestBody object.
- `security` — list of OpenAPI security requirement objects; names
  match `API.yaml.auth.schemes` entries.

SDLC siblings (alongside the OpenAPI keys; stripped before any
OpenAPI tool round-trip):

- `idempotent` — `true | false | null`; `null` means "inherit
  `API.yaml.idempotency.idempotent_methods`".
- `rate_limit_override` — string; `null` means "inherit
  `API.yaml.rate_limiting`".
- `auth_override` — string; `null` means "inherit
  `API.yaml.auth.default_visibility`".

### Per-schema (inside `schemas:` or `shared_schemas:`)

Required:

- `type` — usually `object`; primitives (`string`, `integer`, …) for
  scalar aliases.
- `properties` — for `type: object`. Each property is a JSON Schema
  2020-12 subset.

Recommended:

- `required` — list of property names that are non-null.
- `description` — one-line, optional.
- `projects_from` — SDLC sibling. The DATA entity name this DTO
  projects from. Set to `null` for DTOs that don't map to a single
  entity (e.g. paginated list wrappers, search response).

### Per-property (a JSON Schema 2020-12 subset)

In scope:

- `type` — `string | integer | number | boolean | array | object | null`.
- `format` — common formats only: `uuid | date | date-time | email |
  uri | ipv4 | ipv6 | hostname | byte | binary | int32 | int64 |
  float | double`.
- `enum` — list of allowed values.
- `default` — used by downstream codegen; only meaningful for
  optional properties.
- `nullable` — boolean. (OpenAPI 3.1 uses `type: [..., 'null']`; the
  shorthand `nullable: true` is also accepted and rewritten on
  round-trip.)
- `minLength`, `maxLength`, `pattern` — for `type: string`.
- `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`,
  `multipleOf` — for numeric types.
- `minItems`, `maxItems`, `uniqueItems` — for arrays.
- `items` — required for arrays.
- `$ref` — references; see below.

Out of scope (do NOT use):

- `xml`, `externalDocs`, `discriminator`, `callbacks`, `links`,
  `servers`, `securitySchemes` at the operation level, `example`,
  `examples`. Use `description` for any human-readable hint a
  downstream agent might benefit from.
- `oneOf` / `anyOf` / `allOf` — out for v1 because they complicate
  codegen for DTOs. Polymorphism is a v2 problem.
- `not` — out.

## `$ref` syntax — three flavours

### 1. Within the same file

Standard OpenAPI:

```yaml
schemas:
  User:
    type: object
    properties:
      address:
        $ref: "#/components/schemas/Address"
  Address:
    type: object
    ...
```

`#/components/schemas/<Name>` is supported (the validator rewrites
this to `#/schemas/<Name>` on read — we don't use the OpenAPI
`components` wrapper since `schemas:` is at the top level of the
resource yaml).

### 2. To `API.yaml.shared_schemas` (cross-file)

For schemas shared across ≥2 resources (e.g. `Money`, `Pagination`,
RFC-7807 `Problem`):

```yaml
schemas:
  User:
    type: object
    properties:
      balance:
        $ref: "../API.yaml#/shared_schemas/Money"
```

The relative path `../API.yaml` works because `docs/API.yaml` and
`docs/API__<resource>.yaml` are siblings.

### 3. To `DATA-MODEL.yaml` entities (cross-skill)

DTOs may reference DATA entities directly using a custom scheme that
downstream agents resolve at codegen time:

```yaml
schemas:
  User:
    projects_from: User
    type: object
    properties:
      profile:
        $ref: "data-model://Profile"
```

`data-model://<EntityName>` is the SDLC convention. The validator
checks that `<EntityName>` exists in `DATA-MODEL.entities` as part of
the entity-link check. Downstream agents resolve this to the
appropriate ORM type (TypeORM, Prisma, SQLAlchemy, …) when
generating code.

## DTO-vs-entity discipline (the most important rule)

Schemas in API__<resource>.yaml (and in `API.yaml.shared_schemas`)
are **wire DTOs**, NOT persistent entities. The line:

- **Persistent entity** = a row in storage (ORM model, database
  schema, document store). Defined in `docs/DATA-MODEL.yaml`.
  Includes fields like `password_hash`, `internal_flags`,
  `soft_deleted_at`, server-only metadata.
- **DTO (Data Transfer Object)** = the shape sent over the wire to a
  client. May omit persistence-only fields, rename for client
  ergonomics, add computed fields. Defined in this skill.

Examples of the difference:

| Concern | DATA entity (`User`) | API DTO (`User`) |
|---|---|---|
| Authentication hashes | `password_hash: string` | omit |
| Soft-delete flags | `deleted_at: timestamp\|null` | omit; filter on read |
| Internal state | `internal_state: enum` | omit |
| Public id | `id: uuid` | `id: uuid` |
| Email | `email: string` | `email: string` (often omit for non-admin DTOs) |
| Computed fields | n/a | `full_name: string` (computed from first+last) |
| Renamed fields | `created_at: timestamp` | `created_at: timestamp` (or `createdAt` for JS clients) |

When in doubt: ask the user during theme 10. Suggest sane projections
(`User`, `UserCreate`, `UserUpdate`, `UserPublic`) and let them
override.

## OpenAPI deep-validation is out of scope for v1

`validate_schema.py` validates the SDLC shape of each endpoint
(required keys, methods, etc.) but does NOT call out to an OpenAPI
validator like `openapi-spec-validator`. Reasons:

1. The SDLC-specific siblings (`idempotent`, `rate_limit_override`,
   `auth_override`, `projects_from`) and the custom `$ref` forms
   above would be flagged as invalid by a strict OpenAPI validator
   without preprocessing.
2. Downstream coding agents will typically synthesize a fresh
   OpenAPI document from the SDLC artifacts and validate that — full
   round-trip parity isn't useful here.
3. Pinning an `openapi-spec-validator` version drags in a sizeable
   transitive dependency tree.

This is a deliberate v1 trade-off. A future version may add
preprocessing + opt-in deep validation.

## Mapping back to a vanilla OpenAPI document (downstream-agent
recipe)

For agents that want a strict OpenAPI 3.1 document for codegen tooling:

1. Start with a fresh document:
   ```yaml
   openapi: 3.1.0
   info:
     title: <PRD.product_identity.name>
     version: <API.yaml.versioning.current_version>
   paths: {}
   components:
     schemas: {}
   ```
2. For each resource in `API.yaml.resource_inventory`, load its
   `API__<resource>.yaml`:
   - For each endpoint, write to `paths[<path>][<method>]` as a vanilla
     OpenAPI operation. **Strip** the SDLC siblings (`idempotent`,
     `rate_limit_override`, `auth_override`).
   - For each schema in the resource's `schemas`, write to
     `components.schemas[<name>]`. **Strip** the SDLC sibling
     `projects_from`.
3. For each entry in `API.yaml.shared_schemas`, write to
   `components.schemas[<name>]` as well. **Resolve cross-file `$ref`**
   from `../API.yaml#/shared_schemas/<Name>` to
   `#/components/schemas/<Name>`.
4. **Resolve `data-model://<EntityName>` `$ref`s**: substitute the
   DATA entity's shape (from `docs/DATA-MODEL.yaml.entities[<Name>]`)
   under `components.schemas[<EntityName>]` and rewrite the `$ref` to
   `#/components/schemas/<EntityName>`.

This is a deterministic transform — every downstream agent should
produce the same OpenAPI document from the same SDLC artifacts.

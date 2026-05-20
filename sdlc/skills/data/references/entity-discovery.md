# Entity discovery heuristics

How to derive the *draft* entity list in Phase 3 from PRD + UX + repo
signals. This phase is the most hallucination-prone in the whole skill,
because entities are nouns and nouns appear in every requirement
description. Read this before Phase 3.

## Source priority

1. **`PRD.data_model.key_entities`** — the user already named these.
   Treat verbatim. Tag `✓ found`.
2. **Schema files on disk** (`schema.prisma`, `*.sql`, `models/`,
   `entities/`, Django `models.py`, SQLAlchemy `declarative_base`
   subclasses) — authoritative if present. Tag `✓ found`.
3. **`PRD.functional_requirements.must_have_features`** (FR-NNN list) —
   extract candidate entity nouns. Tag `⚠ inferred`.
4. **`UX__<surface>.yaml.layout` + `validation_rules` +
   `components.content_slots`** — forms imply entities; list items imply
   entities; filters imply entities. Tag `⚠ inferred`.

Higher-priority sources override lower ones. If PRD names `User` and a
UX form has a field labelled "Account", treat them as the same entity
(prefer the PRD name) unless the user disambiguates.

## Heuristics for extracting entities from FR-NNN features

A typical PRD feature reads like: *"FR-001: Quick add a task with a
keyboard shortcut."* The candidate entity is the **direct object of the
main verb**, capitalized and singularized:

| Verb pattern              | Likely entity        |
|---------------------------|----------------------|
| `add/create/insert <X>`   | `<X>` (singularized) |
| `delete/remove <X>`       | `<X>`                |
| `update/edit/modify <X>`  | `<X>`                |
| `list/show/view <X>`      | `<X>` (plural form in UI implies entity exists) |
| `assign <X> to <Y>`       | `<X>` and `<Y>`; expect a relationship |
| `share <X> with <Y>`      | `<X>`, `<Y>`, and a join entity (e.g. `<X>Share`) |
| `notify <X> when <Y>`     | `<X>`, plus a `Notification` or `Event` entity |
| `import/export <X>`       | `<X>` plus possibly `Import`/`Export` job entities |
| `audit <X>` / `track <X>` | `<X>` plus an `AuditLog` entity |

Treat these as **candidates only**. Each must surface in Phase 3 with the
source FR-NNN ID quoted, so the user can correct.

## Heuristics for extracting entities from UX surfaces

Read each `docs/UX__*.yaml`. For each surface:

- **`layout.region_tree`** — region names like `task-list`, `user-card`,
  `order-summary` strongly imply the kebab-cased noun is an entity.
  Convert to PascalCase: `Task`, `User`, `Order`.
- **`components`** — a component with `type: list` or `type: table` whose
  rows are named (e.g. `row_template: TaskRow`) implies the entity.
- **`validation_rules`** — a rule like `field: "email"` implies a form
  field; the form's submission target is usually an entity.
- **`interactions.effects`** — strings like `"create task in store"`,
  `"update user profile"` are direct signals.
- **`cli_args`** (CLI surfaces) — positional args often map to entity IDs
  (e.g. `task-id`, `user-id`).

A surface that has no `validation_rules` and no list/table component is
probably *not* a data-bearing surface (e.g. a marketing splash page,
loading screen). Such surfaces do not contribute entity candidates.

## Heuristics for relationships at discovery time

While drafting candidates, also draft **probable relationships**. The
following imply edges:

- Two entities named together in one FR-NNN feature → likely related.
- A UX surface that displays one entity but filters/sorts/links by
  another → many-to-one foreign key.
- A "list of X within Y" pattern (e.g. "list tasks within a project") →
  `1:N` from Y to X.
- A "tag", "label", "category" suffix → typically `N:M` with a join
  table (e.g. `TaskTag`).

Surface these as proposals during Phase 6's `relationships` theme. Do not
quietly write them.

## What NOT to do

- **Don't invent abstract "Manager" or "Service" entities**. Those are
  application-layer concepts, not data entities. If you see `TaskManager`
  in the PRD, that's likely a service, not a row in a table.
- **Don't propose `Settings` or `Configuration` entities unless there's
  explicit evidence**. Most apps store config in env vars or
  filesystem files, not the DB.
- **Don't propose audit/log entities unless audit_logging is enabled
  in PRD**. If you do propose them, label clearly as `⚠ inferred from
  PRD.security_compliance.audit_logging`.
- **Don't fold two distinct nouns into one entity** to be "clever". If
  PRD names both `Order` and `LineItem`, keep them separate even if you
  could imagine modelling lines as a JSON column on Order.
- **Don't propose junction/join entities until the relationship theme**.
  Discovery is for first-class nouns. N:M join entities surface naturally
  when the user confirms a many-to-many relationship.

## Surfacing candidates to the user

Present the draft list as:

```
I found these entity candidates:

  ✓ User                  (from PRD.data_model.key_entities)
  ✓ Project               (from PRD.data_model.key_entities)
  ✓ Task                  (from schema.prisma model Task)
  ⚠ Tag                   (inferred from UX__dashboard form 'tags')
  ⚠ Comment               (inferred from FR-003 "Add a comment to a task")
  ⚠ Notification          (inferred from FR-007 "Notify users when …")

Add, remove, rename, or skip any of these before we go deep. Each ⚠
needs your explicit confirmation — type 'confirm Tag', 'rename Tag→Label',
'drop Notification', or describe what you'd rather have.
```

Persist the confirmed list to `state.defined_entities` as a list of
`{name, status: confirmed|dropped, source}`. Dropped entries go to
`state.dropped_entity_candidates` so they don't get re-proposed on resume.

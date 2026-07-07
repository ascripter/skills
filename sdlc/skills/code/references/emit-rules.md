# Emit rules — kind → write behavior, provenance, path safety (sdlc-code)

Read this on entering Phase 4. It defines what each task kind writes, how
several tasks share one file, where paths come from, and the provenance
markers.

---

## Path resolution — the ladder

Every write target is resolved in this order; take the first rung that yields
paths and note the rung in the ledger entry (`path_source`):

1. **`target_files`** — authoritative when present. For `implementation`
   tasks it is validator-guaranteed: exactly one entry.
2. **Path-shaped `outputs`** — entries that look like repo-relative file paths
   (contain `/` or a file extension, no spaces-only prose). The gold task
   fixtures use this style for `scaffold`/`test` tasks.
3. **Component `code_location` + stack conventions** — the owning component's
   `code_location` directory from `ARCH__<cid>.yaml`, with the filename
   derived from the target (`<symbol|entity|tst>` in the stack's naming
   convention, e.g. `tests/test_<component>.py`, `src/controllers/tasks.ts`).
4. **Ask** — one AskUserQuestion naming the task and proposing a path
   (position-1 recommended). Never invent silently below rung 3.

## Path safety (hard rules)

- All paths are **repo-relative to the consumer project root**. Reject
  absolute paths and any path containing `..` — refuse the task with a clear
  message; that is a task-graph bug to fix in `/sdlc:task`, not something to
  route around.
- **Placement drift is advisory**: a component-scoped write landing outside
  the component's `code_location` gets a warning in the close report (the same
  severity task's validator gives it) but proceeds — `target_files` is the
  contract.
- Create missing parent directories; never delete or move existing files. A
  task whose semantics seem to require deleting something goes to a gate.

## Multiple tasks, one file

Routine: a controller file accumulates one exported function per task
(gold: TSK-004/005/006 all pin `src/controllers/tasks.ts`).

- The **first** task to touch a file this factory creates it: file header
  (below), the stack's module scaffolding (imports, class shell if
  `target_symbol` is `Class.method`), then the task's own symbol.
- **Later** tasks Edit-insert their symbol at the idiomatic position (inside
  the existing class for `Class.method`, appended after the last export
  otherwise) and merge — never rewrite — the import block.
- **Never rewrite an existing symbol** that belongs to another task (its
  marker names its owner). The only symbol a task may replace is its own
  (marker matches its qualified id) — that's the regeneration path.
- A needed symbol that already exists **without** a marker is pre-existing
  user code: stop, ask (adopt it as-is and mark the task done / replace it /
  skip the task). Never assume ownership of unmarked code.

Class-shell note: when work_units are `Class.method` style, the class shell
belongs to the *first* task that needs it and carries no marker of its own —
markers annotate symbols (methods), not scaffolding.

## Rendering an `implementation` task

The deliverable's shape comes from the task's **embedded contract** (schema
v1.3), never from imagination:

1. Read the task's `interface_contract` — `inputs`/`output`/`raises` are the
   frozen shape (`source: work_unit` = declared in ARCH; `source:
   api_operation` = resolved from the operation named in `operation_id`).
   Render the signature from them in the container's stack; `raises` entries
   like `"ValidationError -> 400"` become the error path. If `signature` is
   set, it IS the contract — use it verbatim.
2. **Pre-1.3 fallback** (no `interface_contract` on the task): look up
   `work_units[name == target_symbol]` on the `component_ref` component in
   `ARCH__<cid>.yaml`; when that unit defers via `traces_api_operation`, the
   API operation's request/response/exception schemas are the contract.
3. **`unit_kind` selects the rendering mode** (default `callable`):
   - `callable` — render the method/function per the contract, marker above
     the symbol.
   - `module` — the file's **definition set is the interface** (e.g. a
     schemas module): emit the whole module named by `target_symbol`;
     marker + producing task go in the file header.
   - `content` — a shipped content file (prompt pack, template, inventory):
     author the content the `description`/`unit_summary` specifies.
   - `tooling` — a standalone tool/validator script; `acceptance` usually
     names its exit-code contract.
   All four keep the same invariants — one deliverable, one `target_files[0]`
   entry — only the rendering differs.
4. Body: implement the task's `description` (+ `unit_summary`) against the
   task's `acceptance`. `touches_entities` names the DATA-MODEL entities whose
   field definitions you must respect — read their INDEX slices;
   `implements` names the FR/NFRs — read their PRD lines only when the
   description is not self-sufficient.
5. Real implementations only — no `TODO` stubs, no `NotImplementedError`
   placeholders. If the contract is too thin to implement honestly, that's a
   gate ("this work_unit's contract doesn't determine behaviour X"), not a
   stub.
6. Language/stack: the container's declared stack in `ARCH.yaml` /
   `ARCH__<cid>.yaml` (the one container-general upstream fact). Match the
   conventions the scaffold task established (formatting, import style, error
   idioms) — the file should read as one hand.

## Rendering the other kinds

- **`scaffold`** — the file set from the ladder: package manifest, workspace
  config, entrypoint, test-harness config. `acceptance` defines "works"
  (`pnpm install resolves`, `app boots`); run it as the static ring.
- **`test`** — the task's embedded `test_spec` (`tier`, `directives`,
  `acceptance`, `covers`) is the spec; author runnable tests that exercise the
  *contract* of the implementation(s) this task `depends_on`. Pre-1.3
  fallback: the TST entry in `TEST-STRATEGY__<cid>.yaml`. Name each test so
  the TST id is visible (test name or marker comment) — Stage-15 verification
  keys results to TST ids.
- **`integration`** — the wiring the edge describes: register routes into the
  app, bind DI, or build the consumer-side client against the provider's
  contract (`touches_operations` → API schemas). Cross-container `integration`
  tasks in `TASKS.json` wire consumer code to the provider's *contract*, never
  reach into the provider's internals.
- **`migration`** — DDL/schema/ORM-migration files for `touches_entities`,
  fields and relations from the DATA-MODEL entity slices. The entity
  realization unit — repositories then query what this task created.
- **`config`** — typed settings loading + env plumbing (`.env.example`,
  settings module). Placeholder *values* for secrets, never real ones;
  secrets backends belong to `/sdlc:deploy`.
- **`design`** — token/theme files from `DESIGN__tokens.yaml`; for asset
  pipelines, the folder scaffold + one `assets/<name>.brief.md` sidecar per
  AST in `touches_assets` (the brief's content comes from
  `DESIGN__assets.yaml`).
- **`chore` / `docs` / `deploy-prep`** — per `description` + the ladder.
  `deploy-prep` stops at handoff stubs (CI skeleton, Dockerfile placeholders)
  — `/sdlc:deploy` owns the real thing.

## Provenance markers

One line per generated symbol, in the language's comment syntax, immediately
above the symbol:

```
// sdlc-code: backend-api/TSK-005 (createTask)        TypeScript/JS/Rust/Go…
# sdlc-code: backend-api/TSK-011 (DigestRun.compute)  Python/Ruby/shell/YAML
<!-- sdlc-code: web-frontend/TSK-004 (TaskList) -->   HTML/Vue SFC…
```

Grammar: `sdlc-code: <qualified-task-id> (<target_symbol>)` — the qualified id
uses the same `<file>/TSK-NNN` syntax as `depends_on` (`TASKS/…` for system
tasks). For non-implementation tasks the parenthesis names the deliverable
(`(scaffold)`, `(TST-003)`, `(schema.prisma)`).

Files **created** by this skill open with a header comment:

```
// generated by sdlc-code — tasks: backend-api/TSK-004, backend-api/TSK-005
```

Maintain the header's task list as later tasks join the file. Files that exist
before this skill touches them get symbol markers only — no header (we don't
claim files we didn't create).

Why markers matter (they are not decoration): they are the **idempotency
probe** (symbol marker present + ledger hash match = already generated), the
**ownership test** in the merge rules above, and the reverse-lookup anchor
(code → TSK → FR/TST) that keeps hand-edits diagnosable. Do not strip them
when healing; update them when regenerating.

## What NOT to write

- No derived counts or task statistics in generated prose/docstrings
  (CLAUDE.md §8 — they go stale silently).
- No provenance *narrative* ("this function was generated because task …") —
  the one-line marker is the entire provenance surface in code; the manifest
  carries the rest.
- Nothing outside the task's write targets except the merges this file
  defines (imports, header task-list, class shell).

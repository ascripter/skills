# Merge, validate & close (sdlc-task)

Read this on entering Phase 7. Covers: why the artifact is JSON, the merge logic
for an existing file, the full cross-check suite, the recovery flow on `[FAIL]`,
the CLAUDE.md pointer rules, and the downstream-rejection rule.

---

## Why the task graph is JSON (not YAML)

Every other SDLC artifact is YAML; the task graph is the deliberate exception.
The decision turns on how the artifact is *produced and consumed*:

1. **It is generated and machine-consumed, not interview-authored and
   human-reviewed.** The upstream specs (PRD, UX, DATA, API, ARCH, TEST) are
   built through long interviews and scrutinized by a human at every HITL gate —
   there, YAML's inline comments and readability earn their keep. The task graph
   is "mostly an autonomous generation node + sweep + approval" (FR-013); its one
   real consumer is the Stage-14 code-generation agent, which fans out per task.
   The single place YAML's comment/readability edge pays off is absent here.
2. **It is a large, regular graph.** 20–200 near-identical task objects plus
   dependency edges (FR-013's expected `TSK-###` count). That is a data
   structure, not a document — JSON arrays of uniform objects are the natural
   fit.
3. **It gets programmatically stitched and topologically sorted.** Per-container
   subgraphs are merged into one global graph, deps resolved, the DAG checked and
   ordered. A clean `json.load → manipulate → json.dump` cycle beats YAML
   round-tripping (which loses comments and ordering anyway, defeating the only
   reason to have chosen YAML).
4. **It maps 1:1 onto the codegen agent's structured output.** The demo PRD runs
   `structured_output` (Pydantic/JSON-schema) on every stage; JSON is the native
   interchange for tool/agent consumption.
5. **Strict, unambiguous parse.** No YAML footguns (the Norway problem,
   `on/off` booleans, accidental multiline) on fields that hold ids, shell-ish
   command hints in `outputs`, and free-text `acceptance`.

The human-readable **schema** is still written as commented YAML
(`TASKS.schema.yaml`, `TASKS__CONTAINER.schema.yaml`) so it reads like its
siblings — only the runtime artifact is JSON. The validator loads the artifact
with `json.load`; it still reads the upstream YAML specs with `yaml.safe_load`.

> If you ever reconsider: the cost of JSON is one mixed format in `docs/` and
> slightly worse hand-edit ergonomics. Given the artifact is regenerated rather
> than hand-tuned, that cost is small and the consumer-side wins dominate.

---

## Merge logic (when the output already exists)

If `docs/TASKS.json` (system) or `docs/TASKS__<container>.json` (container)
already exists, this is an update — not a fresh write:

- Load the on-disk JSON as the **baseline** (authoritative for *answers*; it may
  have been hand-edited).
- Overwrite a key only where the user changed it this session; add new tasks;
  preserve unrecognized keys you didn't touch.
- For a task the session would *remove*, confirm with the user before deleting —
  a downstream artifact or another file's `depends_on` may reference its
  `TSK-NNN`.
- **Never renumber `TSK-NNN`.** Once written, a task id is stable. Reconcile the
  `state.last_ids.TSK` counter to `max(on_disk, state)` on resume so new tasks
  don't collide or leave gaps.
- Surface conflicts (user-edited JSON vs. state-file `partial_answers`) — never
  auto-resolve.
- Append, don't rewrite, `metadata.changelog`; (re)write
  `metadata.upstream_provenance` (replace-on-write).

For a re-run triggered by an **upstream change**, run the delta-review pass first
(SKILL.md Phase 2 → CLAUDE.md §7;
`sdlc/skills/ux/references/upstream-reconciliation.md`).

---

## The cross-check suite (what `validate_schema.py` enforces)

Run from the project root:

```bash
python sdlc/skills/task/validate_schema.py --path docs/TASKS.json
```

`--path` only locates `docs/`; the system file + every sibling `TASKS__*.json`
are validated together (the union-graph check needs them all).

**Blocking (force `status: draft`; a file claiming `complete` with any of these
FAILs the run, exit 1):**

1. Required-field completeness — every REQUIRED field non-null; `tasks`
   non-empty; every task's `outputs` + `acceptance` non-empty; system
   `build_order` non-empty.
2. `TSK-NNN` format + uniqueness per file; `WRN-NNN` format; `kind` in the
   mode's allowed set.
3. Scope integrity — every `implementation` task has `component_ref` OR
   `touches_operations`; every `component_ref` resolves to a component in
   `ARCH__<cid>.yaml`.
4. `implements` integrity — FR/NFR format, resolves to PRD, ⊆ the
   container's/component's `implements_requirements`.
5. `implements_tests` integrity — `TST-NNN`, resolves to the matching
   `TEST-STRATEGY(.__cid).yaml`; `kind:test` must set one.
6. Reference integrity — `involves_containers` / `build_order` resolve to
   `ARCH.yaml` containers.
7. **The stitch** — every `depends_on` resolves across the union of all task
   files; the union graph is **acyclic**.
8. Coverage (trace-or-defer) — container: every component_id + every container
   `TST-NNN`; system: every system `TST-NNN`.

**Non-blocking warnings:** requirement coverage (transitive); cross-container
edge coverage; `build_order` provider-before-consumer order; `container_task_graphs`
file existence; missing optional enrichers; an upstream with `status != complete`.

`metadata.status` → `complete` only when the validator prints `[OK]` *and* it is
not a draft; otherwise `draft`.

### Recovery flow on `[FAIL]`

The validator prints field-level errors. For each:

- a coverage gap → add the missing task, or `defer <id>` with a reason
  (`coverage-and-defer.md`);
- a dependency cycle → fix the offending edge (the path is printed); usually a
  test↔impl edge pointing the wrong way;
- an unresolved `depends_on` / `component_ref` / `implements_tests` → fix the ref
  or build the missing upstream;
- a scope error → split the task or add `component_ref`/`touches_operations`.

Offer interactive re-entry via `AskUserQuestion`, then re-run the validator. Loop
until `[OK]` or the user accepts a `draft`.

---

## CLAUDE.md pointer rules

Call `set_claude_md_pointer.py` in Phase 8. It is deterministic and idempotent:
creates the `## SDLC Documents` section if missing; updates the timestamp if the
`sdlc-task` bullet already exists; appends the bullet otherwise; never reorders or
edits unrelated content. `--dry-run` previews. The bullet is keyed on the
substrings `` `docs/TASKS.json` `` and `` `sdlc-task` ``, so it never collides
with another skill's bullet.

---

## Downstream-rejection rule

A downstream consumer (the code-generation stage, or any agent) MUST reject
`docs/TASKS.json` / `docs/TASKS__<container>.json` if `metadata.status !=
"complete"` OR if `validate_schema.py` exits non-zero. A non-zero exit means a
coverage gap, a dependency cycle, an unresolved reference, or a malformed id —
any of which would make the codegen factory build the wrong thing or fail to
start. The status gate + the validator exit code are the contract; honour both.

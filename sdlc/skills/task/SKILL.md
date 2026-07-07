---
name: task
description: >
  Explicitly invoked skill. Two modes: (a) /sdlc:task — the SYSTEM task graph
  (repo/monorepo scaffold, cross-container integration tasks, the system-level
  e2e/contract test tasks, the topological build_order, and the registry of
  per-container subgraphs) written to docs/TASKS.json; (b) /sdlc:task <container>
  — the per-container task subgraph (dependency-ordered scaffold + atomic
  per-work_unit implementation tasks + first-class test tasks + within-container
  wiring) written to docs/TASKS__<container>.json. A third form, /sdlc:task --next,
  auto-advances: it resolves to the next ready container that has no task graph,
  then to system mode once every container is done, and reports completion once
  the whole graph is stitched. Trigger only on /sdlc:task or a direct
  natural-language request to start the task-breakdown skill — never auto-trigger
  from generic chatter about tasks or todos. Reads docs/ARCH.yaml,
  docs/TEST-STRATEGY.yaml (system), and per container docs/ARCH__<container>.yaml
  + docs/TEST-STRATEGY__<container>.yaml as required preconditions and refuses to
  run if any is missing or its metadata.status != complete. docs/DATA-MODEL.yaml,
  docs/API.yaml (+ API__*), docs/UX.yaml, docs/DESIGN.yaml (+ DESIGN__*), and
  docs/PRD.yaml are read for id resolution and the surface/operation/entity/
  design coverage gates.
user-invocable: true
disable-model-invocation: true
model: opus
effort: high
allowed-tools: Read Write(CLAUDE.md) Write(docs/TASKS.json) Write(docs/TASKS__*.json) Write(.claude/skills-state/sdlc-task.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---

# sdlc-task

Guides the user through a structured interview that produces a validated,
**dependency-ordered task graph** — the executable backlog the downstream
code-generation factory fans out over. Two artifacts:

- a **system** `docs/TASKS.json` — repo/monorepo scaffold tasks, cross-container
  integration tasks, the system-level (e2e/contract) test tasks, the
  topological `build_order`, and the registry of per-container subgraphs;
- one **container** `docs/TASKS__<container>.json` per buildable container —
  that container's scaffold, per-component implementation tasks, first-class
  test tasks, and within-container wiring.

Container tasks are **self-contained for codegen** (schema v1.3): each
implementation task embeds its work_unit's interface contract
(`interface_contract`, plus `unit_kind`/`unit_summary`) and each test task
embeds its TST's specifics (`test_spec`), so `/sdlc:code` acts on a task
without per-task ARCH/TEST-STRATEGY lookups — only container-general facts
(tech stack) stay upstream.

This is the SDLC factory's Stage-13 "Task Breakdown": per-container task
subgraphs are produced one container at a time, then **deterministically
stitched** into one global dependency-ordered graph via `build_order` and
cross-file `depends_on` edges. Each task is **scoped to one component or one
contract**, with explicit `inputs` / `outputs` / `acceptance` — and **test
tasks are first-class**, peers of implementation tasks, never an afterthought.

The task graph is not prose. Every task is a typed `TSK-NNN` item with a `kind`,
a scope (`component_ref` or `touches_operations`), `depends_on` edges, and a
machine-checkable `acceptance`. The validator enforces a **trace-or-defer
coverage contract** (every component and every test realized by a task or
explicitly deferred) plus a **union-graph acyclicity check** (the stitch must be
topologically sortable) so the codegen agent receives a buildable, complete plan.

> **Output format is JSON, not YAML.** The task graph is the one sdlc artifact
> written as JSON (`docs/TASKS.json`, `docs/TASKS__<container>.json`). It is
> machine-generated and machine-consumed — a large, regular graph that gets
> programmatically stitched and topologically sorted — so JSON's clean
> load→manipulate→dump cycle and native fit with the codegen agent's
> structured-output beat YAML's comment/readability edge (which pays off for the
> interview-authored, human-reviewed upstream specs but is wasted here). See
> `references/merge-validate.md` → "Why the task graph is JSON".

## What this skill does (at a glance)

The skill runs in **one of two interview modes**, dispatched on the invocation
form — plus a `--next` resolver that picks the right mode for you:

| Invocation                  | Mode                       | Output                                       |
|-----------------------------|----------------------------|----------------------------------------------|
| `/sdlc:task`                | system interview           | `docs/TASKS.json`                            |
| `/sdlc:task <container>`    | container interview        | `docs/TASKS__<container>.json`               |
| `/sdlc:task --next`         | resolver → one of the above| (whatever the resolved form produces)        |

Both modes follow the canonical 8-phase flow (Phase 1 → Phase 8 below). State is
persisted **after every confirmed batch and after every per-item task
drill-down**, so the user can `EXIT` at any time without losing progress.

**System file vs. container file — what goes where.** Tasks are scoped by how
many containers they touch:

- **System** (`TASKS.json`): work with no single owning container — repo/monorepo
  scaffolding, shared libraries/contracts, cross-container integration tasks
  (realizing `ARCH.yaml` `calls`/`depends_on` edges), the system-level test
  tasks (realizing the `TEST-STRATEGY.yaml` e2e/contract suite), deploy-prep
  handoff, plus the **stitch**: `build_order` (providers before consumers) and
  the `container_task_graphs` registry.
- **Container** (`TASKS__<container>.json`): work scoped to one container — its
  `scaffold` task, one `implementation` task **per component work_unit** (its
  `target_symbol` = the work_unit name, in a single `target_files`), one `test`
  task per `TST-NNN` in its test strategy, and `integration` tasks for its
  internal edges.

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow itself. |
| `task-questions.yaml` | Question inventory; each theme tagged with `mode: system | container`. |
| `TASKS.schema.yaml` | Human-readable canonical schema for `docs/TASKS.json`. |
| `TASKS__CONTAINER.schema.yaml` | Human-readable canonical schema for `docs/TASKS__<container>.json`. |
| `validate_schema.py` | Pydantic v2 validator (system + every container file + coverage + the union-graph acyclicity check). Loads the JSON artifacts. |
| `count_work_units.py` | Deterministic, plumbing-aware per-component work_unit counter for an `ARCH__<container>.yaml` — a real YAML parse, never a grep. Run it in Phase 2 preflight; quote its output in any readiness/refusal message. |
| `set_claude_md_pointer.py` | Deterministic CLAUDE.md pointer injector, called in Phase 8. |
| `references/interview-mechanics.md` | AskUserQuestion batch format, EXIT semantics, importance-tier flows. Read on entering Phase 6. |
| `references/task-discovery.md` | How to seed the task graph from ARCH components + TEST tests + API + DATA (system and container). Read in Phase 3. |
| `references/granularity-and-ordering.md` | Atomic slicing (one implementation task per work_unit — always), dependency ordering, the topological build_order, and the deterministic cross-file stitch. Read in Phases 3–6. |
| `references/coverage-and-defer.md` | The trace-or-defer coverage contract (component + test coverage) and the WRN-NNN deferral mechanism. Read in Phase 6 and Phase 7. |
| `references/merge-validate.md` | Merge logic, the cross-check suite, the JSON rationale, CLAUDE.md pointer rules, the downstream-rejection rule. Read on entering Phase 7. |
| `references/edge-cases.md` | Unusual situations and their handling. |

Runtime files (NOT inside this skill directory):

| File | Purpose |
|---|---|
| `docs/TASKS.json` (project root) | System-level task graph. |
| `docs/TASKS__<container>.json` (project root) | Per-container task subgraph. |
| `.claude/skills-state/sdlc-task.state.yaml` | Session state for resumability. |
| `CLAUDE.md` (project root) | Pointer bullet injected on completion. |

## Reserved EXIT command

At any prompt, the user can type `EXIT` (case-insensitive) into the free-text
field of any `AskUserQuestion` call to abort. State is *always* saved after each
confirmed batch — `EXIT` simply marks the active sub-session `status: aborted`
and stops. There is no `SAVE` command — saving is implicit.

## Invocation dispatch

After reading the `$ARGUMENTS` string, classify the invocation.

**`--next` resolver (runs before the classification below).** Note the order is
the **reverse of `sdlc:test`**: containers are specified FIRST, the system stitch
LAST. That is FR-013's model — per-container subgraphs are generated, then
deterministically stitched into the global graph. `build_order` and the
cross-file deps in `TASKS.json` can only reference container tasks that already
exist. If the first token is `--next` (no other positional args), resolve it to
a concrete form, then proceed exactly as that form:

1. **An in-progress sub-session exists** (any `sessions[*]` with
   `status: in_progress`) → resume it. `--next` means "continue the task work";
   never skip past unfinished work. Phase 1 handles the resume prompt.
2. **A ready, buildable container still has no `docs/TASKS__<container>.json`** →
   resolve to **container mode** for the next one (as if `/sdlc:task <cid>`). A
   container is **buildable** if it is a unit of behaviour worth its own task
   subgraph: `external: false` AND `archetype` NOT in the storage/infra set
   (`primary-database`, `secondary-database`, `cache`, `blob-store`,
   `search-index`, `message-bus`) AND not `external-service` — the same set
   `arch`/`test` refuse to drill. A buildable container is **un-specified** if it
   has no `docs/TASKS__<cid>.json` on disk. It is **ready** only if BOTH
   `docs/ARCH__<cid>.yaml` AND `docs/TEST-STRATEGY__<cid>.yaml` exist (container
   mode needs both — test tasks reference `TST-NNN`). Pick the first
   un-specified, ready, buildable container in **specification order** (below).
3. **A buildable container is un-specified but NOT ready** (missing
   `ARCH__<cid>.yaml` or `TEST-STRATEGY__<cid>.yaml`) → name it and tell the user
   which upstream to run first (`/sdlc:arch <cid>` and/or `/sdlc:test <cid>`),
   then continue with the next ready one. If none are ready, abort with that
   message.
4. **Every buildable, ready container has its `TASKS__<cid>.json`, but no
   `docs/TASKS.json` exists** → resolve to **system mode** (as if `/sdlc:task`).
   The stitch comes last: now `build_order` and cross-file deps can reference
   real container tasks.
5. **Every container is done AND `docs/TASKS.json` exists** → print and abort:
   > "All containers have a task graph and the system graph is stitched. To
   > change one explicitly, invoke `/sdlc:task <container-name>` or `/sdlc:task`.
   > Otherwise task breakdown is complete — go on with `/sdlc:deploy`."

Before launching a resolved interview, confirm the target with one
`AskUserQuestion` so `--next` never silently drops the user into a long
interview:
> "`<k>` of `<n>` buildable containers have task graphs. Next: `<id>`
> (`<archetype>`) [or: the system stitch]. Start it, pick a different target, or
> stop?"

Options: `"Start <target>"` / `"Pick another"` / `"Stop"`. On "Pick another",
list the remaining ready, un-specified containers (and "system stitch" if all
containers are done) and let the user choose. On "Stop", exit cleanly without
changing state.

**Specification order.** Build dependencies first so a consumer's tasks can
depend on a provider's contract tasks: order by ascending count of outgoing
`depends_on` + `calls` edges in `ARCH.yaml.edges` (providers before consumers),
tie-broken by `ARCH.yaml.containers[]` definition order. Reuse `arch`'s
`state.sessions.system.drill_order` or `test`'s `state.spec_order` when present;
otherwise compute it. On a cycle or no edges, fall back to definition order.
Persist the resolved order to `state.spec_order` so `--next` is deterministic
across sessions; recompute only when the container set changed. This same order
seeds `build_order` in system mode.

Otherwise, classify a non-`--next` invocation:

1. **No arguments** → **system interview mode**. Output: `docs/TASKS.json`. If no
   `docs/TASKS__*.json` exist yet, warn that per-container subgraphs are usually
   built first (`/sdlc:task --next`); offer to proceed anyway (repo-scaffold +
   system test tasks can still be authored, and `build_order` is seeded from
   ARCH regardless) or to switch to `--next`.
2. **One argument** → **container interview mode**. The argument is a
   `container_id`. It MUST exist in `ARCH.yaml.containers[].container_id`; if
   not, list valid container_ids and abort. It MUST be buildable (not external,
   not a storage/infra archetype); if not, explain and abort. Both
   `docs/ARCH__<cid>.yaml` and `docs/TEST-STRATEGY__<cid>.yaml` MUST exist; if
   not, tell the user which upstream to run first and abort. These existence +
   `status: complete` + validator checks are the **only** gates — do not invent
   others (git cleanliness, changelog counts, etc.). Output:
   `docs/TASKS__<container>.json`.
3. **More than one positional argument, or unknown flag** → print the three
   valid invocations and abort.

The skill **never** modifies a different mode's output. Container mode will not
touch `docs/TASKS.json` except, on first completion of a container, it may
register the new file under `container_task_graphs[]` and bump
`TASKS.json.metadata.last_updated` (the only fields container mode mutates in the
system file). System mode will not touch any `docs/TASKS__*.json`.

## Pre-flight checks (run before everything else)

Do filesystem lookups before the resume check (Phase 1):

```bash
ls docs/API.yaml docs/DATA-MODEL.yaml docs/UX.yaml docs/DESIGN.yaml 2>/dev/null
```

These optional enrichers sharpen task seeding and feed the coverage gates:
- `docs/API.yaml` (+ `API__*`) → operation-level work + the **operation-coverage**
  gate (every owned resource's `operation_id` realized or deferred).
- `docs/DATA-MODEL.yaml` → entity-level `migration` tasks + the **entity-coverage**
  gate.
- `docs/UX.yaml` → the slug↔`SCR` map the **surface-coverage** gate needs (every
  frontend container's `owns_ux_surfaces` realized or deferred).
- `docs/DESIGN.yaml` (+ `DESIGN__tokens`/`DESIGN__assets`) → `design` tasks
  (theme/token wiring, asset-brief sidecars) for frontend containers.

Record `api_present` / `data_present` / `ux_present` / `design_present` in the
active sub-session state. Absence is not an error — the dependent gate softens to
advisory — but note it in `task_warnings` (WRN-NNN) when it leaves a gap you would
otherwise have filled (e.g. UX absent ⇒ surfaces can't be coverage-checked).

Required preconditions are checked in Phase 2.

## The 8-phase flow

The phases are the same for both modes; the themes differ. Mode-specific themes
are listed under **System themes** / **Container themes**.

### Phase 1 — Resume check

Check for `.claude/skills-state/sdlc-task.state.yaml`:

- If it exists with `status: in_progress` for the **same mode** (and, for
  container mode, the same `container_id`), ask:
  > "I found an unfinished sdlc:task session (`<mode>` mode<, container=X>) from
  > `<last_updated>`. **Resume**, **restart** (discard previous answers), or
  > **discard** (delete state and exit)?"
- If `status: in_progress` but a *different* mode/container is requested, warn
  and offer to start a new sub-session alongside the existing one (the state file
  holds a `sessions:` map keyed by `mode|container_id`).
- If `status: complete` or `aborted` and the target output exists, treat this as
  an update flow — see `references/merge-validate.md`.
- If no state file, continue to Phase 2.

### Phase 2 — Scan inputs

Read upstream artifacts once at startup and validate each via its upstream
validator. **Slice large docs, don't slurp.** `DATA-MODEL.yaml` (and `PRD.yaml`)
are large; when `docs/INDEX.yaml` exists, look a symbol up in `INDEX.yaml` (or
`python .claude/sdlc/docs_index.py --show <symbol>`) and `Read` only its line
range. Fall back to whole-file reads only when `INDEX.yaml` is absent. Protocol:
`.claude/rules/sdlc-docs-access.md`.

Required upstream artifacts (all MUST exist with `metadata.status: complete`):

- **Both modes:**
  1. `docs/ARCH.yaml` — `python sdlc/skills/arch/validate_schema.py --path docs/ARCH.yaml`.
     Supplies containers, archetypes, and the inter-container edges that drive
     `build_order` and integration tasks.
- **System mode:**
  2. `docs/TEST-STRATEGY.yaml` — `python sdlc/skills/test/validate_schema.py --path docs/TEST-STRATEGY.yaml`.
     Supplies the system e2e/contract `TST-NNN` that become first-class test
     tasks.
- **Container mode:**
  2. `docs/ARCH__<container>.yaml` — the components (each a unit of
     implementation work), `implements_requirements`, and internal edges.
  3. `docs/TEST-STRATEGY__<container>.yaml` — the `TST-NNN` that become this
     container's first-class test tasks.

`docs/PRD.yaml` is read for FR/NFR id resolution (`implements`). Treat it as
required-for-resolution: if it is absent, the `implements` cross-checks soften to
format-only and a WRN-NNN is appended.

If any required validator exits non-zero, or any required artifact has
`metadata.status != complete`, **stop**. Print a clear message naming the
offending file and the upstream skill to run.

**The preflight is a CLOSED set of gates.** The ONLY preconditions for running
are the documented ones: `docs/ARCH.yaml` complete; in container mode
`docs/ARCH__<cid>.yaml` + `docs/TEST-STRATEGY__<cid>.yaml` present and
`metadata.status: complete`; the upstream validators pass. **Do not invent
additional gates.** Git working-tree cleanliness, an "uncommitted-modified file",
`metadata.changelog`-count reconciliation, commit-message archaeology, and the
like are NOT preconditions this skill defines — they must never be grounds for a
refusal. If you happen to observe one and think it worth mentioning, put it in a
clearly-separated, non-blocking **FYI** note *after* you have decided to proceed —
never as a reason not to run.

**Deterministic work_unit counting (container mode).** Any step that reasons
about whether components have `work_units` — a readiness check, a "this container
isn't drilled" note, or a refusal — MUST derive the counts from a real YAML
parse, never from `grep`/line-matching. A `work_units[]` item is legitimately
written block-style (`- name: x`) or flow-style (`- {name: x, ...}`); a grep for
`- name:` silently misses the flow-style ones and undercounts a fully-backfilled
document (the exact bug that once wrongly refused a 178-work_unit container —
grep found 37, missed 141). Run the bundled counter and read its output:

```bash
python "${CLAUDE_SKILL_DIR}/count_work_units.py" docs/ARCH__<cid>.yaml
```

It prints per-component counts and marks each zero-work_unit component as
plumbing (legitimately unit-free: `config_loader`/`serializer`/
`observability_bootstrap`/`error_handler`), waived (`work_units_waiver`), or a
**non-trivial gap** (exit 1) — the only kind that warrants "fix upstream in
`/sdlc:arch <cid>`". **Any readiness or refusal message that names zero-work_unit
components MUST quote this tool's output** and be grounded in its parsed counts,
not a grep. A backfilled container the parse shows as fully covered proceeds — do
not refuse it. (This does not change the atomic slicing: still one implementation
task per work_unit, `target_symbol` = the unit name.)

Optional enrichers (read only if present, slice large ones via `INDEX.yaml`):
`docs/DATA-MODEL.yaml` (entities → `migration`/repository tasks;
`touches_entities`), `docs/API.yaml` + `API__*` (operation_ids →
contract/endpoint tasks; `touches_operations`), `docs/UX.yaml` (surfaces →
frontend impl tasks; `implements_surfaces`; also the slug↔SCR map the
surface-coverage gate needs), and `docs/DESIGN.yaml` + `DESIGN__tokens`/`__assets`
(theme/token + asset realization → `design` tasks; `touches_assets`).

**Read `PRD.conventions` (if present).** Honour the binding `conventions` block
before writing anything — `conventions.artifact_ids` (consult before emitting
`TSK-NNN`/`WRN-NNN` or referencing `FR/NFR/TST`; never invent or renumber an
upstream id), and any bucket marked `binding: true`.

**Monorepo handling (v1.0):** if `PRD.metadata.monorepo: true` AND
`PRD.products` is non-empty, stop and warn that multi-product mode is deferred;
the user may proceed against one product at a time. See `references/edge-cases.md`.

**Upstream-change detection (re-runs).** If the active mode's output exists and
carries `metadata.upstream_provenance`, this is a re-run: compare each upstream's
recorded `sha256` to its current hash; for every changed upstream, classify the
delta (added / removed / modified ids) and run the **delta-review pass before the
theme interview** per `sdlc/skills/ux/references/upstream-reconciliation.md`
(CLAUDE.md §7). Fresh outputs skip this step.

For *what* to seed from which upstream field, see `references/task-discovery.md`.

### Phase 3 — Task seeding (mode-specific)

A task graph is fundamentally a coverage-and-ordering problem: enumerate every
unit of work implied upstream, then order it by dependency. Both modes start by
proposing a **draft task list** from upstream so the user corrects early rather
than inventing from a blank page. Load `references/task-discovery.md` and
`references/granularity-and-ordering.md` here.

**System mode — cross-container + repo-level work:**

1. **Repo/monorepo scaffold** — one `scaffold` task for the workspace, shared
   tooling, and root CI. Tag `⚠ inferred`.
2. **`ARCH.yaml` cross-container `calls`/`depends_on` edges** — each seeds one
   `integration` task (the consumer's client against the provider's contract).
   Tag `✓ found`.
3. **System `TEST-STRATEGY.yaml` tests (e2e/contract `TST-NNN`)** — each seeds
   one first-class `test` task. Tag `✓ found`.
4. **`build_order`** — seed from the specification order (providers first). Tag
   `⚠ inferred`.
5. **Deploy-prep handoff** — an optional `deploy-prep` task. Tag `⚠ inferred`.

**Container mode — implementation + test work:**

1. **`ARCH__<container>.components[].work_units[]`** — each component **work_unit**
   seeds one `implementation` task scoped `component_ref` + `target_symbol: <the
   work_unit name>` + a single `target_files` entry, with the unit's traces copied
   up (`touches_operations` ← `traces_api_operation`, `implements` ←
   `implements_requirements`, `touches_entities`) — plus the **embedded
   specifics** (schema v1.3): `interface_contract` (the unit's declared
   `inputs`/`output`/`raises`/`signature`, or the resolved API-operation shape
   when the unit defers), `unit_kind` (the unit's `kind`; omit for `callable`),
   and `unit_summary`. The codegen agent works from the task alone — see
   `references/task-discovery.md` → "Embed the per-task specifics". A component
   with no work_units seeds no implementation task (pure plumbing — there is no
   coarse whole-component fallback). Tag `✓ found`.
2. **`TEST-STRATEGY__<container>.tests[]`** — each `TST-NNN` seeds its own
   first-class `test` task (`implements_tests`) — **one per `TST-NNN`, never
   grouped** — with the TST's `tier`/`directives`/`acceptance`/`covers`
   embedded as `test_spec` (v1.3). Tag `✓ found`.
3. **`ARCH__<container>.internal_edges`** — `calls` edges between components seed
   `integration` tasks. Tag `✓ found`.
4. **Container `scaffold`** — one task for the package skeleton/manifest. Tag
   `⚠ inferred`.
5. **DATA entities the components persist** — a `repository` component's
   `traces_data_entities` seeds a `migration` task (schema/DDL — the entity
   realization unit) with `touches_entities`. Tag `⚠ inferred`.
6. **API operations of owned resources** — controllers seed operation-level work
   with `touches_operations` (operation_ids, not the resource_id). Tag `⚠ inferred`.
7. **UX surfaces (frontend containers)** — each `SCR` in `owns_ux_surfaces` (via a
   component's `traces_ux_surfaces`) seeds an `implementation` task with
   `implements_surfaces`. Tag `✓ found`.
8. **DESIGN (frontend containers)** — `token_based_ui` seeds a `design` task for
   the theme/token files; `asset_pipeline` seeds a `design` asset-scaffold task +
   one brief sidecar per `AST-NNN` (`touches_assets`). Tag `⚠ inferred`.

Seed each component-scoped task's `acceptance` from its component's
`acceptance_criteria` (don't re-invent the ARCH-declared done-conditions).

Present the draft. Each `⚠ inferred` candidate gets its own AskUserQuestion call.
Persist confirmations to `state.sessions[<key>].defined_tasks`. The task list is
a `critical synthesis: true` theme: **after the per-item loop closes in Phase 6,
run the scope-completeness sweep** (seed from ALL upstream ID families +
project-type heuristics), per `references/coverage-and-defer.md`.

### Phase 4 — Structural questions

Slicing is **always atomic** — one `implementation` task per component
`work_unit`, one `test` task per `TST-NNN`. There is no granularity knob and no
coarse whole-component fallback: this is the method-level breakdown the codegen
factory wants (a task pinned to one callable in one file). So this phase has no
"both modes" scalar.

**System mode:**

1. `build_order` — confirm the provider-before-consumer container ordering
   (pre-filled from the specification order). Present as `⚠ inferred`.

Persist all structural answers to state before proceeding.

### Phase 5 — Pre-fill confirmation

Present the pre-fill map **theme by theme**:

- `✓ found` items can be batch-accepted with `ok`.
- `⚠ inferred` items must be confirmed or corrected **one by one** in their own
  AskUserQuestion call. No batch-acceptance — this is the hallucination guard.

### Phase 6 — Theme interview

Walk the themes in `task-questions.yaml` order. Themes are tagged
`mode: system | container`; load only the active mode's themes.

#### System themes (when `/sdlc:task` was invoked)

1. `build_plan` — `high` (build_order + rationale).
2. `system_tasks` — `critical` per item, `synthesis: true`. For each task:
   `tsk_id`, `title`, `kind` (∈ scaffold / integration / test / config /
   migration / deploy-prep / docs / chore), `description`, `involves_containers`,
   `implements`, `implements_tests`, `depends_on`, `inputs`, `target_files`,
   `outputs`, `acceptance`, `priority`. After the per-item loop, run the
   scope-completeness sweep. Every system `TST-NNN` must be realized by a `test`
   task or deferred — Phase 7's system-test-coverage check enforces this.

#### Container themes (when `/sdlc:task <container>` was invoked)

Slicing is always atomic, so container mode has no build-plan theme — it goes
straight to the task graph.

1. `container_tasks` — `critical` per item, `synthesis: true`. For each task:
   `tsk_id`, `title`, `kind` (∈ scaffold / implementation / test / integration /
   migration / config / design / chore), `description`, `component_ref`,
   `target_symbol` (the ONE work_unit name this atomic impl task builds — must
   equal a `work_units[].name` on `component_ref`), `unit_kind` + `unit_summary`
   + `interface_contract` (embedded from the ARCH work_unit / resolved API
   operation — v1.3), `implements` (FR/NFR), `implements_tests` (TST) +
   `test_spec` (embedded from the TST entry — v1.3), `implements_surfaces` (SCR),
   `implements_workflows` (WKF), `touches_entities`, `touches_operations`,
   `touches_assets` (AST), `depends_on`, `inputs`, `target_files`, `outputs`,
   `acceptance`, `priority`.
   `target_files` (the codegen write targets) is drafted from the owning
   component's `code_location` in `ARCH__<container>.yaml` — an implementation task
   carries **exactly one** entry (the file housing `target_symbol`), which must sit
   within the component's `code_location` (validator warns otherwise); this is what
   stops codegen inventing paths. `outputs` stays the contract-level result.
   Run the scope-completeness sweep after the per-item loop. The coverage gates
   (Phase 7) require every component, **every component `work_unit` (named by
   exactly one task's `target_symbol`, no transitive credit)**, container
   `TST-NNN`, owned `SCR` surface, owned-resource operation, traced entity, and
   `implements_requirements` FR/NFR to be realized by a task (directly or — except
   work_units — transitively via a realized component) or deferred — plus a
   `design` task for a token_based_ui frontend.

#### Tier mechanics

Each question carries an `importance: med | high | critical` field. Tier flows
are identical to `sdlc:test` / `sdlc:arch` — see
`references/interview-mechanics.md` (which points at the canonical spec in
`sdlc/skills/prd/references/importance-flows.md`).

The two non-negotiable rules in this phase:

1. `⚠ inferred` candidates surface as the **position-1 recommended option** in
   their `AskUserQuestion` call. They cannot be silently accepted.
2. State is written after **every confirmed batch, mini-section, and per-item
   task completion** — not at theme boundaries.

### Phase 7 — Write & validate

Write or merge the active mode's output JSON:

- System mode → `docs/TASKS.json`. Per-container files are NOT created here.
- Container mode → `docs/TASKS__<container>.json`. On first completion of a
  container, register it under `TASKS.json.container_task_graphs[]`
  (`{container_id, file_path}`) and bump `TASKS.json.metadata.last_updated` — the
  only fields container mode mutates in the system file.

When writing, (re)write the active output's `metadata.upstream_provenance`: one
entry per upstream artifact consumed this run, each `{file, session_id,
last_updated, sha256}` (`sha256` from `docs/INDEX.yaml.generated_from`, else
`sha256(bytes)[:16]`). Replace-on-write. See CLAUDE.md §7.

Then run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/TASKS.json
```

The validator validates `docs/TASKS.json` plus every sibling `docs/TASKS__*.json`
and runs the cross-check suite (including the **union-graph acyclicity check**
across all files — the stitch). Coverage, scope, dependency, and ID-format
failures force `metadata.status: draft`; upstream-status issues emit warnings
only. The full check list (and the merge logic + recovery flow on `[FAIL]`) lives
in `references/merge-validate.md`; in summary:

**Coverage** (block complete — trace-or-defer, see `references/coverage-and-defer.md`).
An item is covered if a task names it OR a task realizes a component that traces it
(transitive credit); otherwise defer it with a `WRN-NNN`:

- **System test coverage** — every `TST-NNN` in `TEST-STRATEGY.yaml` is realized
  by some system `test` task OR deferred.
- **Container component coverage** — every `components[].component_id` in
  `ARCH__<cid>.yaml` is realized by ≥1 task (`component_ref`) OR deferred.
- **Container work-unit coverage** (the atomicity gate — **always blocking**)
  — every `work_units[].name` across the container's components is realized by
  **exactly one** task naming it in `target_symbol` OR deferred. No transitive
  credit from a bare `component_ref` (that is the point), and no two tasks may
  share a `target_symbol`. No-op only for a component that declares no work_units
  (pure plumbing — there is no coarse whole-component fallback).
- **Container test coverage** — every `TST-NNN` in `TEST-STRATEGY__<cid>.yaml` is
  realized by some task (`implements_tests`) OR deferred — one task per `TST-NNN`.
- **Surface coverage** — every `SCR` in the container's `owns_ux_surfaces`
  (ARCH.yaml, slug→SCR via `UX.yaml`) realized (`implements_surfaces` / a realized
  component's `traces_ux_surfaces`) OR deferred. Advisory when `UX.yaml` absent.
- **Operation coverage** — every `operation_id` of an owned API resource realized
  (`touches_operations` / a realized component) OR deferred. Advisory when no
  `API__*.yaml`.
- **Entity coverage** — every entity the components trace realized (a `migration`/
  repository task's `touches_entities` / a realized repository component) OR deferred.
- **Requirement coverage** — every `FR`/`NFR` in the container's + components'
  `implements_requirements` realized (`implements` / a realized component) OR deferred.
- **Design coverage** — a token_based_ui frontend that owns surfaces has a `design`
  task wiring the tokens OR a defer (per-asset AST tasks advisory).
- **Union FR coverage** — every PRD must-have `FR-NNN` realized somewhere or
  deferred; hard only once the whole graph is stitched (system complete + every
  container present), advisory before.

**The stitch** (block complete):

- Every `depends_on` resolves to a real task across the union of all task files
  (same-file `TSK-NNN`, cross-file `<cid>/TSK-NNN`, or `TASKS/TSK-NNN`).
- The union task graph is **acyclic** (a topological build order exists).

**ID-prefix formats + scope** (block complete):

- `TSK-NNN` on every `tsk_id` (unique per file); `WRN-NNN` on every warning.
- `implements` resolves to PRD FR/NFR (⊆ the container's/component's
  `implements_requirements`); `implements_tests` resolves to a `TST-NNN`.
- `touches_operations` ⊆ API `operation_id`s (a bare resource_id is rejected);
  `touches_entities` ⊆ DATA entity names; `implements_surfaces` ⊆ UX `SCR` ids;
  `implements_workflows` ⊆ PRD `WKF` ids; `touches_assets` ⊆ DESIGN `AST` ids.
  Each softens to format-only when its upstream is absent.
- Every `implementation` task is scoped to a component (`component_ref`) or a
  contract (`touches_operations`); every `component_ref` resolves. Every
  `implementation` task sets a `target_symbol` that resolves to one
  `work_units[].name` on its `component_ref`, plus **exactly one** `target_files`
  entry (the atomic-codegen pin).

**Advisory (warn only, never blocks complete):**

- `target_files` placement — a component-scoped task whose `target_files` entry
  falls outside the owning component's `code_location` (from `ARCH__<cid>.yaml`)
  emits a warning (placement drift). Directory-level; skipped when the component
  declares no `code_location`.

Set `metadata.status`:

- `"complete"` — only when all required fields are filled, the validator passes
  `[OK]`, AND every coverage / stitch / ID-format check passes.
- `"draft"` — on early EXIT, when any required field is null, or any check fails.

**The skill confirms tasks — never leave that to the user's editor.** Every task
the user accepted in the drill-down / sweep is written `status: "confirmed"` by
this skill at write time; `status: "draft"` marks only work still mid-interview.
The validator blocks `complete` while any task is a draft (check 19), so a
`complete` artifact always means "every task went through the confirmation
flow".

### Phase 8 — CLAUDE.md pointer & close

Call `set_claude_md_pointer.py` to inject or update this skill's bullet in the
shared `## SDLC Documents` section of the project-root `CLAUDE.md` (create the
section if missing). For bullet detection and append behaviour, see
`references/merge-validate.md`.

**Refresh the navigation index.** If `.claude/sdlc/docs_index.py` exists, run
`python .claude/sdlc/docs_index.py` after writing. Harmless no-op if not
installed.

After the CLAUDE.md write succeeds: set the active sub-session's
`status: complete` in the state file (keep the file as audit trail) and tell the
user where the artifacts live and what `--next` would do.

## Task kinds — the typed vocabulary

The `kind` is the most consequential field on a task: it tells the codegen agent
*what kind of work unit* this is and what to emit.

**Container kinds:**

| Kind            | Scope & codegen implication                                              |
|-----------------|--------------------------------------------------------------------------|
| `scaffold`      | Container skeleton: package layout, manifest, entrypoint.                |
| `implementation`| Implement one component's behaviour (the bulk). Scoped via `component_ref`.|
| `test`          | Author the test(s) realizing one or more `TST-NNN`. First-class.         |
| `integration`   | Wire two components / a within-container call.                           |
| `migration`     | Schema / DDL / persistence setup — the DATA **entity realization** unit.  |
| `config`        | Env / settings wiring (`config_loader`); deploy owns secrets backends.   |
| `design`        | Realize DESIGN for this frontend: theme/token files (token_based_ui) or asset-folder scaffold + per-`AST` brief sidecars (asset_pipeline). |
| `chore`         | Tooling, lint config, local CI, misc plumbing.                          |

**System kinds:** `scaffold` (repo/monorepo skeleton) · `integration`
(cross-container wiring) · `test` (system e2e/contract) · `config` · `migration`
(shared/bootstrap) · `design` (shared design-token package for ≥2 frontends) ·
`deploy-prep` (handoff to `/sdlc:deploy`) · `docs` (repo-level) · `chore`.

`references/task-discovery.md` maps each upstream signal to the kind it seeds.

## Session state file

Path: `.claude/skills-state/sdlc-task.state.yaml`

Like `arch`/`test`, `task` keeps **per-mode sub-sessions** in one file:

```yaml
# changelog:
#   1.2 (2026-07-07): Schema v1.3 — embed per-task specifics at seeding/write
#     time (interface_contract from the ARCH work_unit or resolved API operation;
#     test_spec from the TST entry; unit_kind/unit_summary), draft target_files
#     for every file-producing kind, and write status: confirmed on every
#     user-accepted task (validator checks 18-21).
#   1.1 (2026-07-03): Phase 2 preflight hardened — work_unit presence/counts must
#     come from a real YAML parse (new count_work_units.py helper, quoted in any
#     readiness/refusal), never a line-grep that misses flow-style entries; the
#     preflight gate set is explicitly closed (no invented git/changelog gates).
#   1.0: initial two-mode (system/container) task graph + --next resolver.
session_file_version: "1"
skill_version: "1.2"
last_updated: <iso8601>
spec_order: []                  # container_ids in --next / build_order sequence (providers first)

sessions:
  system:                       # /sdlc:task
    session_id: <uuid4>
    started_at: <iso8601>
    last_updated: <iso8601>
    status: in_progress         # in_progress | complete | aborted
    mode: system
    pre_fill_confirmed: false
    last_ids: {}                # writer-managed counters, e.g. {TSK: 12, WRN: 2}.
    completed_themes: []
    skipped_themes: []
    todo_themes: []
    pending_themes: []
    current_theme: null
    current_task: null          # during the system_tasks drill-down
    defined_tasks: []           # [{tsk_id, kind, status: draft|confirmed, source}]
    partial_answers: {}         # mirrors docs/TASKS.json structure

  "container|backend-api":      # /sdlc:task backend-api
    session_id: <uuid4>
    started_at: <iso8601>
    last_updated: <iso8601>
    status: in_progress
    mode: container
    container_id: backend-api
    pre_fill_confirmed: false
    last_ids: {}                # this container file's TSK + WRN spaces
    completed_themes: []
    skipped_themes: []
    todo_themes: []
    pending_themes: []
    current_theme: null
    current_task: null
    defined_tasks: []
    partial_answers: {}         # mirrors docs/TASKS__backend-api.json
```

Rules:

- Generate `session_id` (UUID4) on first creation of each sub-session.
- Update top-level + sub-session `last_updated` on every write.
- Write the file **after every confirmed batch, mini-section, and per-item step**,
  including pre-fill confirmations and Phase 3 draft confirmation.
- On `EXIT`: set the *active* sub-session `status: aborted`, write
  `partial_answers`, confirm, stop. Other sub-sessions untouched.
- On Phase 8 completion: set the active sub-session `status: complete`; keep file.
- **`TSK-NNN` and `WRN-NNN` counters** are writer-managed in the active
  sub-session's `last_ids`. Each artifact (system file and each container file)
  owns an **independent** `TSK` space. There is no interview question for
  warnings; append them at write time and bump the counter. **Reconcile on
  resume:** if an on-disk file has a higher `TSK-NNN`/`WRN-NNN` than `last_ids`,
  sync the counter to `max(on_disk, state)` before appending.
- **`metadata.changelog`** is append-only, most-recent first; one line per write.
  The validator only type-checks it.
- The validator ignores this file — it validates only the output JSON.

**Source of truth on resume:** the on-disk JSON is authoritative for *answers*
(it may have been hand-edited); the state file is authoritative for *interview
progress*. On resume, load the on-disk JSON first as baseline, then layer the
sub-session's `partial_answers` on top. If they conflict on the same key, ask the
user — never silently overwrite.

## Edge cases

For unusual situations (a required upstream missing or in draft; a buildable
container whose `ARCH__<cid>.yaml` or `TEST-STRATEGY__<cid>.yaml` doesn't exist
yet; a container with no components; a component that genuinely warrants no task;
a dependency cycle the user wants; cross-file deps to a not-yet-built container;
system mode before any container exists; ARCH/TEST edited between sessions;
monorepo mode; write-permission errors) → `references/edge-cases.md`.

## Style of conversation

The task interview can be long. Keep it humane:

- Lead with the draft task list — the user edits a list, they don't invent one.
- Keep `AskUserQuestion` batches to 2–4 questions; never more than 4.
- Acknowledge progress at each theme and task boundary ("That's the `backend-api`
  subgraph — 1 scaffold, 10 implementation (one per work_unit), 8 test, 2
  integration. Work-unit coverage: green. Test coverage: green. Next:
  `web-frontend`.").
- Always call out that candidate tasks were synthesized from ARCH + TEST +
  DATA + API + UX + DESIGN — don't pretend they came from nowhere.
- For each test task, name the `TST-NNN` it realizes so the user sees the
  test→task link; for each integration task, name the edge it wires.
- After all themes, congratulate briefly and move to write & validate.

## Quick reference: commands the user can type

| User input | Effect |
|---|---|
| `EXIT` | Abort: type into the free-text field of any AskUserQuestion call. |
| `confirm` | Accept a single inferred pre-fill (Phase 5). |
| `ok` | Batch-accept all `✓ found` pre-fills in the current theme, OR accept the Phase 3 draft list as-is. |
| `now` | Run the proposed optional theme (gate question). |
| `skip` | Skip the proposed optional theme (gate question). |
| `todo` | Defer the proposed optional theme; logs a `WRN-NNN` to `task_warnings`. |
| `defer <id>` | Mark an upstream id (component_id / work_unit name / TST-NNN) intentionally not-realized; logs the WRN-NNN deferral that satisfies the coverage gate. |

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A repo containing a collection of skills bundled as a Claude Code plugin (`sdlc`).
The skillset is an **SDLC factory**: each skill produces a machine-readable spec
that the next skill consumes, so downstream AI agents can scaffold a software
project from a structured chain of artifacts. Skills are invoked as
`/sdlc:<skill>` and run in order:

| Skill        | Folder              | Inputs                                                                                       | Output(s)                                            |
|--------------|---------------------|----------------------------------------------------------------------------------------------|------------------------------------------------------|
| `setup`      | `sdlc/skills/setup` | run ONCE before `prd`; current project root                                                  | `.claude/sdlc/docs_index.py`, docs PostToolUse hook in `.claude/settings.json` (canonical `docs/*.yaml` **and** `docs/TASKS*.json`), `.claude/rules/sdlc-docs-access.md`, `docs/INDEX.yaml`, `## SDLC Documents` pointer block in `CLAUDE.md` |
| `prd`        | `sdlc/skills/prd`   | repo scan + ideation + interview                                                             | `docs/PRD.yaml`                                      |
| `ux`         | `sdlc/skills/ux`    | `docs/PRD.yaml` + interview                                                                  | `docs/UX.yaml`, `docs/UX__<surface>.yaml`            |
| `design`     | `sdlc/skills/design`| `docs/PRD.yaml` + `docs/UX.yaml` (+ `UX__*`) + interview                                     | `docs/DESIGN.yaml`, `docs/DESIGN__tokens.yaml` (token UIs), `docs/DESIGN__assets.yaml` (asset pipelines) |
| `data`       | `sdlc/skills/data`  | `docs/PRD.yaml` (+ `docs/UX.yaml` (+ `UX__*`) — strongly recommended) + interview            | `docs/DATA-MODEL.yaml`                               |
| `api`        | `sdlc/skills/api`   | `docs/PRD.yaml` + `docs/UX.yaml` + `docs/DATA-MODEL.yaml` + interview                        | `docs/API.yaml`, `docs/API__<resource>.yaml`         |
| `arch`       | `sdlc/skills/arch`  | `docs/PRD.yaml` + `docs/UX.yaml` (+ `UX__*`) + `docs/DATA-MODEL.yaml` (+ `docs/API.yaml` (+ `API__*`)) + interview                              | `docs/ARCH.yaml`, `docs/ARCH__<container>.yaml`      |
| `test`       | `sdlc/skills/test`  | `docs/PRD.yaml` + `docs/DATA-MODEL.yaml` + `docs/ARCH.yaml` (+ `docs/ARCH__<container>.yaml` in container mode) (+ `docs/API.yaml`) (+ `docs/UX.yaml`) + interview | `docs/TEST-STRATEGY.yaml` (system mode), `docs/TEST-STRATEGY__<container>.yaml` (container mode) |
| `task`       | `sdlc/skills/task`  | **system:** `docs/ARCH.yaml` + `docs/TEST-STRATEGY.yaml` + interview; **container:** `docs/ARCH__<container>.yaml` + `docs/TEST-STRATEGY__<container>.yaml` (+ `docs/DATA-MODEL.yaml`) (+ `docs/API.yaml`) (+ `docs/UX.yaml`) (+ `docs/DESIGN.yaml` (+ `DESIGN__*`)) + interview; both read `docs/PRD.yaml` for FR/NFR id resolution. UX/API/DATA/DESIGN drive the surface/operation/entity/design coverage gates | `docs/TASKS.json` (system mode), `docs/TASKS__<container>.json` (container mode) |
| `code`       | `sdlc/skills/code`  | `docs/TASKS.json` + `docs/TASKS__<container>.json` (must be `complete` + task-validator-green; v1.4 tasks are self-contained) + `docs/ARCH__<container>.yaml` (tech-stack slice; full contract fallback for pre-1.4 artifacts) (+ `docs/TEST-STRATEGY__<container>.yaml` pre-1.3) (+ `docs/DATA-MODEL.yaml` entity slices pre-1.4) — **no interview** | generated source files at each task's `target_files`, `docs/CODE-MANIFEST.json`, execution ledger in `.claude/skills-state/sdlc-code.state.yaml` |
| `deploy`     | `sdlc/skills/deploy` *(planned — not yet implemented)* | `docs/ARCH.yaml` + interview                                                | `docs/DEPLOY.yaml`                                   |

**Downstream consumers of every output are AI agents, not humans.** Optimize artifacts for unambiguous machine consumption (typed enums, no prose blobs, explicit `null` for unanswered fields).
Inputs in round brackets `()` are optional to each skill and taken if present.

`code` is an **execution skill**, not an interview skill — the Stage-14 half of
the factory. It consumes the task graph and *writes the actual source files*
each task's provenance pins (`target_files` / `target_symbol`). The session
acts as a **manager** that dispatches waves of up to 3 parallel, non-interactive
worker subagents; each worker executes one work unit (implementation task + its
test task, test-first) with a test-and-heal loop (≤3 attempts; attempt 3
escalates to a manager-dispatched fresh opus subagent). Waves only contain
tasks with pairwise-disjoint `target_files`; the manager is the sole ledger
writer, and integration/container/system test rings run serialized between
waves. Tasks are **self-contained** as of task-artifact v1.4: implementation
tasks embed their `interface_contract` (and `unit_kind` / `unit_summary`), test
tasks their `test_spec`, and integration/migration/design/config tasks their
`operation_contract` / `entity_slice` / `design_spec` / `config_keys` slices,
so codegen needs no per-task ARCH/TEST-STRATEGY/API/DATA/DESIGN lookups — only
the container's tech stack stays upstream. Three forms: `/sdlc:code`
(container-by-container through `build_order`, pausing at each container
boundary with a continue/stop gate), `/sdlc:code <container>` (one subgraph,
then stop), `/sdlc:code --next` (next incomplete unit in `build_order`). Its
per-task execution ledger (`.claude/skills-state/sdlc-code.state.yaml`) makes
every invocation resumable and idempotent; generated symbols carry greppable
`sdlc-code: <cid>/TSK-NNN` markers; `docs/CODE-MANIFEST.json` is the
machine-readable ledger (with per-file `verified` level) downstream
verify/deploy stages consume. Like `setup`, it is exempt from the interview
contract below (no themes, no questions file) — HITL is a plan-approval gate,
container-boundary gates, conflict/failure gates, and a close report. It
honours the downstream-rejection rule (refuses draft/invalid task graphs) and
never edits `docs/*.yaml` or the TASKS files.

`setup` is infrastructure, not an artifact producer. It runs once before `prd`
and wires a **generated `docs/INDEX.yaml`** — a pure line-range location map over
the large specs (`PRD.yaml`, `DATA-MODEL.yaml`, `TASKS*.json`, …) plus a `shards:`
inventory of every `docs/*__*` sub-artifact — plus a `Write|Edit` PostToolUse
hook that refreshes it on every canonical `docs/*.yaml` / `docs/TASKS*.json`
edit, and the `.claude/rules/sdlc-docs-access.md` slice-don't-slurp protocol.
Each artifact skill reads large upstream docs **by slice** via the index
(Phase 2) and refreshes it after writing (Phase 8). The generator
(`docs_index.py`) is stdlib-only and copied into the consumer project at
`.claude/sdlc/docs_index.py`; re-running `/sdlc:setup` upgrades an installed copy.


## Canonical naming

Use these forms consistently across all skills:

| Concept                                          | Form                                          | Example                                  |
|--------------------------------------------------|-----------------------------------------------|------------------------------------------|
| Skill folder + frontmatter `name`                | kebab-case (lowercase, hyphens, ≤64 chars)    | `prd`, `ux`, `arch`                      |
| Plugin invocation                                | `/<plugin>:<skill>`                           | `/sdlc:prd`, `/sdlc:ux`                  |
| State file path                                  | `.claude/skills-state/sdlc-<skill>.state.yaml`| `.claude/skills-state/sdlc-prd.state.yaml`|
| `generated_by` tag in output                     | `sdlc-<skill>`                                | `sdlc-prd`                               |
| Question inventory file (in skill folder)        | `<skill>-questions.yaml`                      | `prd-questions.yaml`, `ux-questions.yaml`|
| Output spec file (in `docs/`)                    | UPPERCASE (with `-` for compounds)            | `PRD.yaml`, `DATA-MODEL.yaml`            |
| Output sub-artifact (per surface/container/...)  | `<NAME>__<slug>.yaml`, slug in kebab-case     | `UX__login-flow.yaml`, `ARCH__backend-api.yaml` |
| Schema reference file (in skill folder)          | `<UPPERCASE-OUTPUT-NAME>.schema.yaml`         | `PRD.schema.yaml`, `UX.schema.yaml`      |
| Bundled Python helpers                           | snake_case `.py`                              | `validate_schema.py`, `set_claude_md_pointer.py` |

Slugs inside `__<slug>` segments are always kebab-case.

## Designing a new skill

When asked to design a new SDLC skill, read **only the upstream skills it
depends on** (per the table above) plus their assets (`references/`,
`<skill>-questions.yaml`, `<NAME>.schema.yaml`). Do not read other unrelated
skills.

Every SDLC skill follows the same architecture: read inputs → resume-aware
interview → write & validate output → inject CLAUDE.md pointer → mark state
complete. The sections below define the contract.

### Frontmatter (required fields)

```yaml
---
name: <skill>                    # kebab-case
description: >
  One-line explicit-invocation summary. Trigger only on /sdlc:<skill> or a
  direct natural-language request. Do not auto-trigger from generic chat.
user-invocable: true
disable-model-invocation: true   # always — these skills are deliberate, not ambient
model: opus                      # opus | sonnet | opusplan ; sonnet only when the
                                 # logic is genuinely simple and shallow-reasoning
effort: xhigh                    # xhigh is the default for every interview/artifact
                                 # skill. Sanctioned exceptions (do not "fix" them):
                                 # setup = sonnet/medium (deterministic installer),
                                 # code = sonnet/high (100+-task codegen runs; heal
                                 # attempt 3 already escalates to an opus subagent)
allowed-tools: Read Write(CLAUDE.md) Write(docs/<OUTPUT>.yaml) Write(.claude/skills-state/sdlc-<skill>.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---
```

`allowed-tools` is **space-separated** (per Anthropic skill docs) or a YAML
list. Never comma-separated.

### Skill directory layout

```
sdlc/skills/<skill>/
├── SKILL.md                     # required — workflow + phase outlines
├── <skill>-questions.yaml       # interview inventory (themes + questions)
├── <UPPERCASE-OUTPUT>.schema.yaml  # human-readable canonical schema
├── validate_schema.py           # Pydantic v2 validator
├── set_claude_md_pointer.py     # CLAUDE.md pointer injector
└── references/                  # on-demand reference material
    ├── interview-mechanics.md
    ├── merge-validate.md
    ├── edge-cases.md
    └── …
```

**`references/` folder** is mandatory for non-trivial skills. SKILL.md stays
under ~500 lines and points into `references/<topic>.md` for detailed rules.
Reference files are loaded only when the phase that needs them is entered.
This keeps the entry-point lean and the loaded context proportional to the
work in progress.

### Interview contract

A skill that has `interview` in its inputs runs an interactive interview via
`AskUserQuestion` driven by `<skill>-questions.yaml`.

`<skill>-questions.yaml` has **two top-level keys**:

```yaml
themes:
  - id: <theme_id>                # snake_case, matches a key in the output schema
    title: <Human Title>          # for messages to user
    required: true|false          # if false, the agent asks a now/skip/todo gate
    description: <one-liner>      # what this theme is about

questions:
  - theme: <theme_id>
    id: <question-id>             # kebab-case, unique
    schema_path: <dotted.path>    # where the answer is written in the output yaml
    question: <prompt shown to user>
    hint: <short note for the agent — why this matters downstream>
    suggested_answers: [<≤4 plausible options>]
    free_text_allowed: true|false # false ⇒ only one of suggested_answers is valid
    required: true|false          # inherited from themes[].required by default
    importance: med|high|critical # see "Importance tiers" below (default: med)
```

Interview style:

- Batch 2–4 questions per `AskUserQuestion` call (the tool's hard limit is 4).
- Recommended answer first; auto-added "Other" lets the user type free text.
- Show a completeness summary at every theme boundary; advance only after
  user confirms.
- Challenge vague answers ("clean and simple") for concrete examples or
  references — but always make sensible proposals.

#### Reserved EXIT command (mandatory)

In any `AskUserQuestion` "Other" free-text field the user may type `EXIT`
(case-insensitive). On detection: persist current state with
`status: aborted`, confirm save to the user, stop.

There is no SAVE command — saving is implicit after every confirmed batch.

#### Importance tiers (recommended)

Question entries may set `importance: med | high | critical | nested_freeform`
to control how they are run:

- **`med`** (default) — batched 2–4 per `AskUserQuestion` call.
- **`high`** — own mini-section. Agent drafts an answer, user approves
  or iterates (cap iterations, e.g. 3).
- **`critical`** — full per-item drill-down (propose → challenge →
  detail → final approval → next item). When the theme is also marked
  `synthesis: true`, a **scope-completeness sweep** runs before the
  list closes (see "Scope-completeness sweep" below).
- **`nested_freeform`** — for a `Dict[str, Any]` field whose shape is
  project-defined (e.g. `prd`'s `conventions` block). Per-bucket draft-
  approve loop, validator only type-checks the top-level mapping.

Reserve `critical` for scope-defining fields (e.g. MVP features in
`prd`; surface inventory in `ux`).

The canonical specification of all four tiers — including the sweep,
the per-item state machine, the structured detail slots, iteration
caps, and EXIT-mid-flow rules — lives in
`sdlc/skills/prd/references/importance-flows.md`. Downstream skills
should point at that file rather than re-document the tiers from
scratch.

#### Confidence / rationale sibling fields (recommended)

For fields where downstream agents benefit from knowing certainty or the
"why" behind a choice, write sibling fields in the output:

- `<field>_confidence`: `confirmed | inferred | assumption`
- `<field>_rationale`: short string explaining the trade-off

The schema file documents which sibling pairs exist.

### Cross-skill conventions (apply to every SDLC skill)

These conventions surfaced first in `prd` and `ux`, then proved generic
enough that they belong here. Every new skill should adopt them unless
there's a concrete reason not to. Downstream skills (`data`, `api`,
`arch`, `test`, `task`, `deploy`) MUST adopt them.

#### 1. `metadata.changelog: Optional[List[str]]` on every artifact

Every output artifact carries an optional, append-only changelog inside
`metadata`. Each entry is a single line:

```yaml
metadata:
  changelog:
    - "1.1 (2026-05-21): Manual review pass. <one-line summary>."
    - "1.0 (2026-05-21): Initial spec produced by sdlc-<skill>."
```

Format: `"<artifact_version> (<YYYY-MM-DD>): <one-line summary>"`.
Most-recent entry first. Append-only — never rewrite or reorder. On a
brand-new write the changelog may be omitted or initialized with a
single `"initial."` entry; both are valid.

The validator type-checks `Optional[List[str]]` only; it does NOT
enforce format on individual entries (over-validation here would
discourage manual edits, which are explicitly allowed and the
common case for the field).

#### 2. `WRN-NNN` is the universal warnings family

Every artifact's `*_warnings` list (`prd_warnings`, `ux_warnings`,
`data_warnings`, etc.) uses the `WRN-NNN` family. Items are formatted
as `"WRN-NNN: <message>"`. The counter is **writer-managed** — there
is no interview question for warnings; the agent appends them at write
time and persists `state.last_ids.WRN` (or
`state.last_ids_by_product[<slug>].WRN` in monorepo mode).

The validator enforces format `^WRN-\d{3,}:\s+.+` on every entry.
Counter reconciliation on resume: if the on-disk file has a higher
WRN-NNN than `state.last_ids.WRN`, sync the state counter to
`max(on_disk, state)` before appending the next warning.

#### 3. Scope-completeness sweep for `critical synthesis: true` themes

A theme marked both `importance: critical` per question AND
`synthesis: true` per theme produces a scope-defining list whose
contents are inferred from upstream artifacts (PRD features synthesized
from problem/users/use-cases; UX surfaces synthesized from PRD WKF/FR/
ENT/JTB ids). For every such theme, **after the per-item loop closes,
run a dynamic scope-completeness sweep** that:

- reflects on the draft list itself,
- reflects on **every upstream artifact's ID families** (not just the
  most direct one), and
- reflects on project-type heuristics (CLI tool, SaaS app, library,
  pipeline, etc.).

The sweep surfaces concrete candidate items — *not* category labels —
via one multi-select `AskUserQuestion`. Caps: at most 2 sweep passes
per list; defer remaining candidates to a `WRN-NNN` warning; honour
the anti-padding rule (surface 0 candidates rather than manufacture).

Canonical specification: PRD's `importance-flows.md`, section
"The `critical` flow → Step e — dynamic scope-completeness sweep".
Reference it instead of duplicating.

The sweep is the single most important defence against synthesis-stage
gaps — the kind where an item implied by an upstream ID family (e.g.
an entity whose description literally names a CLI verb) didn't make it
into the draft list because the agent only seeded from the most-direct
upstream signal. **Skip the sweep at your peril.**

#### 4. Upstream-ID consumption rule

When a skill consumes IDs from an upstream artifact:

- **Read the upstream's `conventions.artifact_ids` block** (if present)
  to know which families exist and what they mean.
- **Reference upstream IDs by their stable prefix** (`"FR-001"`,
  `"WKF-003"`), never by verbatim description text. The PRD's IDs are
  the stable contract; the description text is editable.
- **Never invent IDs in an upstream family.** Don't write `"FR-099"`
  in a UX or DATA-MODEL artifact unless it already exists in PRD.
- **Never renumber upstream IDs.** Promoting an item between sibling
  lists (e.g. PRD nice-to-have → must-have) preserves the ID.
- **Surface stale refs explicitly.** When PRD is edited between
  sessions and a downstream artifact references an id that no longer
  exists, ask the user per stale ref — do NOT silently delete.
- **Categorize refs by semantic role** (recommended). Rather than one
  flat `prd_refs: list[id]`, prefer multiple fields that capture *what
  this surface/operation/component does with* the upstream id (e.g.
  `traces_workflows`, `implements_requirements`, `references_entities`
  in UX; analogous fields downstream). Validator enforces per-field
  family prefix (WKF/FR/ENT/...).
- **Requirement-trace fields accept FR *and* NFR.** A field that traces
  to PRD *requirements* (e.g. `implements_requirements`) admits both
  `FR-NNN` (functional, from `functional_requirements`) and `NFR-NNN`
  (non-functional, from PRD `performance_targets` + `other`). Do not
  build a validator that only admits `FR-`: UX and ARCH both legitimately
  trace surfaces/containers to non-functional requirements, and
  `test`/`deploy` will lean on NFRs heavily (latency budgets, availability
  targets). Resolve such refs against the union of the PRD FR and NFR id
  sets. (Surfaced this session — the gold UX/ARCH docs referenced
  `NFR-010/011` and the FR-only validators wrongly rejected them.)

#### 5. ID families a skill emits get `state.last_ids.<PREFIX>` counters

A skill that emits ID-prefixed list items declares each family in the
top of its output schema yaml, runs a writer-managed counter in
`state.last_ids.<PREFIX>`, and enforces the format `<PREFIX>-{:03d}`
in its validator. Items in those families are stable across the
artifact's lifetime — once written, the id never changes. Renaming a
slug or human label does not change the id.

In monorepo mode, every emitted family has its counter under
`state.last_ids_by_product[<slug>].<PREFIX>` instead — each product
carries an independent id space per family.

Counters persist after every accepted item (including sweep
acceptances). EXIT/resume must not produce gaps or duplicates.

#### 6. Coverage contract: trace every upstream item OR defer it

When a skill's validator enforces that its artifact *covers* an upstream
family — `data` must account for every PRD `FR-NNN`; `test` must cover
every requirement/risk; `task` must realize every container's
responsibilities — the contract is **trace OR defer**, never silent
omission:

- **Trace** — the item is referenced by at least one output element
  (an entity's `traces_prd_features`, a test case's `covers`, a task's
  `implements`, …).
- **Defer** — the item is intentionally out of scope for *this*
  artifact (e.g. a process-only FR with no persisted state belongs in
  ARCH/TASK, not DATA-MODEL). Record it in the artifact's `*_warnings`
  as a `WRN-NNN` deferral that names the id range and the reason:
  `"WRN-007: FR-031..FR-042 are orchestration requirements with no
  persisted entity; deferred to ARCH/TASK."`

The coverage check counts a deferred id as covered. This keeps coverage
honest at 100%: every upstream item is either traced or explicitly,
reviewably waived — none silently dropped. Implement the deferral path
in the validator (don't just document it): a skill whose header promises
"trace-or-defer" but whose validator only counts traces will reject
legitimate artifacts. (Surfaced this session — the gold DATA-MODEL left
12 PRD process-FRs with neither an entity nor a deferral, and the
validator had never implemented the defer half of its own contract.)

#### 6a. Paired deferral: impl and test deferral sets stay symmetric

§6 makes deferral honest *within* one artifact against *one* upstream
family. It says nothing about consistency *between* two downstream
artifacts that describe the same behaviour — and a behaviour has two:
its **test** (`test` → a `TST-NNN`) and its **impl task** (`task` → one
task per work_unit). Deferring one while keeping the other ships a lie:
an untested branch under a "full coverage" claim, or a tested branch
nobody builds. So the two deferral sets must be **symmetric**:

- If `test` **defers the test** for a behaviour (its work_unit / FR /
  component named in `TEST-STRATEGY*.test_strategy_warnings`, so no
  `TST-NNN` exists) and `task` still emits the impl task, that impl task
  MUST be **post-MVP** (`priority: could`) or itself **deferred** in
  `task_warnings`. Otherwise the branch is built with no test.
- The two honest resolutions are **defer both** or **claim partial
  coverage** (restore the test). Never silently keep the impl.

Because a test deferred in the `test` stage leaves **no `TST-NNN`** to
key on, the reconciliation runs off the *test's deferral warnings*, not
its test ids: `task`'s validator reads `test_strategy_warnings` for the
behaviour token (work_unit name / FR / component) and **warns** on an
asymmetric pair (its cross-check #23). It WARNS rather than blocks — the
check spans two artifacts and two id-namespaces, so a hard block would be
brittle — but the warning is the signal to make the deferral honest.
When you defer a test that has real code, **name the behaviour** (the
work_unit and/or FR), not just a `TST-NNN`, so the downstream check can
see it. (Surfaced dogfooding the build-sandbox container: impl tasks were
emitted for branches whose tests were deferred, then "full coverage" was
claimed — nothing reconciled the two sets.)

#### 7. Upstream-change re-invocation contract

Re-invoking a skill whose output already exists means one of three
things, handled by three different mechanisms:

- **Resume** an interrupted session (`status: in_progress`) → the
  state-file resume prompt (Phase 1).
- **Refine/extend** deliberately, upstream *unchanged* → the merge/update
  flow (`references/merge-validate.md`).
- **Reconcile** because an upstream artifact changed → the contract below.

The first two are already uniform across skills. The third — the case
users most often re-invoke for ("the PRD/UX/DATA/API moved under me") —
must be uniform too. Every skill *after* `prd` (every artifact skill that
consumes an upstream artifact) MUST:

1. **Record provenance at write time.** Carry
   `metadata.upstream_provenance`: a replace-on-write snapshot, one entry
   per upstream artifact consumed, each a mapping
   `{file, session_id, last_updated, sha256}`. The `sha256` is the 16-hex
   content-hash prefix `setup`'s `docs_index.py` already computes — read it
   from `docs/INDEX.yaml.generated_from[<file>].sha256`, or compute
   `sha256(bytes)[:16]` when `INDEX.yaml` is absent. A content hash (not
   just `session_id`) is required because it catches **hand-edits** to an
   upstream yaml, which `session_id` does not. The validator type-checks
   `Optional[List[<mapping>]]` only — like `changelog`, manual edits are
   expected, so do not over-validate field shape.

2. **Detect & classify on re-run (Phase 2).** When the output exists and
   carries provenance, compare each upstream's current hash to the
   recorded one. For each *changed* upstream, diff its ID families against
   what the output references → **added** (new upstream ids; already caught
   by coverage but named up front), **removed** (stale-ref, §4), and
   **modified** (id stable, body changed — the case nothing caught before).

3. **Reconcile via one delta-review pass** *before* the theme interview:
   one consolidated `AskUserQuestion` sweep across all changed upstreams;
   per item the user picks incorporate / ignore+`WRN` / defer. This
   unifies the previously-scattered signals (coverage = adds, stale-ref =
   removes, + new modified-body detection) into a single reviewable step,
   then falls through to the normal merge.

If every upstream is unchanged, skip the delta-review — it's a refine, not
a reconcile.

Canonical mechanics (provenance shape, hash sourcing, the delta
classification, the delta-review state machine, edge cases):
`sdlc/skills/ux/references/upstream-reconciliation.md`. Reference it
instead of duplicating. `prd` is exempt — it consumes no upstream
artifact.

Before this convention, only `data` tracked anything (a shallow
`session_id` match that missed hand-edits and never surfaced modified
bodies); `arch` had no upstream-change handling at all. §7 generalizes and
hardens what `data` started.

#### 8. Derived counts don't live in prose

Structured data is the source of truth; prose that *restates* it goes
stale silently. An adversarial review of a skill-authored corpus found
header/footer comments and `overview`/`notes` sentences still claiming
"15 commands", "43 edges", "181 tests" several version bumps after the
structured collections had moved — because propagation passes update
structured fields, not the sentences describing them.

Two rules, every artifact skill, every write:

- **Don't emit derived counts into prose.** New prose fields
  (`overview`, `purpose`, `notes`, rationale strings) and YAML comment
  headers must not restate counts of structured collections. Say *what*,
  not *how many* — downstream agents count the collection; the
  validator's summary line reports totals.
- **Refresh what you touch.** Any pass that updates a file which already
  carries such counts (merge, backfill, propagation, edge-only `-d`
  writes) re-derives each count it invalidated from the structured data
  in the same write — or deletes the sentence. A propagation pass that
  changes a collection but not the prose describing it is an incomplete
  pass.

#### Implications for downstream skills

Any new skill that consumes the PRD (directly or indirectly via UX,
DATA-MODEL, API, etc.) should:

- Read every relevant upstream artifact's IDs during Phase 2.
- Seed `critical synthesis: true` lists from **all** upstream families
  it can plausibly draw on.
- Run the scope-completeness sweep before closing every synthesis list.
- Emit its own `<PREFIX>-NNN` family if it produces a new artifact
  type downstream agents will reference (declare it in the schema's
  header).
- Carry `metadata.changelog` and `<artifact>_warnings` with the WRN
  family.
- Inherit the upstream's `conventions.artifact_ids` block verbatim
  where applicable; consult it before writing IDs.
- **Read large upstream docs by slice via `docs/INDEX.yaml`** (Phase 2)
  and **refresh `INDEX.yaml` after writing** (Phase 8) — both are now
  part of the canonical 8-phase flow.
- **Accept `FR-NNN` and `NFR-NNN` in any requirement-trace field** and
  resolve against the union of the PRD FR + NFR id sets (§4).
- **Enforce coverage as trace-or-defer, not trace-only** — implement
  the `WRN-NNN` deferral path in the validator wherever the artifact
  claims to cover an upstream family (§6).
- **Record `metadata.upstream_provenance` and run the delta-review on
  re-invocation** — snapshot every upstream's content hash at write time,
  and on re-run detect/classify/reconcile upstream drift before the
  interview (§7; mechanics in
  `sdlc/skills/ux/references/upstream-reconciliation.md`).
- **Decompose, don't skim.** Where a skill emits structured models or
  nested items (entities/sub-models in `data`, test cases in `test`,
  task graphs in `task`), recurse to first-class definitions rather
  than leaving shallow stubs — and run a reconciliation/completeness
  sweep before declaring `complete`. (Surfaced this session: the gold
  DATA-MODEL had 33 inlined sub-models and 38 entities unassigned to a
  bounded context; `data` now ships `references/submodel-and-context-sweep.md`
  for exactly this.)

### Schema validation contract

Each skill defines its output schema **twice**, kept in lockstep:

1. `<UPPERCASE-OUTPUT>.schema.yaml` — human/agent-readable, with inline comments.
2. `validate_schema.py` — Pydantic v2 model that enforces it.

`validate_schema.py` requirements:

- Required fields are non-optional; optional fields use `Optional[...]`.
- Fixed-value fields use `Enum` classes.
- Loads the skill's output YAML (default path is its canonical location;
  CLI flag `--path` overrides), parses, validates.
- Prints a clear **pass/fail summary** with field-level error messages.
- The skill **must** call this script after every write and surface errors
  before declaring the workflow complete.
- On validation failure: show field-level errors, offer interactive
  re-entry via `AskUserQuestion`, re-run validation.

**Exit codes** (include verbatim in module docstring):

```
0 — schema valid; either status='complete' with all required fields filled,
    or status='draft' (with or without missing required fields).
1 — schema invalid (pydantic error), OR status='complete' but required
    fields are missing.
2 — could not read or parse the file (missing, bad YAML, etc.)
3 — required dependency missing (pydantic v2 or pyyaml).
```

### Output `metadata.status` contract

Every output YAML carries a `metadata` block with at least:

```yaml
metadata:
  <name>_version: "1.0"
  last_updated: <ISO-8601 UTC>
  generated_by: sdlc-<skill>
  session_id: <uuid4>
  status: "draft" | "complete"
```

- `status: complete` — set **only** when all required fields are filled
  and validation exits 0.
- `status: draft` — set on early EXIT or whenever any required field is null.

**Downstream-agent rejection rule**: downstream skills/agents MUST reject
an input artifact if `metadata.status != "complete"` OR if its
`validate_schema.py` exits non-zero. Document this rule in the skill's
`references/merge-validate.md`.

### State file contract

Path: `.claude/skills-state/sdlc-<skill>.state.yaml`

Baseline schema (skills may add skill-specific keys):

```yaml
session_id: <uuid4>
skill_version: <semver>
started_at: <iso8601>
last_updated: <iso8601>
status: in_progress  # in_progress | complete | aborted
completed_themes: []
skipped_themes: []   # themes the user gated as "skip"
todo_themes: []      # themes the user gated as "todo"
pending_themes: []
current_theme: null
partial_answers: {}  # mirrors the output yaml structure, populated incrementally
```

Behavior:

- **On invocation**: check for the state file.
  - If `status: in_progress` → ask:
    *"Unfinished session found from `<last_updated>`. Resume, restart, or
    discard?"*
  - If `status: aborted` or `status: complete` and the output yaml exists,
    treat as an update flow (merge into existing output; see below).
- **During interview**: write state after every confirmed batch — not at
  theme boundaries, not at the end.
- **On EXIT**: set `status: aborted`, persist `partial_answers`, confirm to
  user, stop.
- **On completion**: set `status: complete`, keep the file as audit trail
  (do not delete).
- `validate_schema.py` ignores the state file — it validates only the
  output yaml.

**Source-of-truth on resume**: the output yaml is authoritative for
*answers* (it may have been edited manually); the state file is
authoritative for *interview progress*. If the two conflict on the same
key, surface the conflict to the user — never silently overwrite.

### Workflow phases (canonical 8-phase flow)

Every skill implements these phases, in order:

1. **Resume check** — load state if present, offer resume/restart/discard.
2. **Scan inputs** — read all dependency artifacts and ad-hoc context.
   Exit early with a clear warning if a required input is missing or
   corrupted (e.g. PRD.yaml absent for sdlc:ux). **Slice, don't slurp:**
   the large specs (`PRD.yaml`, `DATA-MODEL.yaml`, …) are read **by line
   range via `docs/INDEX.yaml`** — the location map `setup` wires. Look up
   the section/symbol you need (or `python .claude/sdlc/docs_index.py
   --show <symbol>`) and `Read` only that slice. Fall back to a whole-file
   read only when `INDEX.yaml` is absent (the project never ran `setup`)
   or the doc is genuinely small. See `.claude/rules/sdlc-docs-access.md`.
3. **Pre-fill** — build a map of values that can be derived from inputs.
   Mark each as `✓ found` (direct quote) or `⚠ inferred` (derived).
   *Recommended:* `⚠ inferred` items must never be batch-accepted; each
   needs explicit user confirmation in Phase 4 or 5 (hallucination guard).
4. **Structural questions** — questions that determine the *shape* of the
   output (e.g. monorepo? CLI vs GUI?). Asked before any theme batch.
5. **Pre-fill confirmation** — theme by theme, present pre-filled values
   for confirmation.
6. **Theme interview** — walk `<skill>-questions.yaml`. Required themes
   run unconditionally; optional themes get a now/skip/todo gate.
   Persist state after every confirmed batch.
7. **Write & validate** — write or merge `docs/<OUTPUT>.yaml`, run
   `validate_schema.py`. On validation failure, show field-level errors
   and offer interactive re-entry, then re-validate.
8. **CLAUDE.md pointer + close** — call `set_claude_md_pointer.py`, set
   state `status: complete`, then **refresh the navigation index** by
   regenerating `docs/INDEX.yaml` (`python .claude/sdlc/docs_index.py`).
   The `setup` PostToolUse hook normally refreshes the index automatically
   on every `docs/*.yaml` write, but do it explicitly here too: a
   freshly-installed hook isn't active until the next session, and a write
   path the matcher missed would otherwise leave a stale index. No-op if
   the project never ran `setup`.

### Merge behavior (Phase 7)

If `docs/<OUTPUT>.yaml` already exists:

- Load as baseline.
- Overwrite keys only where the user changed the value in this session.
- Add new keys.
- For keys the session would remove (rare), ask the user to confirm
  before deleting.
- Surface conflicts (user-edited yaml vs. state file) — never auto-resolve.
- Preserve unrelated keys you don't recognize.

### CLAUDE.md pointer contract

There is **one shared `## SDLC Documents` section** in the project root
`CLAUDE.md`. Each skill appends or updates one bullet pointing to its
artifact(s). Bullet format:

```
- `docs/<OUTPUT>.yaml`: <short purpose>. Load when working on <topics>. Last updated by `sdlc-<skill>` on <ISO-8601 timestamp>.
```

Rules:

- If the section doesn't exist → create it.
- If a bullet whose substring matches `` `docs/<OUTPUT>.yaml` `` and
  `sdlc-<skill>` already exists → update the timestamp only; do not
  duplicate.
- Append new bullets at the section's end.
- Never reorder or modify the user's existing CLAUDE.md content.

Each skill ships its own `set_claude_md_pointer.py` that implements this
logic deterministically. The script accepts a `--dry-run` flag and operates
on the project root `CLAUDE.md`. The skill calls it as the final write step
in Phase 8.

### Test-case guidance

Each skill should be tested for:

1. New output (no state file, no output file).
2. Resume from state file (no output yet).
3. Resume from state file (output already present — merge path).
4. Output file with invalid schema (validator surfaces errors).
5. CLAUDE.md pointer injection (file absent → created; bullet present →
   timestamp updated; section present but bullet missing → bullet
   appended).

### Edge cases reference

Every non-trivial skill includes `references/edge-cases.md` covering at
minimum: missing/corrupted inputs, conflicting scan signals, skipped
required fields, mid-interview abort, write-permission errors, very
large repos.

## Commands

Install Python deps (the skills' validators depend on `pydantic>=2` and `pyyaml`):

    pip install -e .          # or: uv sync

Run a skill's schema validator (from project root):

    python sdlc/skills/<skill>/validate_schema.py
    python sdlc/skills/<skill>/validate_schema.py --path docs/PRD.yaml

Smoke-test a validator against fixture YAMLs:

    python sdlc/skills/prd/validate_schema.py --path sdlc/skills/prd/_smoke/01_valid_single.yaml

Test a CLAUDE.md pointer injector without writing:

    python sdlc/skills/<skill>/set_claude_md_pointer.py --dry-run

## Repository layout

This repo is itself a Claude Code marketplace containing one plugin (`sdlc`).
Output artifacts (`docs/`, `.claude/skills-state/`) are produced **at the
consumer project's root** when the skills run — they are not present in this
repo by default.

- `.claude-plugin/marketplace.json` — top-level marketplace manifest.
- `sdlc/.claude-plugin/plugin.json` — the `sdlc` plugin manifest (skills inventory).
- `sdlc/skills/<skill>/` — per-skill folder (see "Skill directory layout" above).
- `sdlc/skills/<skill>/_smoke/` — YAML fixtures for the validator (one valid + several intentionally-broken).
- `sdlc/skills/<skill>/evals/` — eval prompts (`evals.json`), fixtures, and grader scripts.
- `.claude/settings.json` — project Claude Code settings (permissions, MCP servers).
- `pyproject.toml` / `uv.lock` — Python toolchain.
- `sdlc-*-handoff-draft.md` (root) — scratch handoff drafts; not skill assets.

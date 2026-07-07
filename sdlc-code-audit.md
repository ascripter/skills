# Cross-skill consistency audit — task ⇄ code ⇄ demo docs (step-4 delta report)

Status: standalone diagnostic, 2026-07-07. **Not runtime logic** — nothing here
feeds the `code` skill's behavior except where marked `[contract gap]`.

> **Implementation outcomes (same day, user-directed Step 2):**
> - **A2 → done** — target_files seeding rule in `task-discovery.md` + validator
>   check 21 (advisory) + gold fixtures remodeled.
> - **A3 → done, strengthened** — the skill writes `status: confirmed` itself;
>   validator check 19 *blocks* complete on any draft task (not just advisory).
> - **A4 → done, beyond the note** — user chose full task self-sufficiency:
>   schema v1.3 embeds `interface_contract` (impl tasks) + `test_spec` (test
>   tasks) at write time; checks 18 (presence, version-gated) + 20 (drift
>   advisory). Only tech stack stays in ARCH.
> - **B2 → resolved** — `unit_kind` field on tasks (all four WorkUnit kinds map
>   to `kind: implementation`); mapping documented in `task-discovery.md`.
> - **B3 → done** — `WorkUnit.kind` added to the arch schema + validator (#23
>   FILE exemption); demo ARCH validates green.
> - **C4 → done** — CLAUDE.md documents `code` as an execution skill.
> - A5/A6/B1/B4–B7, C1–C3/C5 — accepted/no change, as recommended.

Framing: the demo docs in `docs/` spec **AICF, a product** (an AI coding factory
built on LangGraph). The sdlc skills are a *different implementation of the same
factory idea* (Claude Code plugin). Divergence is only a defect when it is
accidental drift in a place where one side was modeled on the other; deliberate
platform differences (CLI-orchestrated sandbox vs. Bash tool, LangGraph
checkpoints vs. state yaml) are recorded as accepted.

## A. What `task` emits vs. what `code` needs

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| A1 | `implementation` tasks are fully codegen-ready: `target_symbol` + exactly-one `target_files` + `component_ref`→`code_location`/work_unit contract. | ✅ aligned | none |
| A2 | Non-implementation kinds (`scaffold`, `test`, `migration`, `config`, `design`) leave `target_files` optional, and the **gold fixtures model the weaker style** — file paths pushed into `outputs` (gold `TSK-001`, `TSK-003`). `code` must fall back to a path-resolution ladder. | ⚠ moderate | `task`: in Phase 3 seeding + `task-discovery.md`, draft `target_files` for every file-producing task and keep `outputs` contract-level (the schema already *says* this split; the gold fixtures don't model it). Fix the gold fixtures too — they are the de-facto style guide. No schema change needed. |
| A3 | Task-level `status: draft` does not block `metadata.status: complete` (validator checks never mention it). `code` can meet a complete artifact containing unconfirmed tasks. | ⚠ minor | `task`: add an advisory (or blocking) check — `complete` artifact SHOULD have all tasks `confirmed`. Until then `code` prompts per draft task. |
| A4 | The work_unit interface contract is deliberately NOT on the task (inherited live from ARCH). Fine — but it means `code` hard-depends on `ARCH__<cid>.yaml` at execution time, beyond what "TASKS.json is the executable backlog" suggests. | ℹ note | Document in `task`'s SKILL.md intro that TASKS files are executable only *together with* ARCH/TEST/API/DATA slices. (One sentence.) |
| A5 | No language/stack info on tasks; `code` resolves it from ARCH container `tech_stack`. By design (context slice). | ✅ aligned | none |
| A6 | `depends_on` acyclicity is validated across the union, so `code` can topo-sort without cycle recovery. | ✅ aligned | none |

## B. Demo docs (FR-013/FR-014, DATA-MODEL) vs. `task` skill actual

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| B1 | Field naming drift, demo `Task` vs. skill task: `scoped_to`(CMP-NNN)→`component_ref`(kebab id); `dependencies`→`depends_on`; `test_refs`→`implements_tests`; `acceptance: str`→`list[str]`; flat `implements_refs`→typed per-family fields (deliberate, per CLAUDE.md §4). | ✅ accepted divergence | none — the skill's typed form is strictly better for validation; demo describes AICF's internal Pydantic model, not this plugin's artifact. |
| B2 | `kind` enums disagree: demo `TaskKind = implementation \| test \| docs \| migration \| infra \| other`; skill container kinds = `scaffold \| implementation \| test \| integration \| migration \| config \| design \| chore`. Demo v1.30 maps WorkUnit kinds content→`other`, tooling→`infra` — neither exists in the skill. | ⚠ moderate | If the demo project is ever run through `/sdlc:task`, content/tooling work_units will be forced into `implementation`/`chore`. Either (a) accept that mapping and note it in `task-discovery.md`, or (b) add `content`/`tooling`-ish guidance under existing kinds. No new enum values needed — `chore` covers tooling, `implementation` covers module/content emission — but the mapping should be *written down* in `task`. |
| B3 | **Demo ARCH carries `WorkUnit.kind: module` (×40) which `arch`'s `ARCH__CONTAINER.schema.yaml` does not define.** The demo evolved (FR-013 v1.30, DATA-MODEL v2.21 `WorkUnitKind`) past the skill schema; the pydantic validator tolerates the extra key silently. | ⚠ **the one real schema gap** | `arch`: add optional `kind: callable \| module \| content \| tooling` (default `callable`) to `work_units[]` + one paragraph in `component-discovery.md`. `task`: note the kind→task-kind mapping (B2). `code` treats non-callable kinds as file-deliverables `[contract gap — handled in code's runtime logic]`. |
| B4 | Demo serializes TaskGraph as YAML (`13_task_graph.yaml` per ArtifactBase); skill writes JSON with a documented rationale. | ✅ accepted divergence | none. |
| B5 | Demo FR-052 gates (l)/(m)/(n)/(p)/(q) ≈ skill cross-checks 16/9/7/1/14a — same guarantees, different homes. Demo's tsk_contract_gate additionally covers SIG/CFG/SCT/INT ids; the plugin has no observability/config-schema stages, so those families have no skill counterpart. | ✅ accepted divergence | none (would only change if sdlc ever grows FR-009/FR-010-style skills). |
| B6 | Demo `TaskGraph.tasks[].estimated_effort` optional S/M/L ≈ skill `estimate` xs–xl. Cosmetic. | ✅ | none. |
| B7 | Demo FR-014 pairs codegen with FR-084 heal loop + FR-020 incremental test agent + FR-019 security scan, CLI-orchestrated because stage agents lack exec authority (FR-059). The plugin's `code` runs inside Claude Code where the agent *does* have Bash. | ℹ platform difference | `code` implements a native lite heal loop (see C3); no doc change. |

## C. The `code` skill contract (as designed) vs. both sides

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| C1 | `code` addresses tasks by qualified id (`TASKS/TSK-NNN`, `<cid>/TSK-NNN`) — the exact syntax task's `depends_on` already uses. No new id family; the execution ledger lives in `.claude/skills-state/sdlc-code.state.yaml`, never inside TASKS files. `task` needs no change for `code` v1. | ✅ | none |
| C2 | `code` emits `docs/CODE-MANIFEST.json` (CodeBundle-analogue: one entry per generated file — `path`, `sha256`, `producing_task`, `heal_attempts`) — pending user confirmation. The demo's `GeneratedFile.relative_path SHOULD match a producing task's target_files` check becomes `code`'s self-check. | ✅ mirrors demo | if adopted, register the manifest in CLAUDE.md's artifact table so `deploy`/verify stages can consume it. |
| C3 | Verification: demo FR-084 heals per-unit with the unit's tests, but in the skill graph tests arrive as *separate, later* `test` tasks. `code`'s loop therefore verifies in two rings: (1) per task — machine-checkable subset of `acceptance` (syntax/import/compile-level); (2) on each `test` task completion — run the authored tests against the impl they exercise, heal ≤3 (`AICF_CODEGEN_HEAL_ATTEMPTS`-style cap). | ✅ adaptation | none — this is the honest translation of FR-084 onto the task skill's graph shape. |
| C4 | `code` has no theme interview (mirrors demo stage_14 "no intra-stage interview"; HITL = plan approval + failure gates + final report). This deviates from the canonical 8-phase interview flow every other sdlc skill follows. | ℹ deliberate | CLAUDE.md gets a note that `code` (execution skill) exempts itself from the interview contract the way `setup` (infrastructure skill) already does. |
| C5 | Placement drift: task's validator warns (advisory) when `target_files` escapes `code_location`; `code` re-checks at write time and refuses path traversal (`..`, absolute paths) outright. Slightly stricter than upstream — deliberate (writes are irreversible). | ✅ | none |

## Priority queue (if acting on this report)

1. **B3** — add optional `WorkUnit.kind` to `arch` schema (the only place the
   demo and a skill schema actively disagree on a field that changes downstream
   behavior).
2. **A2** — target_files seeding guidance + gold-fixture touch-up in `task`.
3. **B2** — write down the WorkUnit-kind → task-kind mapping in `task-discovery.md`.
4. **A3** — draft-status advisory check in `task`'s validator.
5. A4/C4 — one-sentence doc notes.

None of these block scaffolding `code`; A2/A3/B3 shape two of its defensive
defaults (path ladder, draft-task prompt, kind fallback), which `code` keeps
regardless so it stays robust against older artifacts.

# sdlc-skills audit + fix plans — handoff folder

**What this is.** An audit of the `sdlc` Claude Code plugin skills (`setup → prd → ux →
design → data → api → arch → test → task → code`) plus five execution-ready fix plans,
authored 2026-07-16 in the AICF repo and intended to be **carried into the skills repo**
and executed there. It is the skill-side half of the 2026-07-12 AICF coding-readiness
audit: the corpus-side defects were fixed in the AICF repo by four plans (PLAN1–PLAN4,
executed 2026-07-14/15); the findings whose *root cause* lives in the skills — including
the original handoff items K1–K8 — are expanded, evidence-verified, and planned here.

**Audit target.** Plugin cache `sdlc/0.3.6` (the latest cached version at audit time).
Every file:line citation in this folder means *the 0.3.6 skill sources*. The skills repo
may have moved — **re-locate every citation against repo HEAD before editing**; treat a
citation that no longer matches as a signal to re-verify the finding, not to skip it.

**Executor contract.** The plans are written for an agent in the skills repo with **no
context of the originating session**. Each plan embeds its own evidence quotes and
worked examples. Do not assume access to the AICF repo — the one exception is SPLAN5's
named porting source (`src/aicf/ui/_docs_index.py` in the AICF repo), which the repo
owner transfers manually.

## File map

| File | Role |
|---|---|
| `SKILLS-AUDIT.md` | Findings **SK-NN** with severity + verified 0.3.6 evidence + the corpus episode that surfaced each + traceability matrix (K1–K8 / F-findings → SK → SPLAN). Immutable evidence — plans cite it, never edit it. |
| `SKILLS-PLANS-OVERVIEW.md` | Plan table, execution order, binding conventions, per-plan verification suite, ⚠-decision protocol. |
| `SPLAN1.md` | test→subject seam + shared test infrastructure (test, task) |
| `SPLAN2.md` | task schema & validator repairs (task) |
| `SPLAN3.md` | arch work-unit contract quality (arch) |
| `SPLAN4.md` | code packets & execution loop (code) |
| `SPLAN5.md` | pipeline-wide integrity + upstream skills + CLAUDE.md delta (setup, prd, ux, data, api, design) |
| `CLAUDE-MD-DELTA.md` | Concrete edit blocks for the skills-repo `CLAUDE.md` (applied by SPLAN5). |

## Decision log (resolved with the repo owner, 2026-07-16)

- **D1 — plan grouping: per-theme.** Cross-skill seams (test↔task↔code) stay atomic in
  one plan each; each plan header names the skill folders it touches.
- **D2 — priority paradigm: PIPELINE-WIDE FLAT retirement.** Not just the task skill
  (original K7): PRD drops the `must_have_features`/`nice_to_have_features` split and
  `milestones`; test drops the per-TST `priority`; task drops `priority` + the
  priority-monotonic gate; every "must-have FR" coverage check re-scopes to **all FRs**.
  Rationale: every consumer of this skillset is built by `/sdlc:code` — AI builds the
  whole graph at once, so an economic priority split has no downstream consumer.
  Blueprint: the AICF product spec made exactly this move for generated apps
  (DATA-MODEL v2.24 `ProductRequirements`: single flat `features`, `parking_lot`,
  Milestones deleted, `TestSpec.priority` removed), and the AICF task corpus already
  runs priority-free (PLAN1-D1).

## Execution order

SPLANs are largely independent, but the recommended order is
**SPLAN2 → SPLAN1 → SPLAN3 → SPLAN4 → SPLAN5**:
SPLAN2 first because the D2 priority removal rewrites the same validator regions
(required-field loops, check #22/#23) that SPLAN1's new checks land next to — removing
before adding avoids editing doomed code. SPLAN5 last because its CLAUDE.md delta
documents conventions the earlier plans introduce.

## Addendum (2026-07-19) — dogfooding findings A.1–A.6 ↔ Gap-1..6, already at HEAD

A second dogfooding pass (build-sandbox container, arch/test/task) surfaced six findings
(A.1–A.6). Investigation at skills-repo HEAD shows **all six are already implemented in the
skill sources**, tagged `Gap-1`…`Gap-6` (commit `483ffe7 "fixes"` — which predates this
folder's commit; the 0.3.6 plugin cache the audit ran against did not contain the arch-side
gaps). `SKILLS-AUDIT.md` stays immutable; this addendum is the evidence record. **Plan
executors must treat the Gap code as existing neighbors, not greenfield.**

| Finding | Marker | HEAD implementation | Residual |
|---|---|---|---|
| A.1 — single-file multi-branch deliverable needs a composition/entry work_unit | Gap-1 | arch `entrypoint` WorkUnit kind (`ARCH__CONTAINER.schema.yaml:323-331`), advisory in `check_component_work_units` (`arch/validate_schema.py:1712-1732`), fixtures `_smoke/23_entrypoint_valid` + `24_seam_and_gaps` | authoring guidance missing (SKILL.md/references: zero hits) → SPLAN3 step 3 |
| A.2 — don't model an externally-enforced constraint as a work_unit | Gap-2 | per-unit advisory (`arch/validate_schema.py:1690-1711`), schema `:628`, fixture 24 | authoring guidance missing → SPLAN3 step 3; complementary to SK-21's per-component advisory (SPLAN3 step 1) |
| A.3 — dependency edges priority-monotonic; lean aggregator/integration deps | Gap-3 | task check #22 BLOCKING (`task/validate_schema.py:1155`, call `:1858`; `TASKS__CONTAINER.schema.yaml:466`; `TASKS.schema.yaml:167`), invariants (a)–(c) (`granularity-and-ordering.md:77-97`), fixture `07_priority_inversion.json` | **check #22 + invariant (a) are deliberately DELETED by SPLAN2/D2** (no priority field ⇒ no inversion possible); the (b)/(c) content survives as the rewritten priority-free invariants (SPLAN2 step 1e) |
| A.4 — impl/test deferral sets stay symmetric | Gap-4 | task check #23 advisory (`task/validate_schema.py:630`, `:1534`), CLAUDE.md §6a, fixture `08_defer_asymmetry/` | SPLAN2 step 1b reworks the could-arm to deferral-only (consistent with A.4) |
| A.5 — pin the cross-container INPUT contract on the shared seam | Gap-5 | system-edge `invocation` field (`ARCH.schema.yaml:194-203`), container `external_edges` `via_unit` + `invocation` (`ARCH__CONTAINER.schema.yaml:434-482`), cross-check #27 advisory (`arch/validate_schema.py:1974-2007`), fixture 24 | authoring guidance missing → SPLAN3 step 3 |
| A.6 — bind the concrete variant of a parameterized code_location | Gap-6 | check #20 Gap-6 arm (`arch/validate_schema.py:1543-1554`), schema `:571`, fixture 24 | authoring guidance missing → SPLAN3 step 3; its warning text says "MVP-variant" — D2 vocabulary, sweep in SPLAN5 step 4 |

Owner decisions 2026-07-19: execution starts with SPLAN2 (folder order); **⚠B resolved: drop**
(condition "tell the skill directly which inputs it shall take" is satisfied by the v1.4
self-contained-task embeds + SPLAN2 step 2 + SPLAN4 steps 1–2); **⚠A resolved: (i) new
`kind: test_infrastructure`**.

## Provenance chain (for archaeology)

AICF repo, `claude-scratchpad/`: `AUDIT-FINDINGS.md` (F1–F23 corpus findings + K1–K6
skill handoff; K7/K8 added during PLAN1/PLAN3) → `PLANS-OVERVIEW.md` + `PLAN1..4.md`
(all EXECUTED; the corpus is /sdlc:code-READY at task-validator exit 0). Key corpus
artifacts referenced as worked examples in these plans: `docs/TASKS__aicf-cli.json` v1.8
(TSK-414 shared test infra; 191 rewired test deps per `fix_scripts/f21_map.json`),
`docs/ARCH__aicf-cli.yaml` v1.19 (214 authored work-unit contracts;
traces_data_entities completion), `docs/TEST-STRATEGY__aicf-cli.yaml` v1.9.

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

## Provenance chain (for archaeology)

AICF repo, `claude-scratchpad/`: `AUDIT-FINDINGS.md` (F1–F23 corpus findings + K1–K6
skill handoff; K7/K8 added during PLAN1/PLAN3) → `PLANS-OVERVIEW.md` + `PLAN1..4.md`
(all EXECUTED; the corpus is /sdlc:code-READY at task-validator exit 0). Key corpus
artifacts referenced as worked examples in these plans: `docs/TASKS__aicf-cli.json` v1.8
(TSK-414 shared test infra; 191 rewired test deps per `fix_scripts/f21_map.json`),
`docs/ARCH__aicf-cli.yaml` v1.19 (214 authored work-unit contracts;
traces_data_entities completion), `docs/TEST-STRATEGY__aicf-cli.yaml` v1.9.

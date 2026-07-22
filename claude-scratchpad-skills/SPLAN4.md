# SPLAN4 — code packets & execution loop

Skills touched: **code** only. Findings: SK-04, SK-25, SK-26, SK-27, SK-28. Corpus
lineage: **K2, K3, K4**, F9's residual, F3/F5's delivery channel, and the PLAN4
sign-off false-green.
Status: **EXECUTED 2026-07-20**. Line numbers = 0.3.6; re-locate at HEAD.

> **Execution reconciliation (2026-07-20).** Five deviations, all verified
> against HEAD before executing:
> 1. **Fold-in (new scope):** SPLAN1's ⚠A created `kind: test_infrastructure`
>    after this plan was authored, and the code skill had ZERO mentions of it
>    (no emit-rules entry, no SKILL.md kind-table row, no wave rule) — a worker
>    receiving one had no instructions. Landed with steps 2/3: a rendering
>    entry (scaffold-like, file-header provenance, description carries
>    mock_policy/fixture_strategy verbatim), a kind-table row, and the
>    runs-solo wave rule (it is SK-27's canonical directory-pinned case).
> 2. **Live-corpus ACR regression impossible:** the corpus PRD has zero
>    `"ACR-NNN:"` definition lines and no corpus `test_spec.covers` names an
>    ACR — the corpus regression is FR-only (TSK-238); ACR resolution is
>    proven by the demo-docs golden check instead. Step 1b's stock-PRD shape
>    claim verified correct (`prd/PRD.schema.yaml:304-314`).
> 3. **Step 5 concretized:** demo-docs had no PRD.yaml, and adding one
>    activates the task validator's union FR gate (fully-stitched, no
>    transitive ARCH credit) — so TSK-003/004 gained `implements` and
>    TSK-005/006 gained `test_spec.covers` (their `test_spec` already
>    existed, contrary to the plan draft's "no test_spec" note). Golden
>    script = `_smoke/emit_selftest.py` (mirrors work_units_style_selftest
>    conventions). Fingerprint-safe: only `TASKS/TSK-001` is pinned by
>    demo-state.yaml and was not touched.
> 4. **No eval change:** `evals.json` never asserts brief composition.
> 5. **No SKILL.md version touch:** the field doesn't exist in code's
>    SKILL.md; not introduced mid-plan.
> The `--overlap` helper (step 3b "only if cheap") was included per owner
> decision (2026-07-20 review).

## Steps

### 1. SK-25/K2 — test packets get requirement grounding

`emit_packets` (`topo_order.py:287-329`) joins only `implements` +
`implements_workflows` (:305); a test task's requirement ids live in
`test_spec.covers`, so **every test-task packet ships an empty requirement_context**
(corpus: all 224). `_REQ_RE` (:66) matches only `FR|NFR|WKF`, so ACR can never resolve.

a. In `emit_packets`, extend the id harvest: after the two fields, also read
   `(task.get("test_spec") or {}).get("covers")` — same dedup, same
   `requirement_context` join, same `requirement_context_unresolved` fallback.
b. Extend `_REQ_RE` to `(?:FR|NFR|WKF|ACR)` and confirm `load_requirements`' line-grep
   picks up PRD acceptance-criteria items (they are quoted `"ACR-NNN: …"` list lines
   under `success_metrics.acceptance_criteria` — same shape as FR lines; verify
   against a real PRD before shipping).
c. SKILL.md/emit-rules: update the "requirement grounding rides in the packet" claims
   to include test tasks (they were false before this fix).

### 2. SK-26/K3 — the worker brief carries the per-kind rendering rules

The brief's enumerated emit-rules inclusion is "the provenance-marker and path-safety
rules" only (`execution-loop.md:55-57`; SKILL.md:225-228) — while the ONLY instruction
to fetch entity shapes ("`touches_entities` names the DATA-MODEL entities … **read
their INDEX slices**") sits in the implementation-rendering Body, `emit-rules.md:94-96`,
which the brief never includes. Workers get entity names with no fetch instruction —
F3/F5's channel failure.

a. Restructure `emit-rules.md`: pull the per-kind rendering rules (implementation
   :61-108 + other kinds :110-146) into a clearly-bounded **"Worker digest"** section
   (provenance marker + path safety + per-kind rendering + the entity-slice fetch +
   the requirement_context consumption rule).
b. `execution-loop.md:55-57` + `SKILL.md:225-228`: the brief includes "the **worker
   digest** from emit-rules.md" (one named block — no more cherry-picking two rules
   out of it).
c. SK-28/K4 (one line, same file): the entity-slice fetch presumes `docs/INDEX.yaml`
   at the project root (the `setup` layout); when the factory runs against another
   layout, the manager resolves the INDEX path once and states it in the brief.

### 3. SK-27 — path-aware wave disjointness

"Pairwise disjoint `target_files`" (`execution-loop.md:45-48`) is literal set-overlap;
directory pins (the task-side convention for multi-file deliverables, e.g.
`target_files: ["tests/"]`) don't register overlap with files beneath them — the
corpus's test-infrastructure task vs 191 test files under `tests/…` is exactly this
shape.

a. Rule text (execution-loop + SKILL.md wave section): *overlap is path-aware — a
   directory entry contains every path beneath it (`a/` overlaps `a/b/c.py`); a task
   with a directory-pinned target runs **solo** (or strictly serialized before its
   dependents), like scaffold tasks.*
b. Optional helper (only if cheap): a `topo_order.py --overlap <qid> <qid>…` debug
   subcommand using prefix containment — mirrors `_path_within_any`
   (`task/validate_schema.py:403-411`). Not required; the rule is prose-enforced by
   the manager.

### 4. SK-04 — measurement rule + ledger exit codes

a. `execution-loop.md` verification rings (:61-63, :76-106): add the rule — *run gate
   commands BARE and capture the exit code directly; never read `$?` after a pipe
   (`cmd | tail; echo $?` reports tail's exit). Redirect to a file when output must be
   kept: `cmd > ring.out 2>&1; echo $?`.* Corpus evidence: an upstream validator ran
   false-green for a full plan cycle behind a `| tail`, masking 294 real errors.
b. Ledger schema (`state-and-idempotency.md`): ring records carry the captured
   numeric exit code, not just pass/fail prose.

### 5. Fixtures + evals

- `_smoke/demo-docs`: add a test task whose `test_spec.covers` names an FR + an ACR;
  assert the emitted packet's `requirement_context` resolves both (a tiny
  `topo_order.py --emit` golden check — the code skill has no validator fixtures for
  emit today, so this is the first; keep it a plain assert script beside demo-docs).
- `evals/evals.json`: extend if it asserts on brief composition.
- SKILL.md version/date touch.

## Verification / done when

- Golden emit check: implementation packet unchanged; test packet now carries
  resolved covers (FR/NFR/WKF/ACR).
- Live meta-corpus regression: `topo_order.py --scope all` unchanged;
  `--emit aicf-cli/TSK-238` (a corpus test task) shows its `covers` FRs resolved in
  `requirement_context` (was empty).
- Docs: the brief-composition list names the worker digest; grep confirms no stale
  "provenance-marker and path-safety rules" enumeration remains.

## Execution ledger

- [x] 1 emit covers+ACR (+PRD line-shape verified) — `emit_packets` harvests
  `test_spec.covers`; `_REQ_RE` admits ACR; module/emit/load_requirements
  docstrings + SKILL.md (:68/:181/:221) + execution-loop (:52/:151) claims
  updated. Corpus `--emit aicf-cli/TSK-238`: FR-018 + FR-056 resolved (was
  `{}`); impl packet (`build-sandbox/TSK-004`) byte-identical to HEAD.
- [x] 2 worker digest restructure + brief list + K4 line — emit-rules.md now
  has a bounded "## Worker digest … *End of worker digest.*" block (path
  safety, one-file merge, per-kind rendering, provenance, what-NOT-to-write,
  plus a promoted "Packet consumption" section: requirement_context rule +
  entity-slice fetch + the K4 INDEX-path line); both brief lists
  (execution-loop, SKILL.md) name the digest; stale two-rule enumeration
  grep-clean.
- [x] 3 path-aware overlap rule + --overlap helper — rule in execution-loop
  wave bullet + SKILL.md wave step + "why disjoint" paragraph;
  `topo_order.py --overlap` (segment-prefix containment mirroring task's
  `_path_within_any`, exit 0/1). Proven on the corpus incident shape:
  `TSK-414 tests/` vs `TSK-238 tests/aicf/...` → 1; nested dirs → 1;
  disjoint dirs → 0.
- [x] 4 measurement rule + ledger exit codes — "Measure rings bare" paragraph
  in execution-loop rings section (294-error false-green evidence);
  state-and-idempotency ledger gains `ring_exit`, `ring_container_exit`, and
  the `failure: "exit N: …"` prefix; SKILL.md ring-closure step points at the
  rule.
- [x] 5 golden emit fixture · verification green — NEW demo-docs/PRD.yaml
  (FR-001/002 + ACR-001/002, post-D2 flat features) + implements/covers on
  TSK-003..006 + NEW `_smoke/emit_selftest.py` (7 assertions).
- [x] fold-in: test_infrastructure rendering entry + kind-table row + solo
  wave rule (see reconciliation note 1).

**Post-execution baselines (2026-07-20):** `emit_selftest.py` SELFTEST PASS
(exit 0, 7/7). Task validator on demo-docs: exit 0, output byte-identical to
pre-change baseline (4 warnings). Corpus: `--scope all` byte-identical to HEAD
(exit 0, 461 pending); `--emit aicf-cli/TSK-238` exit 0 with covers FRs
resolved; impl packet emit byte-identical. `py_compile` clean on topo_order.py
+ emit_selftest.py.

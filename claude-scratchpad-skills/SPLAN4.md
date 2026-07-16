# SPLAN4 — code packets & execution loop

Skills touched: **code** only. Findings: SK-04, SK-25, SK-26, SK-27, SK-28. Corpus
lineage: **K2, K3, K4**, F9's residual, F3/F5's delivery channel, and the PLAN4
sign-off false-green.
Status: **open**. Line numbers = 0.3.6; re-locate at HEAD.

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

- [ ] 1 emit covers+ACR (+PRD line-shape verified)
- [ ] 2 worker digest restructure + brief list + K4 line
- [ ] 3 path-aware overlap rule (+optional --overlap helper)
- [ ] 4 measurement rule + ledger exit codes
- [ ] 5 golden emit fixture · verification green

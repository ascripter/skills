# sdlc-test eval suite

Three evals exercise the two interview modes plus the `--next` resolver:

| # | name | invocation | what it gates |
|---|------|------------|---------------|
| 1 | `system-workflow-coverage` | `/sdlc:test` | system file + the **cross-container WKF-NNN coverage gate** (every workflow traced by ≥2 containers is covered or deferred) + global policy + ID formats |
| 2 | `container-coverage-gate` | `/sdlc:test backend-api` | container file + the full **trace-or-defer gate**: FR-001..FR-004, the two acceptance-bearing components, `postgres-unavailable`, `jwt-forgery`, `pii-in-logs`; `component_ref`/`targets_*` integrity; no `covers: FR-005` |
| 3 | `next-advances-to-container` | `/sdlc:test --next` | the resolver: system already done → skip not-ready `web-frontend`/`digest-worker` → advance to ready `backend-api`, leave the system file's tests intact, register it in `container_strategies[]` |

## Fixtures

The upstream chain is reused from `sdlc-arch`'s validator-clean
`web-app-with-digest-job` project (a small task tracker with a weekly digest
worker), plus a complete `ARCH.yaml` and one enriched, arch-validator-clean
`ARCH__backend-api.yaml`. The enrichment (component `acceptance_criteria` +
`security_concerns`) is what gives the coverage gate teeth.

- `fixtures/web-app/docs/` — base chain + the **system** `ARCH.yaml` (no
  container `file_path`, so it's clean with no siblings). Used by eval 1.
- `fixtures/web-app-container/docs/` — the **container** `ARCH.yaml`
  (`backend-api.file_path` set) + `ARCH__backend-api.yaml`. Used by evals 2/3.
- `fixtures/next-resolver/docs/TEST-STRATEGY.yaml` — a complete **system** test
  strategy used as the "system is already done" starting state for evals 2/3.
- `fixtures/_gold/TEST-STRATEGY__backend-api.yaml` — a reference *correct*
  container output. **Not** staged as an input; used only to self-test the
  grader (see below).

An eval may pull files from several scenario dirs as long as no two map to the
same destination — that's how evals 2/3 reuse the base chain while overriding
`ARCH.yaml` and adding the pre-existing system file.

## Running

```bash
# 1. stage per-eval test-project dirs under sdlc-test-workspace/iteration-N/
python sdlc/skills/test/evals/stage_iteration.py --iteration 1

# 2. run each eval: spawn a subagent per eval that treats its test-project/ as
#    the project root and runs the sdlc-test skill with that eval's prompt
#    (plus a baseline run with no skill), saving outputs into test-project/docs/.

# 3. grade: structural checks + the validator exit-code, per eval
python sdlc/skills/test/evals/grade.py --iteration 1   # writes benchmark.md
```

The workspace (`sdlc-test-workspace/`) is generated and git-ignored.

## Grader self-test

The grader's structural checks mirror the validator's trace-or-defer semantics.
To confirm grader + validator agree before spending subagent runs: copy
`fixtures/next-resolver/docs/TEST-STRATEGY.yaml` and
`fixtures/_gold/TEST-STRATEGY__backend-api.yaml` into the staged test-projects
(registering `backend-api` in the system file's `container_strategies[]`), then
`grade.py` should score every eval green. Corrupt the gold container file
(e.g. `covers: [FR-005]`, drop a security test, strip a `component_ref`) and the
matching assertions — and the validator exit code — must flip to fail.
Re-stage with `stage_iteration.py` to wipe the self-test outputs.

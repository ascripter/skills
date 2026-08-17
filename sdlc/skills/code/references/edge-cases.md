# Edge cases (sdlc-code)

Unusual situations and how to handle them. The theme throughout: generation
degrades gracefully (warn + continue), destruction never happens implicitly
(gate + ask).

## Upstream / preconditions

- **Task file exists but `metadata.status: "draft"`, or task's validator exits
  non-zero** → refuse (downstream-rejection rule). Name the file and say
  exactly what to run: `/sdlc:task <cid>` (or fix the reported check). No
  partial execution of draft graphs.
- **`docs/TASKS.json` absent but `TASKS__<cid>.json` present** → container
  runs work (cross-file `TASKS/…` deps simply can't resolve — treat them like
  blocked-by-missing and gate). Plain `/sdlc:code` and `--next` warn that the
  stitch is missing and offer to proceed container-by-container or stop.
- **`ARCH__<cid>.yaml` or `TEST-STRATEGY__<cid>.yaml` missing/unreadable** →
  that container is not executable; skip it with a clear message, continue
  with others in scope.
- **A task-graph hand-edit broke the union graph** (dangling `depends_on`,
  cycle): `topo_order.py` reports it and exits non-zero → refuse that scope
  with the tool's output quoted (the artifact should be re-validated via
  task's validator; a `complete` artifact can't legally contain either).
- **Individual task with `status: "draft"` inside a complete artifact** →
  per-task gate before executing it (position-1: execute as specified). Batch
  the confirmations at the plan gate when there are several.
- **`PRD.conventions` present** → honour binding buckets (naming, layout)
  when rendering code, same as every other skill honours them when writing
  artifacts.

## Path & write problems

- **No resolvable path after the ladder** (no target_files, no path-shaped
  outputs, no code_location) → ask, with a proposed conventional path as
  position-1. Record `path_source: user`.
- **Absolute path or `..` in target_files** → refuse the task, name it in the
  close report as a task-graph bug. Do not "fix" the path yourself.
- **Write-permission error mid-run** → the ledger has everything up to the
  failed write; report the OS error, mark the task `failed`
  (`failure: "EACCES …"`), continue with tasks whose targets are writable.
- **Two different tasks pin the same `target_symbol` in the same file** —
  can't happen in a validated artifact (uniqueness gate); if met anyway
  (hand-edit), gate: which task owns the symbol?

## Test / heal problems

- **No test command derivable** (scaffold defines no runner, toolchain
  missing) → `verified: none` for affected rings, prominent warning in the
  close report, generation continues. Offer the user a one-question chance to
  supply the command; record it in `containers[<cid>].test_command`.
- **Test task whose implementation task `failed`** → it is `blocked`; don't
  author tests against code that isn't there (they'd fail vacuously and burn
  heals).
- **A TST spec that can't be realized as written** (e.g. references an
  operation the implementation legitimately doesn't expose per ARCH) → don't
  bend the code to a wrong test; **raise an `FND-NNN`** with the contradiction
  spelled out (`execution-loop.md` → "Raising a finding") and gate. This is
  upstream drift between TEST-STRATEGY and ARCH; `/sdlc:repair` localizes and
  fixes it there, never here.
- **Systemic failure** (runner broken, scaffold missing, same infrastructure
  error on two consecutive tasks) → stop the loop and gate; do not burn ≤3
  heals per task on an environment problem.
- **Heal wants to edit outside the ring's scope** (unit heal touching another
  component) → that's a sign the failure is integrational; leave the unit
  red, let the wider ring (component/container) own the fix.

## Scale & session problems

Full protocol: `session-and-limits.md`. The cases that need naming here:

- **Very large graphs** (aicf-cli scale: 400+ tasks in one container across 26
  components) → the component checkpoint, not `--next`, is the primary seam;
  keep the default `next_component` budget and let the ledger carry the split.
  `--next` remains right when the user wants exactly one unit.
- **Usage limit hit mid-worker** → the worker's breadcrumb records how far it
  got; a fresh session resumes that unit at its phase. Do **not** advise
  `/resume` — the ledger is the handoff, not the transcript.
- **Context exhaustion mid-container** → harmless: the manager holds no unique
  state. Per-unit ledger writes mean a fresh session resumes losslessly, and
  keeping the manager thin (packets and digests passed as file paths, capped
  worker reports) is what keeps compaction rare in the first place.
- **Interrupted heal** (session died inside attempt 2) → the breadcrumb carries
  the attempts and their outcomes, so the resumed unit starts at attempt 3
  rather than restarting the ladder. Without a breadcrumb (pre-0.2 state, or a
  worker killed before its first write) the counter restarts — acceptable and
  bounded.
- **A breadcrumb that doesn't match disk** (hashes differ, files missing, or the
  task's fingerprint changed under it) → discard it and regenerate the unit; say
  so at the plan gate. A breadcrumb is evidence, never authority.
- **Agent tool unavailable** → units execute inline, one at a time. Serial is
  already the default, so only the context isolation is lost; note the
  degradation in the close report and expect compaction sooner.

## WorkUnit / contract edge cases

- **Pre-1.3 task artifacts** (no embedded `interface_contract`/`test_spec`/
  `unit_kind`): fall back to the upstream lookups — the ARCH work_unit for the
  contract (its `kind` field for the rendering mode; the API operation when it
  defers), the TST entry for the test spec. Say so once at the plan gate
  ("task artifact predates v1.3 — codegen will read ARCH/TEST-STRATEGY per
  task; re-running /sdlc:task embeds the contracts"). The rendering modes for
  non-callable kinds are first-class in `emit-rules.md`, not an edge case.
- **Work_unit contract genuinely underdetermines behaviour** → gate with the
  specific question; write nothing until answered (no stubs — see
  emit-rules).
- **`work_units_waiver` components** (no units, realized by wiring) →
  correctly produce no implementation task; their behaviour materializes via
  `integration`/`scaffold` tasks. Nothing to do.

## Interaction with other skills' outputs

- Never edit `docs/*.yaml` / `docs/TASKS*.json` — upstream artifacts are
  read-only to this skill (the one exception: `docs/CODE-MANIFEST.json`,
  which this skill owns).
- `CLAUDE.md`: only via `set_claude_md_pointer.py`.
- If the run reveals a defect in an *upstream artifact* — a task-graph bug
  (wrong path, impossible acceptance, missing dependency edge) or a spec defect
  (an underdetermined contract, a test that contradicts it) — **raise an
  `FND-NNN`** and carry on. Do not patch the JSON or the YAML, and do not try to
  work out which stage to fix: `/sdlc:repair` owns localization, and the stage
  that looks wrong from inside codegen is often one hop downstream of the real
  source (CLAUDE.md §9 — an embed is never the source).
- A finding is for a broken *specification*. An ordinary red test is a `failed`
  task, not a finding; a queue that fills with those is a queue nobody reads.

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
  bend the code to a wrong test; gate with the contradiction spelled out —
  this is upstream drift between TEST-STRATEGY and ARCH, fixed there, not
  here.
- **Systemic failure** (runner broken, scaffold missing, same infrastructure
  error on two consecutive tasks) → stop the loop and gate; do not burn ≤3
  heals per task on an environment problem.
- **Heal wants to edit outside the ring's scope** (unit heal touching another
  component) → that's a sign the failure is integrational; leave the unit
  red, let the wider ring (component/container) own the fix.

## Scale & session problems

- **Very large graphs** (aicf-cli scale: ~180 impl tasks + tests) → prefer
  `--next` (one container per invocation); at the plan gate for a full run,
  say the expected task count and suggest container-sized sessions. The
  ledger makes any split safe.
- **Context exhaustion mid-container** → the per-task ledger writes mean a
  fresh session resumes losslessly; keep per-task context slices tiny (that's
  what atomic tasks are *for*) rather than accumulating whole-file history.
- **Interrupted heal** (session died inside attempt 2) → Phase-1 reconcile:
  the task is `in_progress`; re-run its ring from disk state; heal counter
  restarts (attempts are not durable across sessions — acceptable, bounded).

## WorkUnit / contract edge cases

- **`WorkUnit.kind` present in ARCH** (demo-style `module` / `content` /
  `tooling` — a field newer ARCH docs may carry even though the arch schema
  in this repo doesn't define it yet): the deliverable is the **file**, not a
  callable. `module` → emit the module whose definition set is the interface
  (e.g. a schemas file); `content` → the shipped content file the unit names;
  `tooling` → the tool/script. `target_symbol` then names the deliverable,
  and the marker goes in the file header.
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
- If the run reveals a *task-graph* defect (wrong path, impossible acceptance,
  missing dependency edge), record it in the close report as "fix in
  /sdlc:task" — do not patch the JSON.

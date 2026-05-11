# Edge cases

Read this whenever the agent hits an unusual situation that doesn't fit
the happy path.

- **No project files found**: skip Phase 2; Phase 3 takes Branch B (cold
  idea capture). Phase 4 onward proceeds normally.
- **`docs/PRD.yaml` exists but no state file**: this is an update flow. Show
  `metadata.last_updated` and `metadata.status`, ask: "Run an update interview, or abort?"
- **Conflicting signals across scanned files** (e.g. README says
  "TypeScript" but `package.json` has no TS deps): surface the conflict
  during Phase 5 — do not silently pick one.
- **User skips a required field** during the interview: write `null` to
  the field, set `metadata.status = "draft"`, and add an informational
  entry to `prd_warnings`. The validator will surface the missing path on
  the next run.
- **Validation failure**: show field-level errors verbatim, list affected
  paths, offer via `AskUserQuestion`: "Fill in now, or accept draft status?"
  Re-run validation after re-entry.
- **User aborts mid-interview**: set `status: aborted`, write current
  `partial_answers`, confirm to user that state was saved before exiting.
  The PRD (if written) will have `metadata.status: draft`.
- **Very large projects (>500 readable files)**: limit scan to the
  priority list and tell the user what was skipped.
- **No write permission on `docs/PRD.yaml` or `CLAUDE.md`**: report the path
  and the OS error verbatim. Do not retry silently.
- **User wants to skip Phase 3 idea capture**: respected. They can type
  `ok` on Branch A or a one-word answer on Branch B. The interview
  proceeds normally; idea-extraction pre-fills will be sparse.
- **Resume with stale state**: if the state file's `skill_version` is
  older than the current skill's version, warn the user and offer to
  restart cleanly. Don't auto-migrate state across versions.
- **Monorepo answer changes mid-flow**: if the user wants to switch from
  single → multi (or vice versa) after some themes have been answered,
  warn that this requires re-keying every answered field. Offer to
  restart or to keep answers and re-shape on write (Phase 7).
- **Hallucination guard violation attempt**: if the user tries to
  batch-accept `⚠ inferred` items without explicitly selecting or correcting,
  refuse and re-prompt. Each `⚠` item needs an explicit confirmation or
  correction. This applies to both Phase 5 pre-fill confirmation and the
  Phase 6 product_identity synthesis batch.

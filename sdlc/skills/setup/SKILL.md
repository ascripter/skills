---
name: setup
description: >
  Run ONCE before /sdlc:prd to bootstrap a project for the SDLC document
  pipeline. Wires an automatic docs/INDEX.yaml navigation map: installs a
  stdlib-only generator, a Write|Edit PostToolUse hook that refreshes the
  index on every docs/*.yaml edit, the slice-don't-slurp access rule, and the
  CLAUDE.md pointer. Trigger only on /sdlc:setup or a direct request to set up
  the sdlc docs toolchain / docs index. Idempotent — safe to re-run.
user-invocable: true
disable-model-invocation: true
model: sonnet
effort: medium
allowed-tools: Read Write(CLAUDE.md) Write(.claude/**) Write(docs/INDEX.yaml) Edit(CLAUDE.md) Edit(.claude/**) Bash Bash(python *) Bash(uv *) Bash(ls *) Glob AskUserQuestion
---

# sdlc-setup

Bootstraps a consumer project so its SDLC specs stay cheap to navigate as they
grow. `docs/PRD.yaml` and `docs/DATA-MODEL.yaml` routinely reach thousands of
lines; an agent that loads one whole burns a large slice of its context window.
This skill wires a generated **`docs/INDEX.yaml`** location map (file + line
range + one-line summary per symbol) plus the protocol and automation that keep
it current, so every downstream skill and agent reads by slice instead.

**Run this once, before `/sdlc:prd`.** It is fully idempotent — re-running only
fills gaps and refreshes the index, never duplicates.

## What it installs into the project

| Target | Purpose |
|---|---|
| `.claude/sdlc/docs_index.py` | Stdlib-only index generator (zero deps; copied from this skill). Also a `--show <symbol>` power tool. |
| `.claude/settings.json` | A `Write\|Edit\|MultiEdit` **PostToolUse hook** that regenerates the index after any `docs/*.yaml` edit. Merged in — existing settings preserved. |
| `.claude/rules/sdlc-docs-access.md` | The slice-don't-slurp retrieval protocol agents follow. |
| `CLAUDE.md` (`## SDLC Documents`) | Slice-first access note + the `docs/INDEX.yaml` pointer. Coexists with the per-artifact bullets `prd`/`ux`/`data`/`arch` add to the same section. |
| `docs/INDEX.yaml` | Generated once now (no-op if `docs/` is empty). |

## Files in this skill

| File | Purpose |
|---|---|
| `SKILL.md` | This file — the workflow. |
| `docs_index.py` | The generator that gets copied into the target. Read it only if asked to extend index coverage. |
| `wire_setup.py` | Deterministic installer that performs all of the above. The skill calls it; you do not hand-edit the targets. |
| `assets/sdlc-docs-access.md` | The rule-file template copied into the target. |

## Workflow

### 1 — Confirm this is the right moment
`sdlc:setup` is a project bootstrap step. Briefly confirm the project root is
the current working directory (where `docs/` will live). If a `docs/INDEX.yaml`
and the hook already exist, tell the user it's already wired and a re-run will
just refresh — proceed only if they want that.

### 2 — Pick the Python invocation for the hook
The hook command must call a Python that exists on this machine. Decide which:

- If the project uses **uv** (a `pyproject.toml` *and* `uv` is on PATH —
  `uv --version`), use `uv run python`. This matches how the project already
  runs Python and needs no global interpreter.
- Otherwise use a bare interpreter: `python` on Windows, `python3` on
  macOS/Linux (whichever `--version` succeeds).

The generator is **dependency-free stdlib**, so any Python 3.8+ works — the only
goal is naming an interpreter the hook shell can find. When unsure, ask the user
with `AskUserQuestion`, recommending the detected default.

### 3 — Preview, then wire
Run a dry-run first so the user sees exactly what changes:

```bash
python sdlc/skills/setup/wire_setup.py --project-root . --python "<chosen>" --dry-run
```

On approval, apply it:

```bash
python sdlc/skills/setup/wire_setup.py --project-root . --python "<chosen>"
```

`wire_setup.py` is deterministic and idempotent; it prints a per-target action
log and exits non-zero only on a read/write error. Do **not** hand-edit
`settings.json` / `CLAUDE.md` yourself — let the script own the merge.

### 4 — Report + the one caveat that matters
Summarize what was installed and the action log. Then flag the timing caveat:

> **Claude Code loads hooks from `settings.json` at session start.** A hook added
> mid-session does not fire until the next session. `INDEX.yaml` was generated
> now, and `sdlc:prd`/`ux`/`data`/`arch` each refresh it after they write, so the
> map stays current in this session regardless. The hook simply guarantees the
> refresh keeps happening on **manual** `docs/*.yaml` edits too, from next
> session on.

Suggest the user restart the session (or `/hooks` to verify) if they want the
automatic hook active immediately, then move on to `/sdlc:prd`.

## Re-running / updating
Re-run any time the generator improves (this skill is the source of truth for
`docs_index.py`): the installer overwrites the copied generator only when it
differs, and refreshes the index. Use `--dry-run` to preview.

## Edge cases
- **No `docs/` yet** — expected before `prd`. The index is skipped now and built
  on the first doc write (by the hook next session, or by `prd` on completion).
- **Existing unrelated hooks** — preserved; the SDLC hook is appended as its own
  PostToolUse entry. A pre-existing SDLC hook has its command refreshed in place.
- **Malformed `settings.json`** — the installer aborts with exit 2 and a clear
  message rather than clobbering it; fix the JSON and re-run.
- **Non-UTF-8 console (Windows cp1252)** — both scripts force UTF-8 stdio, so
  `--show` and the action log print cleanly.

"""Stage per-eval test-project directories for one iteration of the sdlc-task eval suite.

Usage:
    python sdlc/skills/task/evals/stage_iteration.py --iteration 1

For each eval in evals/evals.json this:
  - creates `sdlc-task-workspace/iteration-N/eval-<id>-<name>/test-project/`
    (deleting it first if it already exists)
  - copies the eval's fixture files into the test-project root, preserving
    any subdirectory structure declared in the eval's `files` list

Fixture paths in evals.json are relative to the skill root and must start with
`evals/fixtures/<scenario>/`. Everything after that prefix is the destination
path inside the test-project (so `evals/fixtures/web-app/docs/PRD.yaml` lands
at `test-project/docs/PRD.yaml`). An eval may pull files from several scenario
dirs as long as no two map to the same destination — that's how the
container/--next evals reuse the shared upstream chain while overriding ARCH.yaml
and adding the per-container TEST-STRATEGY input.

The subagent that runs each eval should treat its test-project directory as
the *project root* and write all outputs there (docs/TASKS.json,
docs/TASKS__*.json, .claude/skills-state/sdlc-task.state.yaml, CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]  # .../skills (repo)
SKILL_ROOT = Path(__file__).resolve().parents[1]  # .../sdlc/skills/task
EVALS_JSON = SKILL_ROOT / "evals" / "evals.json"
WORKSPACE = REPO_ROOT / "sdlc-task-workspace"


def _stage_one(eval_entry: dict, iteration_dir: Path) -> Path:
    eid = eval_entry["id"]
    name = eval_entry.get("name", f"eval-{eid}")
    eval_dir = iteration_dir / f"eval-{eid}-{name}"
    test_project = eval_dir / "test-project"

    if eval_dir.exists():
        shutil.rmtree(eval_dir)
    test_project.mkdir(parents=True)

    for rel in eval_entry.get("files", []):
        src = SKILL_ROOT / rel
        if not src.exists():
            raise FileNotFoundError(f"fixture missing for eval {eid}: {src}")
        parts = Path(rel).parts
        if len(parts) < 4 or parts[0] != "evals" or parts[1] != "fixtures":
            raise ValueError(
                f"fixture path must start with evals/fixtures/<scenario>/: {rel}"
            )
        rest = Path(*parts[3:])
        dest = test_project / rest
        if dest.exists():
            raise ValueError(
                f"eval {eid}: two fixtures map to the same destination {dest} "
                f"(last was {rel})"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    metadata = {
        "eval_id": eid,
        "eval_name": name,
        "prompt": eval_entry["prompt"],
        "expected_output": eval_entry.get("expected_output", ""),
        "fixtures_staged": eval_entry.get("files", []),
        "test_project_path": str(test_project.resolve()),
        "assertions": eval_entry.get("assertions", []),
    }
    (eval_dir / "eval_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    return test_project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated eval ids to (re)stage; others in the iteration are "
        "left untouched. Default: stage every eval (re-staging wipes prior runs).",
    )
    args = parser.parse_args()

    iteration_dir = WORKSPACE / f"iteration-{args.iteration}"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    evals = json.loads(EVALS_JSON.read_text(encoding="utf-8"))["evals"]
    if args.only:
        wanted = {int(x) for x in args.only.split(",") if x.strip()}
        evals = [e for e in evals if e["id"] in wanted]
        if not evals:
            print(f"ERROR: --only {args.only} matched no eval ids in evals.json")
            return 2

    print(f"Staging iteration {args.iteration} at: {iteration_dir}")
    for entry in evals:
        tp = _stage_one(entry, iteration_dir)
        n_files = sum(1 for _ in tp.rglob("*") if _.is_file())
        print(f"  eval {entry['id']:>2}: {entry['name']:<38} -> {n_files} fixture file(s)")

    gitignore = WORKSPACE / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# generated eval workspace - ignore everything\n*\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

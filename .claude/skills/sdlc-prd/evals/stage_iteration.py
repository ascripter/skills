"""Stage per-eval test-project directories for one iteration of the eval suite.

Usage:
    python evals/stage_iteration.py --iteration 1

For each eval in evals/evals.json this:
  - creates `sdlc-prd-workspace/iteration-N/eval-<id>-<name>/test-project/`
    (deleting it first if it already exists)
  - copies the eval's fixture files into the test-project root, preserving
    any subdirectory structure declared in the eval's `files` list

The subagent that runs each eval should treat its test-project directory as
the *project root* and write all outputs there.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]  # .../skills (repo)
SKILL_ROOT = Path(__file__).resolve().parents[1]  # .../sdlc-prd
EVALS_JSON = SKILL_ROOT / "evals" / "evals.json"
WORKSPACE = REPO_ROOT / "sdlc-prd-workspace"


def _stage_one(eval_entry: dict, iteration_dir: Path) -> Path:
    eid = eval_entry["id"]
    name = eval_entry.get("name", f"eval-{eid}")
    eval_dir = iteration_dir / f"eval-{eid}-{name}"
    test_project = eval_dir / "test-project"

    if eval_dir.exists():
        shutil.rmtree(eval_dir)
    test_project.mkdir(parents=True)

    # Copy each declared fixture file, preserving the path *after* the
    # `evals/fixtures/<scenario>/` prefix.
    for rel in eval_entry.get("files", []):
        src = SKILL_ROOT / rel
        if not src.exists():
            raise FileNotFoundError(f"fixture missing for eval {eid}: {src}")
        # rel looks like "evals/fixtures/<scenario>/<rest>"; strip the first
        # three components so the file lands at test-project/<rest>.
        parts = Path(rel).parts
        if len(parts) < 4 or parts[0] != "evals" or parts[1] != "fixtures":
            raise ValueError(
                f"fixture path must start with evals/fixtures/<scenario>/: {rel}"
            )
        rest = Path(*parts[3:])
        dest = test_project / rest
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    # Write metadata
    metadata = {
        "eval_id": eid,
        "eval_name": name,
        "prompt": eval_entry["prompt"],
        "expected_output": eval_entry.get("expected_output", ""),
        "fixtures_staged": eval_entry.get("files", []),
        "test_project_path": str(test_project.resolve()),
        "assertions": [],  # filled in by grader
    }
    (eval_dir / "eval_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    return test_project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=1)
    args = parser.parse_args()

    iteration_dir = WORKSPACE / f"iteration-{args.iteration}"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    evals = json.loads(EVALS_JSON.read_text(encoding="utf-8"))["evals"]

    print(f"Staging iteration {args.iteration} at: {iteration_dir}")
    for entry in evals:
        tp = _stage_one(entry, iteration_dir)
        n_files = sum(1 for _ in tp.rglob("*") if _.is_file())
        print(f"  eval {entry['id']:>2}: {entry['name']:<40} -> {n_files} fixture file(s)")

    # Stop git from tracking the workspace contents
    gitignore = WORKSPACE / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# generated eval workspace — ignore everything\n*\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

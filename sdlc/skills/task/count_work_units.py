"""Print per-component work_unit counts for an ARCH__<container>.yaml — by a real
YAML parse, never a line-grep.

Why this exists: a sequence item in `components[].work_units[]` is legitimately
written BLOCK-style ("- name: x") or FLOW-style ("- {name: x, summary: y}"). A
`grep -c '- name:'` sees only the block ones and undercounts a fully-backfilled
document — which is exactly how a `/sdlc:task` run once wrongly REFUSED a
178-work_unit container (grep found 37, missed 141 flow-style entries). Any
readiness or refusal reasoning in `sdlc:task` MUST derive work_unit presence and
counts from THIS tool's output (which loads the YAML with a real parser), and
quote it. A refusal that names zero-work_unit components must be grounded here.

It is also PLUMBING-AWARE. `sdlc:arch` documents a handful of archetypes as
legitimately unit-free (config_loader / serializer / observability_bootstrap /
error_handler — pure wiring), and lets any component record a `work_units_waiver`
opting out. A zero-work_unit component of one of those archetypes, or one with a
waiver, is NOT a gap. Only a NON-TRIVIAL component (archetype outside the plumbing
set, carrying implements_requirements or a traced contract) that declares no
work_units and no waiver is a real gap — the kind whose fix is `/sdlc:arch
<container>` upstream, not inventing a method breakdown at the task stage.

Usage (from the project root):

    python sdlc/skills/task/count_work_units.py docs/ARCH__backend-api.yaml
    python sdlc/skills/task/count_work_units.py docs/          # every ARCH__*.yaml
    python sdlc/skills/task/count_work_units.py docs/ARCH__x.yaml --json

Exit codes:
    0 — parsed OK; every non-plumbing component either has >=1 work_unit, carries
        no traces (nothing to build), or records a work_units_waiver. Safe to
        proceed with task breakdown on the parsed counts.
    1 — parsed OK, but at least one NON-TRIVIAL component has zero work_units and
        no waiver (a genuine upstream gap — fix in /sdlc:arch <container>).
    2 — could not read/parse a file (missing, not a mapping, bad YAML).
    3 — required dependency missing (pyyaml).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is required.\nInstall with:  pip install pyyaml", file=sys.stderr)
    sys.exit(3)


# Kept in lockstep with sdlc-arch's _PLUMBING_COMPONENT_ARCHETYPES (the set the
# arch validator treats as legitimately unit-free for cross-check #21).
PLUMBING_ARCHETYPES = {
    "config_loader",
    "serializer",
    "observability_bootstrap",
    "error_handler",
}

_TRACE_KEYS = (
    "traces_api_resources",
    "traces_api_operations",
    "traces_ux_surfaces",
    "traces_data_entities",
    "implements_requirements",
)


class CompCount:
    def __init__(
        self,
        component_id: str,
        archetype: Optional[str],
        n_units: int,
        has_trace: bool,
        waived: bool,
    ) -> None:
        self.component_id = component_id
        self.archetype = archetype
        self.n_units = n_units
        self.has_trace = has_trace
        self.waived = waived

    @property
    def plumbing(self) -> bool:
        return self.archetype in PLUMBING_ARCHETYPES

    @property
    def is_gap(self) -> bool:
        """A non-trivial component with a trace, zero work_units, and no waiver."""
        return (
            self.n_units == 0
            and not self.plumbing
            and self.has_trace
            and not self.waived
        )

    def note(self) -> str:
        if self.n_units > 0:
            return ""
        if self.waived:
            return "waived (work_units_waiver)"
        if self.plumbing:
            return "plumbing archetype - legitimately unit-free"
        if not self.has_trace:
            return "no traced contract - nothing to build"
        return "NON-TRIVIAL, zero work_units - fix upstream in /sdlc:arch"


def count_file(path: Path) -> List[CompCount]:
    """Parse one ARCH__<container>.yaml and return per-component counts.

    Raises ValueError on a read/parse problem (caller maps to exit 2).
    """
    if not path.exists():
        raise ValueError(f"file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"YAML parse error in {path}: {e}")
    if not isinstance(raw, dict):
        raise ValueError(f"{path} top level must be a mapping")
    out: List[CompCount] = []
    for comp in raw.get("components") or []:
        if not isinstance(comp, dict):
            continue
        cid = str(comp.get("component_id") or "?")
        archetype = comp.get("archetype")
        archetype = str(archetype).strip() if archetype else None
        units = comp.get("work_units")
        # A real parse: block-style ("- name: x") and flow-style
        # ("- {name: x, ...}") entries are both list items here.
        n_units = len(units) if isinstance(units, list) else 0
        has_trace = any(comp.get(k) for k in _TRACE_KEYS)
        waived = bool((comp.get("work_units_waiver") or "").strip())
        out.append(CompCount(cid, archetype, n_units, has_trace, waived))
    return out


def _iter_arch_files(target: Path) -> List[Path]:
    if target.is_dir():
        return sorted(target.glob("ARCH__*.yaml"))
    return [target]


def _render_text(by_file: Dict[Path, List[CompCount]]) -> str:
    lines: List[str] = []
    total_units = 0
    total_gaps = 0
    for path, comps in by_file.items():
        file_units = sum(c.n_units for c in comps)
        file_gaps = [c for c in comps if c.is_gap]
        total_units += file_units
        total_gaps += len(file_gaps)
        lines.append(f"{path.name}: {len(comps)} component(s), {file_units} work_unit(s)")
        w = max([len(c.component_id) for c in comps] + [12])
        a = max([len(c.archetype or "-") for c in comps] + [10])
        for c in comps:
            note = c.note()
            note = f"  # {note}" if note else ""
            lines.append(
                f"    {c.component_id.ljust(w)}  {(c.archetype or '-').ljust(a)}  "
                f"units={c.n_units}{note}"
            )
        lines.append("")
    verdict = (
        "OK - every non-plumbing component has work_units (or is waived/untraced)."
        if total_gaps == 0
        else f"GAP - {total_gaps} non-trivial component(s) have zero work_units "
        f"(fix upstream in /sdlc:arch)."
    )
    lines.append(
        f"TOTAL: {sum(len(c) for c in by_file.values())} component(s), "
        f"{total_units} work_unit(s); {total_gaps} non-trivial zero-unit component(s). "
        f"{verdict}"
    )
    return "\n".join(lines)


def _render_json(by_file: Dict[Path, List[CompCount]]) -> str:
    payload: Dict[str, Any] = {"files": {}, "total_work_units": 0, "total_gaps": 0}
    for path, comps in by_file.items():
        payload["files"][path.name] = {
            "work_units": sum(c.n_units for c in comps),
            "components": [
                {
                    "component_id": c.component_id,
                    "archetype": c.archetype,
                    "work_units": c.n_units,
                    "plumbing": c.plumbing,
                    "has_trace": c.has_trace,
                    "waived": c.waived,
                    "is_gap": c.is_gap,
                }
                for c in comps
            ],
        }
        payload["total_work_units"] += sum(c.n_units for c in comps)
        payload["total_gaps"] += sum(1 for c in comps if c.is_gap)
    return json.dumps(payload, indent=2)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print per-component work_unit counts for an ARCH__<container>.yaml "
        "(real YAML parse - counts block- AND flow-style entries)."
    )
    parser.add_argument(
        "path",
        type=Path,
        help="An ARCH__<container>.yaml, or a docs directory (every ARCH__*.yaml).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = parser.parse_args(argv)

    files = _iter_arch_files(args.path)
    if not files:
        print(f"ERROR: no ARCH__*.yaml found at {args.path}", file=sys.stderr)
        return 2

    by_file: Dict[Path, List[CompCount]] = {}
    for f in files:
        try:
            by_file[f] = count_file(f)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    print(_render_json(by_file) if args.json else _render_text(by_file))
    any_gap = any(c.is_gap for comps in by_file.values() for c in comps)
    return 1 if any_gap else 0


if __name__ == "__main__":
    raise SystemExit(main())

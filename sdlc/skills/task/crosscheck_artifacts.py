#!/usr/bin/env python3
"""Cross-artifact integrity linter for the SDLC docs/ chain.

Every sdlc-* validator checks its OWN artifact (plus the slices of its direct
upstreams it needs). Nothing, until this script, checked the chain ACROSS
artifacts — which is exactly where desyncs hide: a TEST-STRATEGY referencing a
retired ARCH id family, a task graph naming a work_unit an ARCH edit renamed,
an edge grounded in an API resource that no longer exists. This linter walks
every readable artifact in docs/ and verifies that every cross-artifact
reference still resolves. It duplicates no intra-file validation.

Checks (all cross-artifact):
  X1. TEST → ARCH: every container test's component_ref is a component in
      ARCH__<cid>.yaml, and targets_work_unit is a work_units[].name of that
      component. Legacy targets_operation (retired OPN family) warns.
  X2. TASKS → ARCH: every container task's component_ref resolves; every
      implementation task's target_symbol is a work_units[].name of its
      component_ref.
  X3. TASKS → TEST: every implements_tests TST-NNN resolves to a tests[].tst_id
      in some TEST-STRATEGY file; TST ids are globally unique across the
      strategy set. Under meta_corpus_dialect the id form is the
      container-namespaced TST-<PREFIX>-NNN instead.
  X4. TASKS → API/DATA/UX: touches_operations ⊆ API operation_ids,
      touches_entities ⊆ DATA-MODEL entities, implements_surfaces ⊆ UX SCR ids.
  X5. requirement refs → PRD: every FR/NFR/ACR/WKF referenced by TEST `covers`
      or TASKS `implements`/`implements_workflows` exists in PRD.
  X6. ARCH edges: from/to resolve to containers; via_resource_id ⊆ API
      resources; via_entity ⊆ DATA-MODEL entities.

Missing artifacts soften their checks: a check whose ground truth is absent
is skipped with a note (this linter must be runnable at any pipeline stage).

Usage:
    python crosscheck_artifacts.py [--docs-dir docs]

Exit codes:
    0 — no cross-artifact errors (warnings allowed).
    1 — at least one cross-artifact reference is broken.
    2 — could not read or parse a required file.
    3 — required dependency missing (pyyaml).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    print("[crosscheck] missing dependency: pyyaml (pip install pyyaml)", file=sys.stderr)
    sys.exit(3)

FR_RE = re.compile(r"^(FR|NFR|ACR|WKF)-\d+$", re.IGNORECASE)
SCR_RE = re.compile(r"^SCR-\d+$", re.IGNORECASE)
TST_RE = re.compile(r"^TST-\d{3,}$")
# Meta-corpus dialect (system TEST-STRATEGY.yaml sets meta_corpus_dialect: true):
# test shards namespace their TST ids as TST-<PREFIX>-NNN. X3 resolution honors
# the same flag `test` and validate_schema.py do; default stays flat TST-NNN.
TST_SHARDED_RE = re.compile(r"^TST-(?:[A-Z][A-Z0-9]*-)?\d{3,}$")
OPN_RE = re.compile(r"^OPN-\d{3,}$", re.IGNORECASE)
ID_TOKEN_RE = re.compile(r"\b(?:FR|NFR|ACR|WKF)-\d+\b", re.IGNORECASE)


def _yaml(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — any parse failure is fatal here
        raise SystemExit(f"[crosscheck] cannot parse {path.name}: {e}")
    return data if isinstance(data, dict) else None


def _json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[crosscheck] cannot parse {path.name}: {e}")
    return data if isinstance(data, dict) else None


def _ids_in_text_lists(node: Any) -> Set[str]:
    """Every FR/NFR/ACR/WKF token anywhere inside a nested structure."""
    out: Set[str] = set()
    if isinstance(node, str):
        out |= {m.upper() for m in ID_TOKEN_RE.findall(node)}
    elif isinstance(node, list):
        for item in node:
            out |= _ids_in_text_lists(item)
    elif isinstance(node, dict):
        for value in node.values():
            out |= _ids_in_text_lists(value)
    return out


# ---------------------------------------------------------------------------
# Ground-truth loaders (each returns None when its artifact is absent)
# ---------------------------------------------------------------------------


def load_prd_ids(docs: Path) -> Optional[Set[str]]:
    prd = _yaml(docs / "PRD.yaml")
    if prd is None:
        return None
    ids: Set[str] = set()
    for section in ("functional_requirements", "non_functional_requirements",
                    "use_cases", "success_metrics"):
        ids |= _ids_in_text_lists(prd.get(section))
    return ids


def load_data_entities(docs: Path) -> Optional[Set[str]]:
    dm = _yaml(docs / "DATA-MODEL.yaml")
    if dm is None:
        return None
    entities = dm.get("entities")
    names: Set[str] = set(entities.keys()) if isinstance(entities, dict) else set()
    products = dm.get("products")
    if isinstance(products, dict):
        for product in products.values():
            ents = (product or {}).get("entities")
            if isinstance(ents, dict):
                names |= set(ents.keys())
    return names


def load_api_ids(docs: Path) -> Tuple[Optional[Set[str]], Optional[Set[str]]]:
    """(resource_ids, operation_ids) across API.yaml + every API__*.yaml."""
    api = _yaml(docs / "API.yaml")
    resources: Set[str] = set()
    operations: Set[str] = set()
    found = api is not None
    if api is not None:
        for inv in (api.get("resource_inventory") or []):
            if isinstance(inv, dict) and inv.get("resource_id"):
                resources.add(str(inv["resource_id"]))
    for shard in sorted(docs.glob("API__*.yaml")):
        found = True
        res = _yaml(shard) or {}
        if res.get("resource_id"):
            resources.add(str(res["resource_id"]))
        for ep in (res.get("endpoints") or []):
            if isinstance(ep, dict) and ep.get("operation_id"):
                operations.add(str(ep["operation_id"]))
    return (resources if found else None), (operations if found else None)


def load_ux_scrs(docs: Path) -> Optional[Set[str]]:
    ux = _yaml(docs / "UX.yaml")
    if ux is None:
        return None
    scrs: Set[str] = set()
    for surface in (ux.get("surface_inventory") or []):
        if isinstance(surface, dict) and surface.get("id"):
            scrs.add(str(surface["id"]).upper())
    return scrs


def load_arch(docs: Path):
    """(container_ids, per-container {component_id: {work_unit names}}, edges)."""
    arch = _yaml(docs / "ARCH.yaml")
    containers: Optional[Set[str]] = None
    edges: List[dict] = []
    if arch is not None:
        containers = {
            str(c.get("container_id"))
            for c in (arch.get("containers") or [])
            if isinstance(c, dict) and c.get("container_id")
        }
        edges = [e for e in (arch.get("edges") or []) if isinstance(e, dict)]
    comp_units: Dict[str, Dict[str, Set[str]]] = {}
    for shard in sorted(docs.glob("ARCH__*.yaml")):
        cid = shard.stem.split("__", 1)[1]
        doc = _yaml(shard) or {}
        comps: Dict[str, Set[str]] = {}
        for comp in (doc.get("components") or []):
            if not isinstance(comp, dict) or not comp.get("component_id"):
                continue
            units = {
                str(u["name"]).strip()
                for u in (comp.get("work_units") or [])
                if isinstance(u, dict) and u.get("name")
            }
            comps[str(comp["component_id"])] = units
        comp_units[cid] = comps
    return containers, comp_units, edges


def meta_corpus_dialect(docs: Path) -> bool:
    """The opt-in flag on the system TEST-STRATEGY.yaml top level (never a shard)."""
    doc = _yaml(docs / "TEST-STRATEGY.yaml")
    return bool(doc.get("meta_corpus_dialect")) if isinstance(doc, dict) else False


def load_test_strategies(docs: Path):
    """(global {TST id: filename}, per-container test lists)."""
    tst_owner: Dict[str, str] = {}
    per_container: Dict[str, List[dict]] = {}
    dupes: List[str] = []
    tst_rx = TST_SHARDED_RE if meta_corpus_dialect(docs) else TST_RE
    files = [docs / "TEST-STRATEGY.yaml"] + sorted(docs.glob("TEST-STRATEGY__*.yaml"))
    found = False
    for path in files:
        doc = _yaml(path)
        if doc is None:
            continue
        found = True
        tests = [t for t in (doc.get("tests") or []) if isinstance(t, dict)]
        if "__" in path.name:
            per_container[path.stem.split("__", 1)[1]] = tests
        for t in tests:
            tid = str(t.get("tst_id") or "")
            if tst_rx.match(tid):
                if tid in tst_owner:
                    dupes.append(f"{tid} appears in both {tst_owner[tid]} and {path.name}")
                else:
                    tst_owner[tid] = path.name
    return (tst_owner if found else None), per_container, dupes


def load_task_graphs(docs: Path):
    """[(scope_label, container_id_or_None, tasks)] for TASKS.json + shards."""
    graphs = []
    system = _json(docs / "TASKS.json")
    if system is not None:
        graphs.append(("TASKS.json", None, [t for t in (system.get("tasks") or []) if isinstance(t, dict)]))
    for shard in sorted(docs.glob("TASKS__*.json")):
        doc = _json(shard) or {}
        cid = shard.stem.split("__", 1)[1]
        graphs.append((shard.name, cid, [t for t in (doc.get("tasks") or []) if isinstance(t, dict)]))
    return graphs


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def run(docs: Path) -> Tuple[List[str], List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    notes: List[str] = []

    prd_ids = load_prd_ids(docs)
    entities = load_data_entities(docs)
    api_resources, api_operations = load_api_ids(docs)
    scrs = load_ux_scrs(docs)
    containers, comp_units, edges = load_arch(docs)
    tst_owner, tests_by_cid, tst_dupes = load_test_strategies(docs)
    graphs = load_task_graphs(docs)

    for absent, name in (
        (prd_ids is None, "PRD.yaml"), (entities is None, "DATA-MODEL.yaml"),
        (api_operations is None, "API artifacts"), (scrs is None, "UX.yaml"),
        (containers is None, "ARCH.yaml"), (tst_owner is None, "TEST-STRATEGY artifacts"),
        (not graphs, "TASKS artifacts"),
    ):
        if absent:
            notes.append(f"{name} absent — its checks skipped")

    # X3 (uniqueness half)
    for d in tst_dupes:
        errors.append(f"X3 TST collision: {d}")

    # X1 — TEST → ARCH
    for cid, tests in tests_by_cid.items():
        comps = comp_units.get(cid)
        for i, t in enumerate(tests):
            where = f"TEST-STRATEGY__{cid}.tests[{i}] ({t.get('tst_id', '?')})"
            comp_ref = t.get("component_ref")
            unit = t.get("targets_work_unit")
            legacy = t.get("targets_operation")
            if legacy:
                warnings.append(f"X1 {where}: targets_operation '{legacy}' is the retired OPN family — migrate to targets_work_unit")
            if comps is None:
                continue
            if comp_ref and comp_ref not in comps:
                errors.append(f"X1 {where}: component_ref '{comp_ref}' is not a component in ARCH__{cid}.yaml")
            if unit:
                if not comp_ref:
                    errors.append(f"X1 {where}: targets_work_unit '{unit}' without component_ref")
                elif comp_ref in comps and comps[comp_ref] and str(unit).strip() not in comps[comp_ref]:
                    errors.append(f"X1 {where}: targets_work_unit '{unit}' is not a work_units[].name of '{comp_ref}' in ARCH__{cid}.yaml")

    # X2/X3/X4/X5 — TASKS → everything
    for fname, cid, tasks in graphs:
        comps = comp_units.get(cid) if cid else None
        for i, t in enumerate(tasks):
            where = f"{fname}.tasks[{i}] ({t.get('tsk_id', '?')})"
            comp_ref = t.get("component_ref")
            symbol = t.get("target_symbol")
            if cid and comps is not None:
                if comp_ref and comp_ref not in comps:
                    errors.append(f"X2 {where}: component_ref '{comp_ref}' is not a component in ARCH__{cid}.yaml")
                if t.get("kind") == "implementation" and symbol and comp_ref in (comps or {}):
                    units = comps.get(comp_ref) or set()
                    if units and str(symbol).strip() not in units:
                        errors.append(f"X2 {where}: target_symbol '{symbol}' is not a work_units[].name of '{comp_ref}' in ARCH__{cid}.yaml")
            if tst_owner is not None:
                ref_rx = TST_SHARDED_RE if meta_corpus_dialect(docs) else TST_RE
                for ref in (t.get("implements_tests") or []):
                    if ref_rx.match(str(ref)) and str(ref) not in tst_owner:
                        errors.append(f"X3 {where}: implements_tests '{ref}' resolves to no TEST-STRATEGY tests[].tst_id")
            if api_operations:
                for ref in (t.get("touches_operations") or []):
                    if str(ref) not in api_operations:
                        errors.append(f"X4 {where}: touches_operations '{ref}' is not an API operation_id")
            if entities:
                for ref in (t.get("touches_entities") or []):
                    if str(ref) not in entities:
                        errors.append(f"X4 {where}: touches_entities '{ref}' is not a DATA-MODEL entity")
            if scrs:
                for ref in (t.get("implements_surfaces") or []):
                    if SCR_RE.match(str(ref)) and str(ref).upper() not in scrs:
                        errors.append(f"X4 {where}: implements_surfaces '{ref}' is not a UX surface id")
            if prd_ids:
                for ref in list(t.get("implements") or []) + list(t.get("implements_workflows") or []):
                    up = str(ref).upper()
                    if FR_RE.match(up) and up not in prd_ids:
                        errors.append(f"X5 {where}: '{ref}' does not resolve to a PRD id")

    # X5 — TEST covers → PRD
    if prd_ids is not None:
        for cid, tests in tests_by_cid.items():
            for i, t in enumerate(tests):
                for ref in (t.get("covers") or []):
                    up = str(ref).upper()
                    if FR_RE.match(up) and up not in prd_ids:
                        errors.append(f"X5 TEST-STRATEGY__{cid}.tests[{i}]: covers '{ref}' does not resolve to a PRD id")

    # X6 — ARCH edges grounded
    if containers is not None:
        for i, e in enumerate(edges):
            where = f"ARCH.edges[{i}]"
            for end in ("from", "to"):
                val = e.get(end)
                if val and val not in containers:
                    errors.append(f"X6 {where}: {end} '{val}' is not a container")
            if api_resources and e.get("via_resource_id") and str(e["via_resource_id"]) not in api_resources:
                errors.append(f"X6 {where}: via_resource_id '{e['via_resource_id']}' is not an API resource")
            if entities and e.get("via_entity") and str(e["via_entity"]) not in entities:
                errors.append(f"X6 {where}: via_entity '{e['via_entity']}' is not a DATA-MODEL entity")

    return errors, warnings, notes


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass
    ap = argparse.ArgumentParser(description="SDLC cross-artifact integrity linter.")
    ap.add_argument("--docs-dir", default="docs", help="Path to the docs directory (default: docs).")
    args = ap.parse_args(argv)
    docs = Path(args.docs_dir)
    if not docs.is_dir():
        print(f"[crosscheck] docs dir not found: {docs}", file=sys.stderr)
        return 2

    errors, warnings, notes = run(docs)
    for n in notes:
        print(f"[note] {n}")
    for w in warnings:
        print(f"[warn] {w}")
    for e in errors:
        print(f"[FAIL] {e}")
    if errors:
        print(f"[crosscheck] {len(errors)} cross-artifact error(s), {len(warnings)} warning(s).")
        return 1
    print(f"[crosscheck] OK — no broken cross-artifact references ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

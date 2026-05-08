"""Validate sdlc-arch artifact files against bundled JSON schemas.

Usage:
    python validate_artifacts.py <path-to-yaml> [<path-to-yaml> ...]
    python validate_artifacts.py --self-test

Exit codes:
    0  all artifacts valid (or --self-test passed)
    1  one or more artifacts failed validation
    2  missing dependencies (pyyaml or jsonschema) — caller should
       degrade gracefully and skip validation rather than block.
    3  bad invocation (no inputs, file not found, etc.)

The script is project-agnostic: it has no dependencies on this
repository and can be copied into any project that uses the
sdlc-arch skill.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_MISSING_DEPS = 2
EXIT_BAD_INVOCATION = 3

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "references" / "artifact-schemas"

LEVEL_TO_SCHEMA = {
    "context": "architecture.schema.json",
    "container": "container.schema.json",
    "component": "component.schema.json",
    "code": "code.schema.json",
}


def _load_deps():
    """Import pyyaml + jsonschema lazily so we can return a clear error."""
    try:
        import yaml  # type: ignore
        import jsonschema  # type: ignore
    except ImportError as exc:
        return None, None, str(exc)
    return yaml, jsonschema, None


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _pick_schema_for(doc: dict, path: Path) -> tuple[str, dict] | tuple[None, None]:
    """Return (schema-name, schema-dict) for the given parsed YAML doc."""
    if path.name in ("sdlc-arch.state.yaml", "state.yaml"):
        return "state.schema.json", _load_schema("state.schema.json")
    level = doc.get("c4-level")
    schema_name = LEVEL_TO_SCHEMA.get(level)
    if schema_name is None:
        return None, None
    return schema_name, _load_schema(schema_name)


def _validate_file(path: Path, yaml_mod, jsonschema_mod) -> list[str]:
    """Return a list of human-readable error strings; empty means valid."""
    if not path.exists():
        return [f"{path}: file not found"]
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: read error: {exc}"]
    try:
        doc = yaml_mod.safe_load(raw)
    except yaml_mod.YAMLError as exc:
        return [f"{path}: YAML parse error: {exc}"]
    if not isinstance(doc, dict):
        return [f"{path}: top-level YAML must be a mapping, got {type(doc).__name__}"]
    schema_name, schema = _pick_schema_for(doc, path)
    if schema is None:
        return [
            f"{path}: cannot determine schema "
            f"(not a state file and 'c4-level' is missing or unknown)"
        ]
    validator = jsonschema_mod.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if not errors:
        return []
    out = [f"{path}: failed against {schema_name}"]
    for err in errors:
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"  - {loc}: {err.message}")
    return out


_SELF_TEST_FIXTURES: dict[str, dict] = {
    "sdlc-arch.state.yaml": {
        "version": "1",
        "mode": "CREATE",
        "current-pointer": "root",
        "updated-at": "2026-05-04T12:00:00Z",
        "graph": {
            "root": {
                "kind": "context",
                "status": "complete",
                "children": [
                    {
                        "canonical": "web-frontend",
                        "aliases": ["frontend", "web"],
                        "status": "complete",
                        "edges": [{"type": "calls", "to": "backend-api"}],
                        "children": [],
                    }
                ],
            }
        },
    },
    "ARCHITECTURE.yaml": {
        "doc-kind": "architecture",
        "c4-level": "context",
        "node-path": [],
        "updated-by": "sdlc-arch",
        "updated-at": "2026-05-04T12:00:00Z",
        "system": {"name": "demo", "purpose": "demo system"},
        "boundaries": {"in-scope": ["x"], "out-of-scope": ["y"]},
        "actors": ["user"],
        "external-systems": [],
        "quality-attributes": ["availability"],
        "architecture-pattern": "modular-monolith",
        "containers": [{"canonical": "web-frontend", "aliases": []}],
    },
    "web-frontend.yaml": {
        "doc-kind": "architecture",
        "c4-level": "container",
        "container": {"canonical": "web-frontend", "aliases": []},
        "node-path": ["web-frontend"],
        "updated-by": "sdlc-arch",
        "updated-at": "2026-05-04T12:00:00Z",
        "overview": "demo container",
        "responsibilities": ["render UI"],
        "components": [{"canonical": "router", "aliases": []}],
    },
    "web-frontend__router.yaml": {
        "doc-kind": "architecture",
        "c4-level": "component",
        "container": {"canonical": "web-frontend", "aliases": []},
        "component": {"canonical": "router", "aliases": []},
        "node-path": ["web-frontend", "router"],
        "updated-by": "sdlc-arch",
        "updated-at": "2026-05-04T12:00:00Z",
        "overview": "demo component",
        "responsibilities": ["map URL to handler"],
        "code": [
            {
                "canonical": "home-route",
                "kind": "api-endpoint",
                "summary": "GET /",
            }
        ],
    },
    "web-frontend__router__home-route.yaml": {
        "doc-kind": "architecture",
        "c4-level": "code",
        "container": {"canonical": "web-frontend", "aliases": []},
        "component": {"canonical": "router", "aliases": []},
        "code": {"canonical": "home-route", "kind": "api-endpoint"},
        "node-path": ["web-frontend", "router", "home-route"],
        "updated-by": "sdlc-arch",
        "updated-at": "2026-05-04T12:00:00Z",
        "summary": "Renders the landing page.",
    },
}


def _self_test(yaml_mod, jsonschema_mod) -> int:
    failures: list[str] = []
    for filename, doc in _SELF_TEST_FIXTURES.items():
        fake_path = Path(filename)
        schema_name, schema = _pick_schema_for(doc, fake_path)
        if schema is None:
            failures.append(f"self-test: {filename}: no schema picked")
            continue
        validator = jsonschema_mod.Draft202012Validator(schema)
        errors = list(validator.iter_errors(doc))
        if errors:
            failures.append(
                f"self-test: {filename}: {len(errors)} error(s) against {schema_name}"
            )
            for err in errors:
                loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
                failures.append(f"  - {loc}: {err.message}")
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_INVALID
    print(f"self-test: {len(_SELF_TEST_FIXTURES)} fixtures validated against bundled schemas.")
    return EXIT_OK


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Artifact YAML files to validate.")
    parser.add_argument(
        "--self-test", action="store_true", help="Validate bundled minimal fixtures."
    )
    args = parser.parse_args(argv)

    yaml_mod, jsonschema_mod, dep_err = _load_deps()
    if yaml_mod is None or jsonschema_mod is None:
        print(
            f"validate_artifacts: missing dependency ({dep_err}). "
            "Install with: pip install pyyaml jsonschema. "
            "Skipping validation.",
            file=sys.stderr,
        )
        return EXIT_MISSING_DEPS

    if args.self_test:
        return _self_test(yaml_mod, jsonschema_mod)

    if not args.paths:
        parser.print_usage(sys.stderr)
        return EXIT_BAD_INVOCATION

    any_failed = False
    for path in args.paths:
        errors = _validate_file(path, yaml_mod, jsonschema_mod)
        if errors:
            any_failed = True
            for line in errors:
                print(line, file=sys.stderr)
        else:
            print(f"{path}: ok")
    return EXIT_INVALID if any_failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

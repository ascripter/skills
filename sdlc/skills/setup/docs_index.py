#!/usr/bin/env python3
"""Navigation-index generator for the large SDLC artifacts under ``docs/``.

``docs/PRD.yaml``, ``docs/DATA-MODEL.yaml`` and ``docs/TASKS.json`` grow large
enough that a downstream agent loading them whole burns a big slice of its
context window. This script produces ``docs/INDEX.yaml`` — a pure *location map*
(file + line range + a short summary per addressable symbol) that lets an agent
``Read`` only the lines it needs, plus a ``shards:`` inventory naming every
``docs/*__*`` sub-artifact so agents can discover per-surface/container/resource
files without reading each parent's inventory block. The index duplicates no
field bodies, so it cannot drift in content; only line ranges move, and the
``Write|Edit`` PostToolUse hook (installed by the ``sdlc:setup`` skill) keeps
those current. The retrieval protocol agents follow lives in
``.claude/rules/sdlc-docs-access.md``.

This file is dropped into a consumer project at ``.claude/sdlc/docs_index.py`` by
``sdlc:setup``. It is **stdlib-only by design**: a line-based scanner over the
regular 2-space-indented YAML — and pretty-printed JSON (``TASKS.json``,
``CODE-MANIFEST.json``) — the SDLC skills emit. No YAML parser is imported, so
the script has zero runtime dependencies and runs under any Python 3.8+ without an
environment to set up.

Usage
-----
    python docs_index.py                     # regenerate docs/INDEX.yaml
    python docs_index.py --docs-dir path     # ... for a non-default docs dir
    python docs_index.py --hook              # PostToolUse mode: regen iff the
                                             #   edited file (read from stdin JSON)
                                             #   is a canonical doc or a shard;
                                             #   else no-op
    python docs_index.py --show <symbol>     # print one symbol's [start,end] slice
                                             #   (entity / enum name, FR-### id,
                                             #   TSK-### id, or a stage_dossiers
                                             #   map key)

Project root is resolved from ``--project-root``, then ``$CLAUDE_PROJECT_DIR``,
then the current working directory. ``docs/`` is taken relative to that root
unless ``--docs-dir`` is given explicitly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple, Optional

INDEX_FILENAME = "INDEX.yaml"

# Canonical SDLC docs the index covers, in priority order — this drives the
# deterministic ordering of the emitted index. Any *other* ``docs/*.yaml`` that
# is not a sub-artifact / snapshot (see ``_is_canonical``) is appended after
# these, alphabetically. Symbol extraction (see ``_EXTRACTORS``) only runs for
# the files that have an extractor; every covered file still gets ``sections``.
PRIORITY_FILES: tuple[str, ...] = (
    "PRD.yaml",
    "UX.yaml",
    "DESIGN.yaml",
    "DATA-MODEL.yaml",
    "API.yaml",
    "ARCH.yaml",
    "TEST-STRATEGY.yaml",
    "TASKS.json",
    "CODE-MANIFEST.json",
    "DEPLOY.yaml",  # planned — no producing skill yet
)

# Canonical docs that are JSON, not YAML. Their shards (``TASKS__<cid>.json``)
# are excluded like every ``__`` shard but listed in the ``shards:`` inventory.
_JSON_CANONICALS: frozenset = frozenset({"TASKS.json", "CODE-MANIFEST.json"})

_SUMMARY_LIMIT = 120

# The sha256 in ``generated_from`` is a change-detector, not a security digest,
# so a 16-hex (64-bit) prefix is plenty to spot a stale index and keeps the
# index lean.
_SHA_LEN = 16

# A mapping-key line: leading spaces, then an unquoted simple key, then a colon.
# List items (``- ...``) never match — ``-`` is not a valid first key character —
# so nested keys inside list items are correctly ignored.
_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w./-]*):(?:\s|$)")

# A functional-requirement list item: ``- "FR-001: ...`` (quote optional). The
# opening quote is captured so a matching trailing quote can be trimmed off the
# summary of a short, single-sentence quoted FR.
_FR_ITEM_RE = re.compile(r'^\s*-\s*(?P<q>["\']?)(?P<id>FR-\d+):\s*(?P<rest>.*)')


class SymbolSlice(NamedTuple):
    """Location of a single addressable symbol within a canonical doc."""

    file: str
    path: str
    start: int  # 1-based, inclusive
    end: int  # 1-based, inclusive
    kind: str
    context: Optional[str]
    summary: str


# ---------------------------------------------------------------------------
# Canonical-file discovery
# ---------------------------------------------------------------------------


def _is_canonical(name: str) -> bool:
    """True for a top-level SDLC doc the index should cover.

    Excludes the index itself, per-surface/container/resource sub-artifacts
    (``UX__login.yaml``, ``ARCH__backend.yaml``, ``TASKS__backend.json`` — they
    carry ``__`` and load cheaply whole; the ``shards:`` inventory names them),
    draft scratch files, and version-suffixed snapshots (``PRDv1.3.yaml``).
    JSON canonicals are whitelisted by exact name (``_JSON_CANONICALS``).
    """
    if name == INDEX_FILENAME:
        return False
    if not (name.endswith(".yaml") or name in _JSON_CANONICALS):
        return False
    if "__" in name or "_draft" in name.lower():
        return False
    # A version-suffixed snapshot like ``PRDv1.3.yaml`` / ``PRD-v2.yaml``.
    if re.search(r"v\d", name) and name not in PRIORITY_FILES:
        return False
    return True


def _is_shard(name: str) -> bool:
    """True for a ``<PARENT>__<slug>`` sub-artifact (YAML or JSON).

    Shards are never content-indexed (they load cheaply whole) but are listed
    in the ``shards:`` inventory, and an edit to one refreshes the index so
    that inventory stays current.
    """
    if "__" not in name or "_draft" in name.lower():
        return False
    return name.endswith(".yaml") or name.endswith(".json")


def _shard_parent(name: str) -> str:
    """The canonical file a shard belongs to (``UX__x.yaml`` → ``UX.yaml``)."""
    stem = name.split("__", 1)[0]
    return stem + (".json" if name.endswith(".json") else ".yaml")


def _discover_files(docs_dir: Path) -> list[str]:
    """Return canonical doc filenames present in ``docs_dir``, in index order."""
    candidates = list(docs_dir.glob("*.yaml")) + list(docs_dir.glob("*.json"))
    present = {p.name for p in candidates if _is_canonical(p.name)}
    ordered = [f for f in PRIORITY_FILES if f in present]
    ordered += sorted(present - set(ordered))
    return ordered


def _discover_shards(docs_dir: Path) -> "dict[str, list[str]]":
    """Map each parent canonical filename to its sorted shard filenames."""
    shards: dict[str, list[str]] = {}
    candidates = list(docs_dir.glob("*__*.yaml")) + list(docs_dir.glob("*__*.json"))
    for p in candidates:
        if _is_shard(p.name):
            shards.setdefault(_shard_parent(p.name), []).append(p.name)
    return {parent: sorted(names) for parent, names in sorted(shards.items())}


# ---------------------------------------------------------------------------
# Low-level line scanning
# ---------------------------------------------------------------------------


def _indent(line: str) -> int:
    """Return the count of leading spaces on a line."""
    return len(line) - len(line.lstrip(" "))


def _is_boundary(line: str) -> bool:
    """A non-blank, non-comment line can close an enclosing block."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _block_end(lines: list[str], start_idx: int, indent: int, limit: int) -> int:
    """Return the 0-based index of the last content line of a block.

    The block opened at ``start_idx`` (a key or list-item line at ``indent``)
    extends through every following line more deeply indented than ``indent``,
    skipping blank and comment lines, and closes at the first content line whose
    indent is ``<= indent`` or at ``limit`` (exclusive). Trailing blank/comment
    lines are not included.
    """
    end = start_idx
    j = start_idx + 1
    while j < limit:
        line = lines[j]
        if not _is_boundary(line):
            j += 1
            continue
        if _indent(line) <= indent:
            break
        end = j
        j += 1
    return end


def _top_level_sections(lines: list[str]) -> "dict[str, tuple[int, int]]":
    """Map every top-level (indent-0) key to its 1-based inclusive line range."""
    sections: dict[str, tuple[int, int]] = {}
    n = len(lines)
    for i, line in enumerate(lines):
        match = _KEY_RE.match(line)
        if match is None or match.group("indent"):
            continue
        end = _block_end(lines, i, 0, n)
        sections[match.group("key")] = (i + 1, end + 1)
    return sections


def _child_keys(
    lines: list[str], parent_range: "tuple[int, int]", child_indent: int
) -> "list[tuple[str, int, int]]":
    """Find keys at exactly ``child_indent`` inside a parent's line range.

    ``parent_range`` is 1-based inclusive. Returns ``(key, start, end)`` triples
    with 1-based inclusive ranges, in source order.
    """
    start_1b, end_1b = parent_range
    limit = end_1b  # exclusive 0-based == inclusive 1-based end
    results: list[tuple[str, int, int]] = []
    for i in range(start_1b, end_1b):  # skip the parent key line itself
        line = lines[i]
        match = _KEY_RE.match(line)
        if match is None or len(match.group("indent")) != child_indent:
            continue
        block_end = _block_end(lines, i, child_indent, limit)
        results.append((match.group("key"), i + 1, block_end + 1))
    return results


def _find_child_value(
    lines: list[str], block_range: "tuple[int, int]", child_indent: int, key: str
) -> Optional[str]:
    """Return the inline scalar value of ``key`` at ``child_indent`` in a block."""
    start_1b, end_1b = block_range
    pattern = re.compile(rf"^\s{{{child_indent}}}{re.escape(key)}:\s*(?P<val>.*)$")
    for i in range(start_1b, end_1b):
        match = pattern.match(lines[i])
        if match is not None:
            return match.group("val").strip()
    return None


def _named_range(
    children: "list[tuple[str, int, int]]", key: str
) -> "Optional[tuple[int, int]]":
    """Return the (start, end) range of the named child from ``_child_keys``."""
    for name, start, end in children:
        if name == key:
            return (start, end)
    return None


# ---------------------------------------------------------------------------
# Value cleaning / summarising
# ---------------------------------------------------------------------------


def _unquote(value: str) -> str:
    """Strip one layer of surrounding single/double quotes if present."""
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def _summarize(text: str, limit: int = _SUMMARY_LIMIT) -> str:
    """First sentence of ``text``, collapsed to one line and capped at ``limit``."""
    text = " ".join(_unquote(text).split())
    dot = text.find(". ")
    if 0 < dot < limit:
        return text[:dot]
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Per-doc symbol extractors
# ---------------------------------------------------------------------------


def _bounded_context_map(
    lines: list[str], sections: "dict[str, tuple[int, int]]"
) -> "dict[str, str]":
    """Reverse map entity name -> owning bounded_context family (best-effort)."""
    result: dict[str, str] = {}
    bc_range = sections.get("bounded_contexts")
    if bc_range is None:
        return result
    for family, fam_start, fam_end in _child_keys(lines, bc_range, 2):
        ent_val = _find_child_value(lines, (fam_start, fam_end), 4, "entities")
        if ent_val is None:
            continue
        names: list[str] = []
        if ent_val.startswith("["):
            buf = ent_val
            k = fam_start
            while "]" not in buf and k < fam_end:
                buf += " " + lines[k].strip()
                k += 1
            inner = buf[buf.find("[") + 1 : buf.rfind("]")] if "]" in buf else buf[1:]
            names = [p.strip() for p in inner.split(",") if p.strip()]
        else:
            for i in range(fam_start, fam_end):
                item = lines[i].strip()
                if item.startswith("- "):
                    names.append(item[2:].strip())
        for name in names:
            result.setdefault(name, family)
    return result


def _extract_entities(
    lines: list[str], sections: "dict[str, tuple[int, int]]", filename: str
) -> "list[SymbolSlice]":
    """Index every entity under the top-level ``entities:`` block."""
    ent_range = sections.get("entities")
    if ent_range is None:
        return []
    context_of = _bounded_context_map(lines, sections)
    out: list[SymbolSlice] = []
    for name, start, end in _child_keys(lines, ent_range, 2):
        category = _find_child_value(lines, (start, end), 4, "category") or "entity"
        description = _find_child_value(lines, (start, end), 4, "description")
        summary = _summarize(description) if description else ""
        out.append(
            SymbolSlice(
                file=filename,
                path=f"entities.{name}",
                start=start,
                end=end,
                kind=category.strip(),
                context=context_of.get(name),
                summary=summary,
            )
        )
    return out


def _extract_enums(
    lines: list[str], sections: "dict[str, tuple[int, int]]", filename: str
) -> "list[SymbolSlice]":
    """Index every named enum under ``enums_and_lookups.enums``."""
    root = sections.get("enums_and_lookups")
    if root is None:
        return []
    enums_range = _named_range(_child_keys(lines, root, 2), "enums")
    if enums_range is None:
        return []
    out: list[SymbolSlice] = []
    for name, start, end in _child_keys(lines, enums_range, 4):
        value = re.sub(r"\s+#.*$", "", lines[start - 1].split(":", 1)[1]).strip()
        if not value:
            members = [
                lines[i].strip()[2:].strip()
                for i in range(start, end)
                if lines[i].strip().startswith("- ")
            ]
            value = f"[{', '.join(members)}]" if members else ""
        out.append(
            SymbolSlice(
                file=filename,
                path=f"enums_and_lookups.enums.{name}",
                start=start,
                end=end,
                kind="enum",
                context=None,
                summary=_summarize(value) if value else "",
            )
        )
    return out


def _extract_frs(
    lines: list[str], sections: "dict[str, tuple[int, int]]", filename: str
) -> "list[SymbolSlice]":
    """Index FR-### list items under ``functional_requirements``."""
    fr_range = sections.get("functional_requirements")
    if fr_range is None:
        return []
    out: list[SymbolSlice] = []
    for sublist, sub_start, sub_end in _child_keys(lines, fr_range, 2):
        for i in range(sub_start, sub_end):
            match = _FR_ITEM_RE.match(lines[i])
            if match is None:
                continue
            item_end = _block_end(lines, i, _indent(lines[i]), sub_end)
            rest = match.group("rest").rstrip()
            quote = match.group("q")
            if quote and rest.endswith(quote):  # trim the matching closing quote
                rest = rest[:-1]
            out.append(
                SymbolSlice(
                    file=filename,
                    path=f"functional_requirements.{sublist}[{match.group('id')}]",
                    start=i + 1,
                    end=item_end + 1,
                    kind="functional_requirement",
                    context=sublist,
                    summary=_summarize(rest),
                )
            )
    return out


def _extract_dossiers(
    lines: list[str], sections: "dict[str, tuple[int, int]]", filename: str
) -> "list[SymbolSlice]":
    """Index per-stage dossiers under ``conventions.stage_dossiers.map`` (if any)."""
    conv = sections.get("conventions")
    if conv is None:
        return []
    sd_range = _named_range(_child_keys(lines, conv, 2), "stage_dossiers")
    if sd_range is None:
        return []
    map_range = _named_range(_child_keys(lines, sd_range, 4), "map")
    if map_range is None:
        return []
    out: list[SymbolSlice] = []
    for name, start, end in _child_keys(lines, map_range, 6):
        owning = _find_child_value(lines, (start, end), 8, "owning_fr")
        schema = _find_child_value(lines, (start, end), 8, "data_schema")
        bits = [
            b
            for b in (
                _unquote(owning) if owning else "",
                _unquote(schema) if schema else "",
            )
            if b
        ]
        out.append(
            SymbolSlice(
                file=filename,
                path=f"conventions.stage_dossiers.map.{name}",
                start=start,
                end=end,
                kind="stage_dossier",
                context=None,
                summary=_summarize(" — ".join(bits)) if bits else "",
            )
        )
    return out


# Which extractors run for which canonical file (keyed by base filename).
_EXTRACTORS = {
    "DATA-MODEL.yaml": (_extract_entities, _extract_enums),
    "PRD.yaml": (_extract_frs, _extract_dossiers),
}


# ---------------------------------------------------------------------------
# JSON canonicals (TASKS.json, CODE-MANIFEST.json)
# ---------------------------------------------------------------------------

# A task's stable id inside a pretty-printed task object.
_TSK_LINE_RE = re.compile(r'"task_id"\s*:\s*"(?P<id>[A-Z]+-\d+)"')
# A top-level JSON key line: ``  "key": ...`` (checked only at root depth).
_JSON_KEY_RE = re.compile(r'^\s*"(?P<key>[^"]+)"\s*:')
# A one-line title/name/summary member, used for the symbol summary.
_JSON_TITLE_RE = re.compile(r'"(?:title|name|summary)"\s*:\s*"(?P<val>[^"]*)"')


def _scan_json(lines: "list[str]") -> "tuple[dict[str, tuple[int, int]], list[SymbolSlice]]":
    """Line-range map for a pretty-printed JSON canonical (stdlib, no parse).

    Returns top-level-key sections plus one symbol per ``"task_id"`` object.
    Assumes the machine-written ``json.dump(indent=…)`` shape the skills emit:
    strings never span lines, and a task object's ``{`` opens on or before the
    line carrying its ``task_id`` member. Compact single-line objects are not
    symbol-indexed (their enclosing section still is). Best-effort by design —
    a malformed file yields empty results, never an exception.
    """
    sections: "dict[str, tuple[int, int]]" = {}
    symbols: "list[SymbolSlice]" = []
    stack: "list[dict]" = []  # frames: {"ch": "{"|"[", "line": int, "tid": str|None}
    current_key: "Optional[tuple[str, int]]" = None  # (key, start_line)

    def close_section(end_line: int) -> None:
        nonlocal current_key
        if current_key is not None:
            sections[current_key[0]] = (current_key[1], max(current_key[1], end_line))
            current_key = None

    for i, line in enumerate(lines, start=1):
        if len(stack) == 1 and stack[0]["ch"] == "{":
            key_match = _JSON_KEY_RE.match(line)
            if key_match is not None:
                close_section(i - 1)
                current_key = (key_match.group("key"), i)
        in_str = esc = False
        for ch in line:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append({"ch": ch, "line": i, "tid": None})
            elif ch in "}]":
                if not stack:
                    return {}, []  # malformed — bail out empty
                frame = stack.pop()
                if frame["ch"] == "{" and frame["tid"]:
                    summary = ""
                    for j in range(frame["line"] - 1, i):
                        title = _JSON_TITLE_RE.search(lines[j])
                        if title is not None:
                            summary = _summarize(title.group("val"))
                            break
                    symbols.append(
                        SymbolSlice(
                            file="",  # filled by the caller
                            path=f"tasks[{frame['tid']}]",
                            start=frame["line"],
                            end=i,
                            kind="task",
                            context=None,
                            summary=summary,
                        )
                    )
                if not stack:
                    close_section(i - 1)
        tsk_match = _TSK_LINE_RE.search(line)
        if tsk_match is not None:
            for frame in reversed(stack):
                if frame["ch"] == "{":
                    if frame["tid"] is None:
                        frame["tid"] = tsk_match.group("id")
                    break
    close_section(len(lines))
    symbols.sort(key=lambda s: s.start)
    return sections, symbols


# ---------------------------------------------------------------------------
# Index assembly
# ---------------------------------------------------------------------------


class DocIndex(NamedTuple):
    """The assembled navigation index, ready to render or query."""

    generated_from: "dict[str, dict[str, object]]"
    sections: "dict[str, dict[str, tuple[int, int]]]"
    symbols: "dict[str, SymbolSlice]"
    shards: "dict[str, list[str]]"


def build_index(docs_dir: Path) -> DocIndex:
    """Scan the canonical docs and assemble the navigation index.

    Files that do not parse or are absent are skipped so the generator never
    breaks an edit.
    """
    files = _discover_files(docs_dir)
    generated_from: dict[str, dict[str, object]] = {}
    sections: dict[str, dict[str, tuple[int, int]]] = {}
    symbols: dict[str, SymbolSlice] = {}

    for filename in files:
        path = docs_dir / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines()
        generated_from[filename] = {
            "sha256": sha256(text.encode("utf-8")).hexdigest(),
            "lines": len(lines),
        }
        if filename.endswith(".json"):
            file_sections, json_symbols = _scan_json(lines)
            sections[filename] = file_sections
            for sym in json_symbols:
                sym = sym._replace(file=filename)
                symbols[sym.file + ":" + sym.path] = sym
            continue
        file_sections = _top_level_sections(lines)
        sections[filename] = file_sections
        for extractor in _EXTRACTORS.get(filename, ()):
            for sym in extractor(lines, file_sections, filename):
                symbols[sym.file + ":" + sym.path] = sym  # temp key; re-keyed below

    ordered = sorted(
        symbols.values(),
        key=lambda s: (files.index(s.file), s.start),
    )
    named: dict[str, SymbolSlice] = {}
    for sym in ordered:
        named[_symbol_name(sym)] = sym
    return DocIndex(
        generated_from=generated_from,
        sections=sections,
        symbols=named,
        shards=_discover_shards(docs_dir),
    )


def _symbol_name(sym: SymbolSlice) -> str:
    """The lookup key an agent uses: entity/enum name, FR/TSK id, or dossier key."""
    bracketed = re.search(r"\[((?:FR|TSK)-\d+)\]$", sym.path)
    if bracketed is not None:
        return bracketed.group(1)
    return sym.path.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# YAML emission (controlled, schema-specific — not a general dumper)
# ---------------------------------------------------------------------------

_HEADER = (
    "# GENERATED by .claude/sdlc/docs_index.py — DO NOT HAND-EDIT.\n"
    "# Regenerated automatically by the Write|Edit PostToolUse hook on any\n"
    "# canonical docs/*.yaml or docs/TASKS*.json edit (shard edits refresh the\n"
    "# shards inventory). A pure location map (file + line range + one-line\n"
    "# summary) over the large SDLC artifacts; it duplicates NO field\n"
    "# bodies. Retrieval protocol: .claude/rules/sdlc-docs-access.md\n"
)

# Characters that force a scalar out of bare form inside a flow sequence.
_FLOW_UNSAFE = re.compile(r"""[\s,:\[\]{}#&*!|>'"%@`]""")


def _sq(value: object) -> str:
    """Render ``value`` as a single-quoted YAML scalar with minimal escaping."""
    text = " ".join(str(value).split())
    return "'" + text.replace("'", "''") + "'"


def _flow(value: str) -> str:
    """Bare scalar when safe in a flow sequence, else single-quoted."""
    return value if value and not _FLOW_UNSAFE.search(value) else _sq(value)


def render_index_yaml(index: DocIndex) -> str:
    """Serialize the index to deterministic, token-lean YAML."""
    out: list[str] = [_HEADER, "generated_from:"]
    for fname, meta in index.generated_from.items():
        sha = str(meta["sha256"])[:_SHA_LEN]
        out.append(f"  {fname}: {{sha256: {sha}, lines: {meta['lines']}}}")

    out.append("")
    out.append("sections:")
    for fname, secs in index.sections.items():
        out.append(f"  {fname}:")
        for key, (start, end) in secs.items():
            out.append(f"    {key}: [{start}, {end}]")

    if index.shards:
        out.append("")
        out.append("# shards: every docs/<PARENT>__<slug> sub-artifact present, keyed by")
        out.append("# its parent canonical. Shards load cheaply whole — no line ranges.")
        out.append("shards:")
        for parent, names in index.shards.items():
            out.append(f"  {parent}: [{', '.join(_flow(n) for n in names)}]")

    out.append("")
    out.append("# symbols: grouped by file. Each row is positional —")
    out.append("#   name: [start, end, kind, context, summary]")
    out.append("# Read only the [start, end] line range; never the whole source file.")
    out.append("# context is ~ (null) for enums and stage dossiers.")
    out.append("symbols:")
    by_file: dict[str, list[tuple[str, SymbolSlice]]] = {}
    for name, sym in index.symbols.items():
        by_file.setdefault(sym.file, []).append((name, sym))
    for fname in index.sections:  # canonical file order
        rows = by_file.get(fname)
        if not rows:
            continue
        out.append(f"  {fname}:")
        for name, sym in rows:
            context = _flow(sym.context) if sym.context else "~"
            out.append(
                f"    {name}: [{sym.start}, {sym.end}, {_flow(sym.kind)}, "
                f"{context}, {_sq(sym.summary)}]"
            )

    return "\n".join(out) + "\n"


def write_index(docs_dir: Path) -> Path:
    """Build the index and write ``docs/INDEX.yaml``. Returns the written path."""
    index = build_index(docs_dir)
    target = docs_dir / INDEX_FILENAME
    target.write_text(render_index_yaml(index), encoding="utf-8")
    return target


def find_symbol_slice(
    docs_dir: Path, name: str
) -> "Optional[tuple[Path, int, int]]":
    """Resolve a symbol name to ``(file_path, start, end)`` via a fresh scan."""
    index = build_index(docs_dir)
    sym = index.symbols.get(name)
    if sym is None:
        return None
    return docs_dir / sym.file, sym.start, sym.end


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_docs_dir(args: argparse.Namespace) -> Path:
    if args.docs_dir:
        return Path(args.docs_dir)
    root = args.project_root or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    return Path(root) / "docs"


def _edited_path_from_stdin() -> Optional[str]:
    """Read the PostToolUse JSON event from stdin and pull out the file path.

    Tolerant of schema variation: tries ``tool_input.file_path`` /
    ``tool_input.path`` and the top-level fallbacks. Returns None on empty or
    unparseable input (manual ``--hook`` invocation), which the caller treats
    as "nothing relevant changed".
    """
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw.strip():
        return None
    try:
        event = json.loads(raw)
    except (ValueError, TypeError):
        return None
    ti = event.get("tool_input") or {}
    for key in ("file_path", "path", "filePath"):
        val = ti.get(key) or event.get(key)
        if val:
            return str(val)
    return None


def _path_is_relevant(file_path: str) -> bool:
    """True if ``file_path``'s edit should trigger a regen.

    Canonical docs move line ranges; shard writes (``UX__x.yaml``,
    ``TASKS__cid.json``) change the ``shards:`` inventory. Both refresh.
    """
    p = Path(file_path)
    return "docs" in p.parts and (_is_canonical(p.name) or _is_shard(p.name))


def _force_utf8_stdio() -> None:
    """Best-effort: keep prints working on a non-UTF-8 console (e.g. Windows cp1252).

    ``--show`` streams raw doc text (em-dashes, arrows), which would otherwise
    crash on a cp1252 console.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: "Optional[list[str]]" = None) -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser(description="SDLC docs/INDEX.yaml generator.")
    ap.add_argument("--docs-dir", help="Path to the docs directory (default: <root>/docs).")
    ap.add_argument("--project-root", help="Project root (default: $CLAUDE_PROJECT_DIR or cwd).")
    ap.add_argument("--hook", action="store_true", help="PostToolUse mode: read the event from stdin and regenerate only when a canonical doc changed.")
    ap.add_argument("--show", metavar="SYMBOL", help="Print one symbol's [start,end] line slice and exit.")
    args = ap.parse_args(argv)

    docs_dir = _resolve_docs_dir(args)

    if args.show:
        hit = find_symbol_slice(docs_dir, args.show)
        if hit is None:
            print(f"[docs-show] symbol not found: {args.show}", file=sys.stderr)
            return 1
        path, start, end = hit
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            print(f"[docs-show] cannot read {path}: {e}", file=sys.stderr)
            return 2
        print(f"# {path}:{start}-{end}")
        sys.stdout.write("\n".join(lines[start - 1 : end]) + "\n")
        return 0

    if args.hook:
        edited = _edited_path_from_stdin()
        if edited is None or not _path_is_relevant(edited):
            return 0  # unrelated edit (or no event) — silent no-op
        # Resolve docs dir from the edited path itself when not pinned, so the
        # hook works regardless of cwd.
        if not args.docs_dir and not args.project_root:
            parts = Path(edited).parts
            docs_dir = Path(*parts[: parts.index("docs") + 1])

    if not docs_dir.is_dir():
        # Nothing to index yet (docs/ not created) — not an error.
        return 0
    target = write_index(docs_dir)
    if not args.hook:
        print(f"[docs-index] wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

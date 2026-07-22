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
``Write|Edit|MultiEdit`` PostToolUse hook (installed by the ``sdlc:setup`` skill)
keeps those current. Beyond the location map it also emits a cross-reference
graph (``referenced_by`` + ``dangling``) so an agent can look up a symbol's edit
blast-radius and gate on id integrity (``--check``). The retrieval protocol
agents follow lives in ``.claude/rules/sdlc-docs-access.md``.

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
                                             #   (entity / enum / convention name,
                                             #   FR/NFR/WKF/SCR/… id, TSK-### id, or
                                             #   a stage_dossiers map key)
    python docs_index.py --refs <symbol>     # print a symbol's edit blast-radius
    python docs_index.py --check             # exit non-zero on any dangling ref
    python docs_index.py --find kind=… …     # predicate search over symbols

Project root is resolved from ``--project-root``, then ``$CLAUDE_PROJECT_DIR``,
then the current working directory. ``docs/`` is taken relative to that root
unless ``--docs-dir`` is given explicitly.

Capability version: 2 (adds the cross-reference graph — ``referenced_by`` +
``dangling`` — the extra symbol families NFR/WKF/INT/AIF/SCR + ``conventions.*``,
and the ``--refs`` / ``--check`` / ``--find`` subcommands over the v1 location
map). Re-run ``/sdlc:setup`` to upgrade an installed v1 copy.
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

# ---------------------------------------------------------------------------
# Cross-reference (edge) vocabulary — the id-integrity half of the index.
# ---------------------------------------------------------------------------
#
# ID families *defined* somewhere in the canonical SDLC docs — the only prefixes
# the dangling-reference check resolves. Every other XX-### token (downstream
# generated-app families like TST/TSK/CMP/OPR/CFG, or external standards like
# ISO-8601) is a forward/illustrative reference, NOT a corpus symbol: mentions
# of those are ignored and never flagged dangling. ``stage_NN`` is a special
# form handled alongside. (Ported from the AICF navigation fork, SK-01/SK-29.)
_CORPUS_PREFIXES: "tuple[str, ...]" = (
    "FR", "NFR", "ENT", "INT", "AIF", "PER", "GOL", "PAN",
    "WKF", "JTB", "EDG", "OOS", "SCR", "ACR", "WRN",
)

# A reference token: an uppercase corpus-prefix id (``FR-083``) or ``stage_NN``.
# Case-sensitive on purpose — ids are uppercase, so prose like "per-stage" or
# "integration" never matches "PER-"/"INT-".
_REF_RE = re.compile(r"\b(?:" + "|".join(_CORPUS_PREFIXES) + r")-\d+\b|\bstage_\d+\b")

# Corpus ids intentionally referenced without a definition — a number RESERVED
# or RETIRED and kept in a changelog for an honest audit trail, not a typo or a
# deleted symbol. Excluded from ``dangling`` so the ``--check`` gate stays green
# on an otherwise-clean corpus. Keep in sync with the PRD changelog. Empty by
# default in a fresh project; add a retired id here (with a sync comment) only
# when its changelog documents the retirement.
_ALLOWLISTED_IDS: "frozenset[str]" = frozenset()

# Definition anchors (line-start), one per shape:
#  - PRD list families + PRD/ARCH warnings:  ``- "FR-001: ...``  /  ``- "WRN-006: ...``
#  - UX surfaces:                            ``- id: SCR-001``
#  - PRD stage dossiers / inference profile: ``stage_00:`` (mapping key)
_DEF_LISTITEM_RE = re.compile(r'^\s*-\s*"?(?P<id>(?:' + "|".join(_CORPUS_PREFIXES) + r")-\d+):")
_DEF_SCR_RE = re.compile(r"^\s*-\s*id:\s*(?P<id>SCR-\d+)\b")
_DEF_STAGE_RE = re.compile(r"^\s*(?P<id>stage_\d+):(?:\s|$|\s*\{)")

# The PRD's other single-namespace id list items (NFR/WKF/INT/AIF/OOS/PER/…),
# defined as ``- "NFR-004: …"`` — the same anchored shape ``_scan_definitions``
# resolves — surfaced as addressable symbols so ``--show NFR-010`` resolves an
# id the dangling-checker already understands. FR is handled by ``_extract_frs``.
_SYMBOL_ITEM_PREFIXES = tuple(p for p in _CORPUS_PREFIXES if p not in ("FR", "WRN"))
_SYMBOL_ITEM_RE = re.compile(
    r'^\s*-\s*"?(?P<id>(?:' + "|".join(_SYMBOL_ITEM_PREFIXES) + r")-\d+):\s*(?P<rest>.*)")
_SYMBOL_ITEM_KINDS = {
    "NFR": "non_functional_requirement", "ENT": "entity_ref", "INT": "integration",
    "AIF": "ai_feature", "PER": "persona", "GOL": "user_goal", "PAN": "user_frustration",
    "WKF": "workflow", "JTB": "job_to_be_done", "EDG": "edge_case", "OOS": "out_of_scope",
    "SCR": "surface", "ACR": "acceptance_criterion",
}


class SymbolSlice(NamedTuple):
    """Location of a single addressable symbol within a canonical doc."""

    file: str
    path: str
    start: int  # 1-based, inclusive
    end: int  # 1-based, inclusive
    kind: str
    context: Optional[str]
    summary: str


class Reference(NamedTuple):
    """One mention of a corpus id at a line, attributed to its container symbol."""

    id: str
    file: str
    line: int  # 1-based
    container: str


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


def _named_range(children: "list[tuple[str, int, int]]", key: str) -> "Optional[tuple[int, int]]":
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


def _extract_convention_blocks(
    lines: list[str], sections: "dict[str, tuple[int, int]]", filename: str
) -> "list[SymbolSlice]":
    """Index each indent-2 sub-block of ``conventions`` as an addressable symbol.

    ``conventions`` is a long sequence of self-contained sub-blocks
    (``nfr_propagation``, ``artifact_ids``, ``stage_tool_inventory``, …). The
    named-symbol index otherwise reaches only FR-### and ``stage_NN``, so these
    were findable only by knowing they exist; surfacing each as a ``convention``
    symbol lets ``--show nfr_propagation`` resolve like any other symbol.
    ``context`` carries the block's ``owning_fr``; ``summary`` its
    ``description``/``purpose`` first sentence. ``_``-prefixed keys (navigational
    manifests) are skipped. (Ported from the AICF fork, SK-29.)
    """
    conv = sections.get("conventions")
    if conv is None:
        return []
    out: list[SymbolSlice] = []
    for name, start, end in _child_keys(lines, conv, 2):
        if name.startswith("_"):
            continue
        owning = _find_child_value(lines, (start, end), 4, "owning_fr")
        descr = _find_child_value(lines, (start, end), 4, "description") or _find_child_value(
            lines, (start, end), 4, "purpose"
        )
        out.append(
            SymbolSlice(
                file=filename,
                path=f"conventions.{name}",
                start=start,
                end=end,
                kind="convention",
                context=_unquote(owning) if owning else None,
                summary=_summarize(descr) if descr else "",
            )
        )
    return out


def _extract_prd_id_items(
    lines: list[str], sections: "dict[str, tuple[int, int]]", filename: str
) -> "list[SymbolSlice]":
    """Index the PRD's other single-namespace id list items (NFR/WKF/INT/AIF/…).

    These families are *defined* as ``- "NFR-004: …"`` list items — the same
    anchored shape :func:`_scan_definitions` resolves for the edge graph — but
    previously never became addressable symbols, so ``--show NFR-010`` could not
    resolve an id the dangling-checker fully understood. ``context`` is the
    narrowest enclosing mapping key (``core_workflows``, ``other``, …). FR items
    are handled by :func:`_extract_frs`. (Ported from the AICF fork, SK-29.)
    """
    containers: list[tuple[int, int, str]] = []
    path_of: dict[str, str] = {}
    for name, (start, end) in sections.items():
        containers.append((start, end, name))
        path_of[name] = name
        for child, c_start, c_end in _child_keys(lines, (start, end), 2):
            containers.append((c_start, c_end, child))
            path_of[child] = f"{name}.{child}"
    out: list[SymbolSlice] = []
    for i, line in enumerate(lines):
        match = _SYMBOL_ITEM_RE.match(line)
        if match is None:
            continue
        item_end = _block_end(lines, i, _indent(line), len(lines))
        container = _locate_container(containers, i + 1)
        parent_path = path_of.get(container or "", container) if container else filename
        out.append(
            SymbolSlice(
                file=filename,
                path=f"{parent_path}[{match.group('id')}]",
                start=i + 1,
                end=item_end + 1,
                kind=_SYMBOL_ITEM_KINDS.get(match.group("id").split("-", 1)[0], "id_item"),
                context=container,
                summary=_summarize(match.group("rest")),
            )
        )
    return out


def _extract_surfaces(
    lines: list[str], sections: "dict[str, tuple[int, int]]", filename: str
) -> "list[SymbolSlice]":
    """Index UX ``- id: SCR-NNN`` surface-inventory items as addressable symbols.

    UX declares surfaces as ``- id: SCR-001`` list items (the shape
    :func:`_scan_definitions` resolves via ``_DEF_SCR_RE``); surfacing each as a
    ``surface`` symbol lets ``--show SCR-001`` resolve and gives the edge graph a
    symbol container for references sitting inside a surface block. ``summary``
    is the surface's ``name``/``purpose`` if present. (SK-29 extension.)
    """
    out: list[SymbolSlice] = []
    for i, line in enumerate(lines):
        match = _DEF_SCR_RE.match(line)
        if match is None:
            continue
        item_end = _block_end(lines, i, _indent(line), len(lines))
        name = _find_child_value(lines, (i + 1, item_end + 1), _indent(line) + 2, "name")
        purpose = _find_child_value(lines, (i + 1, item_end + 1), _indent(line) + 2, "purpose")
        summary = _summarize(_unquote(name or purpose)) if (name or purpose) else ""
        out.append(
            SymbolSlice(
                file=filename,
                path=f"surfaces[{match.group('id')}]",
                start=i + 1,
                end=item_end + 1,
                kind="surface",
                context=None,
                summary=summary,
            )
        )
    return out


# Which extractors run for which canonical file (keyed by base filename).
_EXTRACTORS = {
    "DATA-MODEL.yaml": (_extract_entities, _extract_enums),
    "PRD.yaml": (
        _extract_frs,
        _extract_prd_id_items,
        _extract_dossiers,
        _extract_convention_blocks,
    ),
    "UX.yaml": (_extract_surfaces,),
}


# ---------------------------------------------------------------------------
# JSON canonicals (TASKS.json, CODE-MANIFEST.json)
# ---------------------------------------------------------------------------

# A task's stable id inside a pretty-printed task object. The SDLC task artifacts
# key this field ``tsk_id`` (TASKS.json + every TASKS__<cid>.json); it is the
# project-wide standard — do not look for a legacy ``task_id`` key.
_TSK_LINE_RE = re.compile(r'"tsk_id"\s*:\s*"(?P<id>[A-Z]+-\d+)"')
# A top-level JSON key line: ``  "key": ...`` (checked only at root depth).
_JSON_KEY_RE = re.compile(r'^\s*"(?P<key>[^"]+)"\s*:')
# A one-line title/name/summary member, used for the symbol summary.
_JSON_TITLE_RE = re.compile(r'"(?:title|name|summary)"\s*:\s*"(?P<val>[^"]*)"')


def _scan_json(lines: "list[str]") -> "tuple[dict[str, tuple[int, int]], list[SymbolSlice]]":
    """Line-range map for a pretty-printed JSON canonical (stdlib, no parse).

    Returns top-level-key sections plus one symbol per ``"tsk_id"`` object.
    Assumes the machine-written ``json.dump(indent=…)`` shape the skills emit:
    strings never span lines, and a task object's ``{`` opens on or before the
    line carrying its ``tsk_id`` member. Compact single-line objects are not
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
# Cross-reference graph (definitions, references, dangling)
# ---------------------------------------------------------------------------


def _id_sort_key(symbol_id: str) -> "tuple[str, int, str]":
    """Natural sort: ``FR-83`` -> ('FR', 83, ''), ``stage_00`` -> ('stage', 0, '')."""
    match = re.match(r"^([A-Za-z]+)[-_](\d+)$", symbol_id)
    if match is not None:
        return (match.group(1), int(match.group(2)), "")
    return (symbol_id, 0, symbol_id)


def _scan_definitions(lines: "list[str]") -> "dict[str, int]":
    """Map every corpus id *defined* in this file to its 1-based line number.

    A definition is matched by an anchored line shape (list item ``- "FR-001:``,
    UX ``- id: SCR-001``, or a bare ``stage_NN:`` mapping key) — never an inline
    mention — so a body that merely cites an id is not mistaken for its source.
    """
    found: dict[str, int] = {}
    for i, line in enumerate(lines):
        for pattern in (_DEF_LISTITEM_RE, _DEF_SCR_RE, _DEF_STAGE_RE):
            match = pattern.match(line)
            if match is not None:
                found.setdefault(match.group("id"), i + 1)
                break
    return found


def _container_ranges(
    lines: "list[str]",
    file_sections: "dict[str, tuple[int, int]]",
    file_symbols: "list[SymbolSlice]",
) -> "list[tuple[int, int, str]]":
    """Candidate containers for reference attribution (coarse to fine).

    Combines top-level sections, the indent-2 children of the large
    ``conventions`` section (so a hit resolves to ``artifact_ids`` rather than
    the whole ``conventions`` blob), and every extracted symbol. The narrowest
    covering range wins in :func:`_locate_container`.
    """
    ranges: list[tuple[int, int, str]] = [
        (start, end, name) for name, (start, end) in file_sections.items()
    ]
    conv = file_sections.get("conventions")
    if conv is not None:
        ranges.extend((start, end, name) for name, start, end in _child_keys(lines, conv, 2))
    ranges.extend((sym.start, sym.end, _symbol_name(sym)) for sym in file_symbols)
    return ranges


def _locate_container(ranges: "list[tuple[int, int, str]]", line: int) -> Optional[str]:
    """Return the narrowest container range covering ``line`` (1-based)."""
    best: Optional[str] = None
    best_width: Optional[int] = None
    for start, end, name in ranges:
        if start <= line <= end:
            width = end - start
            if best_width is None or width < best_width:
                best, best_width = name, width
    return best


def _build_edges(
    lines_by_file: "dict[str, list[str]]",
    sections: "dict[str, dict[str, tuple[int, int]]]",
    named_symbols: "dict[str, SymbolSlice]",
) -> "tuple[dict[str, tuple[str, int]], dict[str, list[str]], dict[str, list[str]], list[Reference]]":
    """Build the corpus reference graph from the scanned docs.

    Returns ``(definitions, referenced_by, references_out, dangling)``:
    ``definitions`` maps id -> ``(file, line)``; ``referenced_by`` maps a defined
    id -> the sorted containers that mention it; ``references_out`` maps a
    container -> the sorted defined ids it mentions; ``dangling`` lists references
    to corpus-family ids that resolve to no definition (a typo or deleted symbol).
    References are scanned over BOTH the YAML canonicals AND the JSON/TASKS docs,
    so a task whose ``implements`` names a deleted FR is caught (SK-01).
    """
    definitions: dict[str, tuple[str, int]] = {}
    for filename, lines in lines_by_file.items():
        for sym_id, lineno in _scan_definitions(lines).items():
            definitions.setdefault(sym_id, (filename, lineno))

    ranges_by_file: dict[str, list[tuple[int, int, str]]] = {
        filename: _container_ranges(
            lines,
            sections.get(filename, {}),
            [s for s in named_symbols.values() if s.file == filename],
        )
        for filename, lines in lines_by_file.items()
    }

    referenced_by: dict[str, set[str]] = {}
    references_out: dict[str, set[str]] = {}
    dangling: list[Reference] = []
    for filename, lines in lines_by_file.items():
        ranges = ranges_by_file[filename]
        for i, line in enumerate(lines):
            lineno = i + 1
            for match in _REF_RE.finditer(line):
                ref_id = match.group(0)
                if definitions.get(ref_id) == (filename, lineno):
                    continue  # the token sitting on its own definition line
                container = _locate_container(ranges, lineno) or filename
                if container == ref_id:
                    continue  # a symbol referencing itself
                if ref_id in definitions:
                    referenced_by.setdefault(ref_id, set()).add(container)
                    references_out.setdefault(container, set()).add(ref_id)
                elif ref_id not in _ALLOWLISTED_IDS:
                    dangling.append(Reference(ref_id, filename, lineno, container))

    return (
        definitions,
        {k: sorted(v, key=_id_sort_key) for k, v in referenced_by.items()},
        {k: sorted(v, key=_id_sort_key) for k, v in references_out.items()},
        sorted(set(dangling), key=lambda r: (_id_sort_key(r.id), r.file, r.line)),
    )


# ---------------------------------------------------------------------------
# Index assembly
# ---------------------------------------------------------------------------


class DocIndex(NamedTuple):
    """The assembled navigation index, ready to render or query."""

    generated_from: "dict[str, dict[str, object]]"
    sections: "dict[str, dict[str, tuple[int, int]]]"
    symbols: "dict[str, SymbolSlice]"
    shards: "dict[str, list[str]]"
    definitions: "dict[str, tuple[str, int]]"
    referenced_by: "dict[str, list[str]]"
    references_out: "dict[str, list[str]]"
    dangling: "list[Reference]"


def build_index(docs_dir: Path) -> DocIndex:
    """Scan the canonical docs and assemble the navigation index.

    Files that do not parse or are absent are skipped so the generator never
    breaks an edit.
    """
    files = _discover_files(docs_dir)
    generated_from: dict[str, dict[str, object]] = {}
    sections: dict[str, dict[str, tuple[int, int]]] = {}
    symbols: dict[str, SymbolSlice] = {}
    # Every scanned file's raw lines — fed to the reference-graph builder so the
    # dangling check and referenced_by span YAML canonicals AND JSON/TASKS docs.
    lines_by_file: dict[str, list[str]] = {}

    for filename in files:
        path = docs_dir / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines()
        lines_by_file[filename] = lines
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

    # TASKS__<cid>.json shards are large enough (100+ tasks) that "load whole"
    # is a lie. Per-task-symbol-index them so an agent can slice one task by its
    # qualified id (``<cid>/TSK-NNN`` — see ``_symbol_name``). Only their task
    # symbols are indexed, not their top-level sections; other shards
    # (UX__/ARCH__/API__) stay inventory-only, listed in ``shards:``.
    for p in sorted(docs_dir.glob("TASKS__*.json")):
        if not _is_shard(p.name):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        shard_lines = text.splitlines()
        lines_by_file[p.name] = shard_lines
        _shard_sections, json_symbols = _scan_json(shard_lines)
        for sym in json_symbols:
            sym = sym._replace(file=p.name)
            symbols[sym.file + ":" + sym.path] = sym

    def _file_rank(fname: str) -> int:
        try:
            return files.index(fname)  # canonical files keep their index order
        except ValueError:
            return len(files)  # shard files sort after every canonical

    ordered = sorted(
        symbols.values(),
        key=lambda s: (_file_rank(s.file), s.file, s.start),
    )
    named: dict[str, SymbolSlice] = {}
    for sym in ordered:
        named[_symbol_name(sym)] = sym

    definitions, referenced_by, references_out, dangling = _build_edges(
        lines_by_file, sections, named
    )
    return DocIndex(
        generated_from=generated_from,
        sections=sections,
        symbols=named,
        shards=_discover_shards(docs_dir),
        definitions=definitions,
        referenced_by=referenced_by,
        references_out=references_out,
        dangling=dangling,
    )


def _symbol_name(sym: SymbolSlice) -> str:
    """The lookup key an agent uses: entity/enum name, FR/TSK id, or dossier key.

    A task in a ``TASKS__<cid>.json`` shard is keyed by its **qualified** id
    ``<cid>/TSK-NNN`` — matching how sdlc-code (``topo_order.py``) addresses
    tasks and avoiding the cross-file ``TSK-001`` collision (every shard and the
    canonical file restart their numbering). A task in the canonical
    ``TASKS.json`` keeps its bare ``TSK-NNN``.
    """
    bracketed = re.search(r"\[((?:FR|TSK)-\d+)\]$", sym.path)
    if bracketed is not None:
        sym_id = bracketed.group(1)
        if sym_id.startswith("TSK-") and "__" in sym.file:
            cid = sym.file.split("__", 1)[1].rsplit(".", 1)[0]
            return f"{cid}/{sym_id}"
        return sym_id
    return sym.path.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# YAML emission (controlled, schema-specific — not a general dumper)
# ---------------------------------------------------------------------------

_HEADER = (
    "# GENERATED by .claude/sdlc/docs_index.py — DO NOT HAND-EDIT.\n"
    "# Regenerated automatically by the Write|Edit|MultiEdit PostToolUse hook on\n"
    "# any canonical docs/*.yaml or docs/TASKS*.json edit (shard edits refresh the\n"
    "# shards inventory). A location map (file + line range + one-line summary)\n"
    "# PLUS a cross-reference graph (referenced_by + dangling) over the large SDLC\n"
    "# artifacts; it duplicates NO field bodies. `docs_index.py --check` gates on\n"
    "# an empty dangling list. Retrieval protocol: .claude/rules/sdlc-docs-access.md\n"
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
        out.append("# its parent canonical. Most shards load cheaply whole; TASKS__<cid>.json")
        out.append("# shards are additionally per-task indexed under symbols: (<cid>/TSK-NNN).")
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
    # Canonical files first (in sections order), then any file that carries
    # symbols but no sections — the TASKS__<cid>.json shards (by_file preserves
    # the deterministic ordered() grouping for them).
    render_order = list(index.sections)
    render_order += [f for f in by_file if f not in index.sections]
    for fname in render_order:
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

    _render_edges(out, index)
    return "\n".join(out) + "\n"


def _render_edges(out: "list[str]", index: DocIndex) -> None:
    """Append the ``referenced_by`` (inbound blast-radius) and ``dangling`` blocks.

    ``referenced_by`` rows are grouped by the file that DEFINES each id; only
    defined ids with at least one inbound reference appear. ``dangling`` lists
    corpus-family references that resolve to no definition — an empty list when
    the corpus is clean (the state the ``--check`` gate requires).
    """
    out.append("")
    out.append("# referenced_by: inbound edge map — the edit blast-radius. For each")
    out.append("#   defined corpus id, the symbols/sections/tasks that mention it, grouped")
    out.append("#   by the doc that DEFINES the id. Consult before editing a symbol.")
    out.append("referenced_by:")
    by_def_file: dict[str, list[str]] = {}
    for ref_id in index.referenced_by:
        def_entry = index.definitions.get(ref_id)
        if def_entry is None:
            continue
        by_def_file.setdefault(def_entry[0], []).append(ref_id)
    render_order = list(index.sections)
    render_order += [f for f in by_def_file if f not in index.sections]
    for fname in render_order:
        ids = by_def_file.get(fname)
        if not ids:
            continue
        out.append(f"  {fname}:")
        for ref_id in sorted(ids, key=_id_sort_key):
            containers = ", ".join(_flow(c) for c in index.referenced_by[ref_id])
            out.append(f"    {ref_id}: [{containers}]")

    out.append("")
    out.append("# dangling: references whose id is a corpus family but resolves to no")
    out.append("#   definition (a typo or a deleted symbol). Empty when the corpus is clean;")
    out.append("#   `docs_index.py --check` exits non-zero when this list is non-empty.")
    if not index.dangling:
        out.append("dangling: []")
        return
    out.append("dangling:")
    for ref in index.dangling:
        out.append(f"  - {_sq(f'{ref.id} @ {ref.file}:{ref.line} (in {ref.container})')}")


def write_index(docs_dir: Path) -> Path:
    """Build the index and write ``docs/INDEX.yaml``. Returns the written path."""
    index = build_index(docs_dir)
    target = docs_dir / INDEX_FILENAME
    target.write_text(render_index_yaml(index), encoding="utf-8")
    return target


def find_symbol_slice(docs_dir: Path, name: str) -> "Optional[tuple[Path, int, int]]":
    """Resolve a symbol name to ``(file_path, start, end)`` via a fresh scan."""
    index = build_index(docs_dir)
    sym = index.symbols.get(name)
    if sym is None:
        return None
    return docs_dir / sym.file, sym.start, sym.end


def find_symbol_refs(
    docs_dir: Path, name: str
) -> "Optional[tuple[list[str], list[str], list[Reference]]]":
    """Resolve a symbol/id's 1-hop reference neighbourhood (the ``--refs`` query).

    Returns ``(references_out, referenced_by, dangling_within)``: the defined ids
    ``name`` mentions, the containers that mention ``name``, and any dangling
    references located inside ``name``'s line range. ``None`` when ``name`` is
    wholly unknown (not a symbol, a container, or a defined id).
    """
    index = build_index(docs_dir)
    known = name in index.symbols or name in index.definitions or any(
        name in cs for cs in index.referenced_by.values()
    ) or name in index.references_out
    if not known:
        return None
    out_refs = index.references_out.get(name, [])
    in_refs = index.referenced_by.get(name, [])
    within: list[Reference] = []
    sym = index.symbols.get(name)
    if sym is not None:
        within = [
            r for r in index.dangling
            if r.file == sym.file and sym.start <= r.line <= sym.end
        ]
    return out_refs, in_refs, within


def find_symbols(
    docs_dir: Path,
    *,
    kind: "Optional[str]" = None,
    context: "Optional[str]" = None,
    file: "Optional[str]" = None,
    text: "Optional[str]" = None,
    references: "Optional[str]" = None,
    referenced_by: "Optional[str]" = None,
) -> "list[tuple[str, SymbolSlice]]":
    """Predicate search over the symbol table (the ``--find`` query).

    Every supplied filter must match (AND semantics): ``kind``/``context``/``file``
    are exact (case-insensitive); ``text`` is a case-insensitive substring of the
    summary; ``references`` keeps symbols whose container mentions that id;
    ``referenced_by`` keeps the single defined id whose inbound set contains the
    named container. Returns ``(name, SymbolSlice)`` pairs in index order.
    """
    index = build_index(docs_dir)
    refs_out = index.references_out
    out: list[tuple[str, SymbolSlice]] = []
    for name, sym in index.symbols.items():
        if kind is not None and sym.kind.lower() != kind.lower():
            continue
        if context is not None and (sym.context or "").lower() != context.lower():
            continue
        if file is not None and sym.file.lower() != file.lower():
            continue
        if text is not None and text.lower() not in sym.summary.lower():
            continue
        if references is not None and references not in refs_out.get(name, []):
            continue
        if referenced_by is not None and name not in index.referenced_by.get(referenced_by, []):
            continue
        out.append((name, sym))
    return out


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
    ap.add_argument(
        "--hook",
        action="store_true",
        help="PostToolUse mode: read the event from stdin and regenerate only when a canonical doc changed.",
    )
    ap.add_argument(
        "--show", metavar="SYMBOL", help="Print one symbol's [start,end] line slice and exit."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Integrity gate: rebuild the index and exit non-zero if any reference is dangling.",
    )
    ap.add_argument(
        "--refs",
        metavar="SYMBOL",
        help="Print a symbol/id's blast-radius: outbound refs, inbound referenced_by, dangling within.",
    )
    ap.add_argument(
        "--find",
        nargs="+",
        metavar="FILTER",
        help="Predicate search over symbols. Filters: kind=, context=, file=, text=, references=, referenced_by=.",
    )
    args = ap.parse_args(argv)

    docs_dir = _resolve_docs_dir(args)

    if args.check:
        if not docs_dir.is_dir():
            print(f"[docs-check] no docs dir: {docs_dir}", file=sys.stderr)
            return 2
        index = build_index(docs_dir)
        if index.dangling:
            print(f"[docs-check] {len(index.dangling)} dangling reference(s):")
            for ref in index.dangling:
                print(f"  - {ref.id} @ {ref.file}:{ref.line} (in {ref.container})")
            return 1
        print("[docs-check] no dangling references.")
        return 0

    if args.refs:
        hit = find_symbol_refs(docs_dir, args.refs)
        if hit is None:
            print(f"[docs-refs] unknown symbol/id: {args.refs}", file=sys.stderr)
            return 1
        out_refs, in_refs, within = hit
        print(f"# refs for {args.refs}")
        print(f"references_out: [{', '.join(out_refs)}]")
        print(f"referenced_by: [{', '.join(in_refs)}]")
        if within:
            print("dangling_within:")
            for ref in within:
                print(f"  - {ref.id} @ {ref.file}:{ref.line}")
        return 0

    if args.find:
        filters: dict[str, str] = {}
        for tok in args.find:
            if "=" not in tok:
                print(f"[docs-find] bad filter (expected key=value): {tok}", file=sys.stderr)
                return 2
            key, val = tok.split("=", 1)
            key = key.strip()
            if key not in ("kind", "context", "file", "text", "references", "referenced_by"):
                print(f"[docs-find] unknown filter key: {key}", file=sys.stderr)
                return 2
            filters[key] = val.strip()
        matches = find_symbols(docs_dir, **filters)  # type: ignore[arg-type]
        for name, sym in matches:
            print(f"{name}\t{sym.file}:{sym.start}-{sym.end}\t{sym.kind}\t{sym.summary}")
        print(f"# {len(matches)} match(es)", file=sys.stderr)
        return 0

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

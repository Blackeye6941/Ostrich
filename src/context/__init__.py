"""
Context package exports.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Load context.json relative to project root or context dir
_CONTEXT_PATH = Path(__file__).resolve().parent.parent / "context.json"
if not _CONTEXT_PATH.exists():
    _CONTEXT_PATH = Path(__file__).resolve().parent / "context.json"

_CTX: dict = {}
if _CONTEXT_PATH.exists():
    with _CONTEXT_PATH.open(encoding="utf-8") as _f:
        _CTX = json.load(_f)

_ALIASES: dict[str, str] = _CTX.get("app_aliases", {})
_PATH_RULES: dict = _CTX.get("path_conventions", {})


def resolve_app_name(raw: str) -> str:
    """Normalise a human/model-supplied app name to the executable name."""
    normalised = raw.strip().lower()
    without_exe = re.sub(r"\.exe$", "", normalised)
    return _ALIASES.get(normalised) or _ALIASES.get(without_exe) or raw


def validate_path(path_str: str) -> tuple[bool, str]:
    """Check a Windows file path against the naming conventions in context.json."""
    forbidden: list[str] = _PATH_RULES.get("forbidden_chars", [])
    reserved: list[str] = _PATH_RULES.get("reserved_names", [])
    max_len: int = _PATH_RULES.get("max_path_length", 260)

    if len(path_str) > max_len:
        return False, f"Path exceeds Windows MAX_PATH ({max_len} chars)."

    check_str = path_str[2:] if len(path_str) > 2 and path_str[1] == ":" else path_str
    for ch in forbidden:
        if ch in check_str:
            return False, f"Path contains forbidden character: '{ch}'"

    parts = Path(path_str).parts
    for part in parts:
        stem = Path(part).stem.upper()
        if stem in reserved:
            return False, f"Path component '{part}' is a reserved Windows name."

    return True, "Path is valid."


from context.tree_pipeline import (
    INTERACTIVE_ROLES,
    SERIALIZE_STATES,
    SKIP_APPS,
    get_screen_bounds,
    count_nodes,
    count_forest,
    build_node,
    prune_visibility,
    prune_structure,
    prune_dedupe,
    prune_pipeline,
    serialize_tree,
    get_ui_context,
)
from context.pruning import (
    deterministic_prune,
    calculate_element_score,
)

__all__ = [
    "resolve_app_name",
    "validate_path",
    "INTERACTIVE_ROLES",
    "SERIALIZE_STATES",
    "SKIP_APPS",
    "get_screen_bounds",
    "count_nodes",
    "count_forest",
    "build_node",
    "prune_visibility",
    "prune_structure",
    "prune_dedupe",
    "prune_pipeline",
    "serialize_tree",
    "get_ui_context",
    "deterministic_prune",
    "calculate_element_score",
]

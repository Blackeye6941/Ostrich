"""
UI Context Tree Extraction and Deterministic Pruning Pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

# Interactive accessible roles
INTERACTIVE_ROLES: set[str] = {
    "push button",
    "toggle button",
    "menu",
    "menu item",
    "link",
    "check box",
    "radio button",
    "tab",
    "list item",
    "text",
    "entry",
    "password text",
    "combo box",
    "tree item",
    "terminal",
}

# States that should be serialized into human-readable prompts / logs
SERIALIZE_STATES: tuple[str, ...] = (
    "focused",
    "checked",
    "selected",
    "editable",
    "expanded",
    "sensitive",
)

SKIP_APPS: set[str] = {"gnome-shell"}

log = logging.getLogger("atspi")


def get_screen_bounds() -> tuple[int, int, int, int]:
    """Retrieve screen bounds (x, y, w, h) from Atspi desktop(0).

    Must ONLY be called on the AT-SPI thread.
    """
    try:
        from gi.repository import Atspi

        desktop = Atspi.get_desktop(0)
        if desktop:
            r = desktop.get_extents(Atspi.CoordType.SCREEN)
            if r and r.width > 0 and r.height > 0:
                return (r.x, r.y, r.width, r.height)
    except Exception as exc:
        log.warning("Failed to fetch screen extents from desktop: %s", exc)
    return (0, 0, 1920, 1080)


def count_nodes(node: dict | None) -> int:
    """Count total nodes in a subtree."""
    if not node:
        return 0
    count = 1
    for child in node.get("children", []):
        count += count_nodes(child)
    return count


def count_forest(nodes: list[dict]) -> int:
    """Count total nodes across a list of subtrees."""
    return sum(count_nodes(n) for n in nodes)


def build_node(
    acc: Any,
    path: tuple[int, ...],
    tracker: list[int],
    max_depth: int = 25,
    current_depth: int = 0,
    max_children: int = 50,
    node_cap: int = 1500,
) -> dict | None:
    """Recursively build a structured node dictionary from an Atspi.Accessible.

    Must ONLY be called on the AT-SPI thread.
    """
    if acc is None or current_depth > max_depth:
        return None

    if tracker[0] >= node_cap:
        if tracker[0] == node_cap:
            log.warning("Global node cap of %d reached during tree build", node_cap)
            tracker[0] += 1
        return None

    tracker[0] += 1

    try:
        from gi.repository import Atspi

        states = set()
        state_set = acc.get_state_set()
        if state_set:
            states = {s.value_nick for s in state_set.get_states()}

        role = acc.get_role_name() or "unknown"
        name = (acc.get_name() or "").strip()
        raw_desc = (acc.get_description() or "").strip()
        desc = "" if raw_desc == name else raw_desc

        bbox = (0, 0, 0, 0)
        bbox_is_screen = False
        try:
            r_screen = acc.get_extents(Atspi.CoordType.SCREEN)
            r_window = acc.get_extents(Atspi.CoordType.WINDOW)
            _INT_MIN = -2147483648

            # If SCREEN returns non-zero coords (and not INT_MIN), it is genuine screen coordinates.
            if (
                r_screen
                and r_screen.width > 0
                and r_screen.height > 0
                and (r_screen.x != 0 or r_screen.y != 0)
                and r_screen.x != _INT_MIN
                and r_screen.y != _INT_MIN
            ):
                bbox = (int(r_screen.x), int(r_screen.y), int(r_screen.width), int(r_screen.height))
                bbox_is_screen = True
            elif (
                r_window
                and r_window.width > 0
                and r_window.height > 0
                and r_window.x != _INT_MIN
                and r_window.y != _INT_MIN
            ):
                # When SCREEN is (0,0), GTK4 exposes real coords via WINDOW.
                # bbox is window-relative, so consumer must add win_x/win_y.
                bbox = (int(r_window.x), int(r_window.y), int(r_window.width), int(r_window.height))
                bbox_is_screen = False
            elif r_screen and r_screen.width > 0 and r_screen.height > 0:
                bbox = (int(r_screen.x), int(r_screen.y), int(r_screen.width), int(r_screen.height))
                bbox_is_screen = False
        except Exception:
            pass

        children = []
        child_count = 0
        try:
            child_count = acc.get_child_count()
        except Exception:
            pass

        limit = min(child_count, max_children)
        for i in range(limit):
            if tracker[0] >= node_cap:
                if tracker[0] == node_cap:
                    log.warning("Global node cap of %d reached during tree build", node_cap)
                    tracker[0] += 1
                break
            try:
                child = acc.get_child_at_index(i)
                if child:
                    child_node = build_node(
                        child,
                        path=path + (i,),
                        tracker=tracker,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                        max_children=max_children,
                        node_cap=node_cap,
                    )
                    if child_node is not None:
                        children.append(child_node)
            except Exception:
                continue

        return {
            "role": role,
            "name": name,
            "desc": desc,
            "states": states,
            "bbox": bbox,
            "bbox_is_screen": bbox_is_screen,
            "path": path,
            "children": children,
        }
    except Exception as exc:
        log.debug("Failed to build accessible node: %s", exc)
        return None


def prune_visibility(node: dict, screen_bounds: tuple[int, int, int, int]) -> list[dict]:
    """Rule 1: Drop invisible or off-screen nodes, returning surviving children if parent is dropped."""
    pruned_children = []
    for c in node.get("children", []):
        pruned_children.extend(prune_visibility(c, screen_bounds))
    node["children"] = pruned_children

    x, y, w, h = node.get("bbox", (0, 0, 0, 0))
    sx, sy, sw, sh = screen_bounds

    if w <= 0 or h <= 0:
        return pruned_children

    # Only apply screen-bounds clipping when the bbox is in screen coordinates.
    # Window-relative bboxes start from (0, 0) within the window and cannot be
    # compared against screen_bounds without the window offset, so we keep them.
    if node.get("bbox_is_screen", False):
        if x + w <= sx or x >= sx + sw or y + h <= sy or y >= sy + sh:
            return pruned_children

    return [node]


def prune_structure(node: dict) -> list[dict]:
    """Rules 2, 3, 4, 5: Showing state, collapsing wrappers, dropping empty leaves."""
    pruned_children = []
    for c in node.get("children", []):
        pruned_children.extend(prune_structure(c))
    node["children"] = pruned_children

    states = node.get("states", set())
    name = node.get("name", "")
    desc = node.get("desc", "")
    role = node.get("role", "unknown")
    is_interactive = role in INTERACTIVE_ROLES

    # Rule 2: drop leaf nodes that lack both 'showing' and 'visible'. Never drop container if it has surviving children.
    if not pruned_children:
        if "showing" not in states and "visible" not in states:
            return []

    # Rule 3: collapse wrappers: if no name, no desc, and role not in interactive set -> replace with pruned children
    if not name and not desc and not is_interactive:
        return pruned_children

    # Rule 4 & 5: drop empty leaves: unnamed, non-interactive leaves are removed.
    if not pruned_children:
        if not name and not is_interactive:
            return []

    return [node]


def prune_dedupe(nodes: list[dict]) -> list[dict]:
    """Rule 6: Dedupe repetitive siblings (>3 consecutive same role and name)."""
    for node in nodes:
        if node.get("children"):
            node["children"] = prune_dedupe(node["children"])

    result = []
    i = 0
    n = len(nodes)
    while i < n:
        j = i
        role = nodes[i].get("role", "")
        name = nodes[i].get("name", "")
        while j < n and nodes[j].get("role", "") == role and nodes[j].get("name", "") == name:
            j += 1

        count = j - i
        if count > 3:
            result.extend(nodes[i : i + 3])
            excess = count - 3
            marker = {
                "role": role,
                "name": f"+{excess} more",
                "desc": "",
                "states": set(),
                "bbox": (0, 0, 0, 0),
                "path": (),
                "children": [],
            }
            result.append(marker)
        else:
            result.extend(nodes[i:j])
        i = j

    return result


def prune_pipeline(
    root_node: dict,
    screen_bounds: tuple[int, int, int, int],
) -> tuple[list[dict], tuple[int, int, int, int]]:
    """Runs the full structural pruning pipeline and tracks counts for the funnel."""
    raw_count = count_nodes(root_node)

    vis_nodes = prune_visibility(root_node, screen_bounds)
    vis_count = count_forest(vis_nodes)

    col_nodes = []
    for n in vis_nodes:
        col_nodes.extend(prune_structure(n))
    col_count = count_forest(col_nodes)

    dedup_nodes = prune_dedupe(col_nodes)
    dedup_count = count_forest(dedup_nodes)

    funnel = (raw_count, vis_count, col_count, dedup_count)
    return dedup_nodes, funnel


def serialize_tree(forest: list[dict]) -> tuple[str, list[dict]]:
    """Walk pruned forest depth-first, assign sequential ids, and produce tree_str and flat nodes list."""
    current_id = 0
    lines = []
    nodes = []

    def walk(node: dict, parent_id: int | None, depth: int):
        nonlocal current_id
        current_id += 1
        node_id = current_id

        role = node.get("role", "unknown")
        name = node.get("name", "")
        desc = node.get("desc", "")
        states = node.get("states", set())
        bbox = node.get("bbox", (0, 0, 0, 0))
        bbox_is_screen = node.get("bbox_is_screen", False)
        path = node.get("path", ())

        active_states = [s for s in SERIALIZE_STATES if s in states]

        flat_node = {
            "id": node_id,
            "role": role,
            "name": name,
            "desc": desc,
            "bbox": bbox,
            "bbox_is_screen": bbox_is_screen,
            "states": active_states,
            "path": path,
            "parent_id": parent_id,
        }
        nodes.append(flat_node)

        indent = "  " * depth
        name_part = f" '{name}'" if name else ""
        x, y, w, h = bbox
        bbox_part = f" @({x},{y},{w}x{h})"
        states_part = f" states=[{','.join(active_states)}]" if active_states else ""

        lines.append(f"{indent}[{node_id}] {role}{name_part}{bbox_part}{states_part}")

        for child in node.get("children", []):
            walk(child, node_id, depth + 1)

    for root in forest:
        walk(root, None, 0)

    return "\n".join(lines), nodes


def get_ui_context(window_query: str | None = None) -> dict[str, Any] | None:
    """Retrieve UI context (pruned accessible node tree) for a target window or active window.

    Attempts live AT-SPI extraction first. If unavailable or no live match is found,
    checks for saved snapshots in src/context/*.json.
    """
    import json
    from pathlib import Path

    # 1. Try Live AT-SPI on Linux
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        Atspi.init()
        desktop = Atspi.get_desktop(0)
        screen_bounds = get_screen_bounds()

        if desktop:
            for i in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(i)
                if not app:
                    continue
                app_name = (app.get_name() or "").strip()
                if app_name.lower() in SKIP_APPS:
                    continue
                for j in range(app.get_child_count()):
                    win = app.get_child_at_index(j)
                    if not win:
                        continue
                    role = win.get_role_name() or ""
                    if role not in {"frame", "window", "dialog", "alert"}:
                        continue
                    title = (win.get_name() or "").strip()
                    if not title:
                        continue

                    match = False
                    if window_query is not None:
                        q = window_query.strip().lower()
                        match = (q in title.lower() or q in app_name.lower())
                    else:
                        try:
                            states = {s.value_nick for s in win.get_state_set().get_states()}
                            match = "active" in states
                        except Exception:
                            match = False

                    if match:
                        tracker = [0]
                        raw = build_node(win, path=(), tracker=tracker)
                        if raw:
                            forest, _ = prune_pipeline(raw, screen_bounds)
                            tree_str, nodes = serialize_tree(forest)
                            return {
                                "app": app_name,
                                "title": title,
                                "role": role,
                                "tree": tree_str,
                                "nodes": nodes,
                                "win_x": 0,
                                "win_y": 0,
                            }
    except Exception as exc:
        log.debug("Live AT-SPI context extraction failed: %s", exc)

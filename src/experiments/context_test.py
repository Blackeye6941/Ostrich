import logging
import os
import sys
import threading
import time

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

# Shared state between threads
active_window: dict | None = None
window_version: int = 0
window_lock = threading.Lock()
window_cond = threading.Condition(window_lock)
atspi_ready = threading.Event()
stop_event = threading.Event()

EVENT_TYPES = ("window:activate", "window:deactivate")

INTERACTIVE_ROLES = {
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

SERIALIZE_STATES = (
    "focused",
    "checked",
    "selected",
    "editable",
    "expanded",
    "sensitive",
)

SKIP_APPS = {"gnome-shell"}

logging.basicConfig(
    filename="atspi.log",
    level=logging.INFO,
    format="%(asctime)s %(threadName)s %(message)s",
)


def get_screen_bounds() -> tuple[int, int, int, int]:
    """Retrieve screen bounds (x, y, w, h) from desktop(0).

    Must ONLY be called on the AT-SPI thread.
    """
    try:
        desktop = Atspi.get_desktop(0)
        if desktop:
            r = desktop.get_extents(Atspi.CoordType.SCREEN)
            if r and r.width > 0 and r.height > 0:
                return (r.x, r.y, r.width, r.height)
    except Exception as exc:
        logging.warning("Failed to fetch screen extents from desktop: %s", exc)
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
    acc: Atspi.Accessible,
    path: tuple[int, ...],
    tracker: list[int],
    max_depth: int = 10,
    current_depth: int = 0,
    max_children: int = 50,
    node_cap: int = 1500,
) -> dict | None:
    """Recursively build a structured node dictionary.

    Must ONLY be called on the AT-SPI thread.
    """
    if acc is None or current_depth > max_depth:
        return None

    if tracker[0] >= node_cap:
        if tracker[0] == node_cap:
            logging.warning("Global node cap of %d reached during tree build", node_cap)
            tracker[0] += 1
        return None

    tracker[0] += 1

    try:
        states = set()
        state_set = acc.get_state_set()
        if state_set:
            states = {s.value_nick for s in state_set.get_states()}

        role = acc.get_role_name() or "unknown"
        name = (acc.get_name() or "").strip()
        raw_desc = (acc.get_description() or "").strip()
        desc = "" if raw_desc == name else raw_desc

        bbox = (0, 0, 0, 0)
        try:
            r = acc.get_extents(Atspi.CoordType.SCREEN)
            if r:
                bbox = (r.x, r.y, r.width, r.height)
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
                    logging.warning("Global node cap of %d reached during tree build", node_cap)
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
            "path": path,
            "children": children,
        }
    except Exception:
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


def prune_pipeline(root_node: dict, screen_bounds: tuple[int, int, int, int]) -> tuple[list[dict], tuple[int, int, int, int]]:
    """Runs the full pruning pipeline and tracks counts for the funnel."""
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
    """Walk pruned forest depth-first, assign sequential ids, and produce tree_str and nodes list."""
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
        path = node.get("path", ())

        active_states = [s for s in SERIALIZE_STATES if s in states]

        flat_node = {
            "id": node_id,
            "role": role,
            "name": name,
            "desc": desc,
            "bbox": bbox,
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


def _handle_event(event, *_):
    """Event listener callback running inside the atspi thread."""
    global active_window, window_version

    try:
        src = event.source
        app = src.get_application() if src else None
        event_kind = event.type
        info = {
            "kind": event_kind,
            "app": app.get_name() if app else None,
            "title": src.get_name() if src else None,
            "role": src.get_role_name() if src else None,
        }
    except Exception as exc:
        logging.warning("Failed to inspect event %s: %s", getattr(event, "type", "?"), exc)
        return

    tree_str = None
    nodes = []

    if event_kind == "window:activate":
        title = info.get("title") or ""
        app_name = (info.get("app") or "").strip().lower()

        # Skip non-app windows: empty title or desktop compositor/shell
        if not title.strip() or app_name in SKIP_APPS:
            logging.info("Skipping non-app window activation: app='%s', title='%s'", info.get("app"), info.get("title"))
            return

        try:
            screen_bounds = get_screen_bounds()
            tracker = [0]
            raw_tree = build_node(event.source, path=(), tracker=tracker)
            if raw_tree:
                pruned_forest, funnel = prune_pipeline(raw_tree, screen_bounds)
                logging.info(
                    "Funnel: raw nodes %d -> after visibility %d -> after collapse %d -> after dedupe %d",
                    funnel[0],
                    funnel[1],
                    funnel[2],
                    funnel[3],
                )
                tree_str, nodes = serialize_tree(pruned_forest)
            else:
                tree_str = ""
                nodes = []
            logging.info("Tree built for '%s' (%d nodes)", title, len(nodes))
        except Exception as exc:
            logging.exception("Failed to build accessible tree: %s", exc)
            tree_str = None
            nodes = []

    # Store plain data under window_lock
    with window_cond:
        if event_kind == "window:activate":
            window_version += 1
            active_window = {
                "kind": info.get("kind"),
                "app": info.get("app"),
                "title": info.get("title"),
                "role": info.get("role"),
                "tree": tree_str,
                "nodes": nodes,
                "version": window_version,
            }
            logging.info("Activated window (version %d): %s", window_version, active_window.get("title"))
            window_cond.notify_all()
        elif event_kind == "window:deactivate":
            current_app = active_window.get("app") if active_window else None
            current_title = active_window.get("title") if active_window else None
            ev_app = info.get("app")
            ev_title = info.get("title")

            if (
                active_window is not None
                and bool(ev_title)
                and ev_title == current_title
                and ev_app == current_app
            ):
                window_version += 1
                active_window = None
                logging.info("Deactivated window (version %d)", window_version)
                window_cond.notify_all()


def atspi_thread():
    """First thread: ONLY this thread executes Atspi calls."""
    listener = None
    loop = None
    try:
        listener = Atspi.EventListener.new(_handle_event)
        for t in EVENT_TYPES:
            listener.register(t)

        loop = GLib.MainLoop()

        def check_stop():
            if stop_event.is_set():
                loop.quit()
                return False
            return True

        GLib.timeout_add(200, check_stop)
        logging.info("AT-SPI listener started")
        atspi_ready.set()
        loop.run()
    except Exception:
        logging.exception("AT-SPI loop crashed")
    finally:
        atspi_ready.set()
        stop_event.set()
        with window_cond:
            window_cond.notify_all()
        if listener:
            for t in EVENT_TYPES:
                try:
                    listener.deregister(t)
                except Exception:
                    pass
        logging.info("AT-SPI listener stopped")


def agent_thread():
    """Second thread: agent execution thread.

    Never calls any Atspi.* methods. Waits for atspi_ready, copies active_window
    under the lock, releases it, and processes updates when version changes.
    """
    # Wait until the AT-SPI listener has initialized
    atspi_ready.wait()

    last_processed_version = -1

    while not stop_event.is_set():
        current_data = None

        with window_cond:
            # Wait for condition update or timeout to check stop_event
            while not stop_event.is_set() and window_version == last_processed_version:
                window_cond.wait(timeout=0.2)

            if stop_event.is_set():
                break

            if window_version != last_processed_version:
                current_data = dict(active_window) if active_window else None
                last_processed_version = window_version

        # Process outside of the lock
        if current_data is not None:
            nodes_count = len(current_data.get("nodes") or [])
            logging.info(
                "Processed window state version %d: %s (%d nodes)",
                last_processed_version,
                current_data.get("title"),
                nodes_count,
            )
            print(f"Active Window: {current_data.get('title')} (v{current_data.get('version')}) - {nodes_count} nodes")
            if current_data.get("tree"):
                print(current_data.get("tree"))

            # [HOOK]: Search and model stages plug in here with current_data['nodes']
            pass
        else:
            logging.info("No active window (version %d)", last_processed_version)

    stop_event.set()


if __name__ == "__main__":
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        print("ERROR: DBUS_SESSION_BUS_ADDRESS is not set. Accessibility bus unavailable. Exiting.", file=sys.stderr)
        sys.exit(1)

    try:
        Atspi.init()
    except Exception as exc:
        print(f"ERROR: Failed to initialize AT-SPI: %s" % exc, file=sys.stderr)
        sys.exit(1)

    t_atspi = threading.Thread(target=atspi_thread, name="atspi-writer", daemon=True)
    t_agent = threading.Thread(target=agent_thread, name="agent-runner")

    t_atspi.start()
    t_agent.start()

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping threads...")
        stop_event.set()
        with window_cond:
            window_cond.notify_all()

    t_agent.join(timeout=2.0)
    stop_event.set()
    print("Done")

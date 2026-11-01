import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

S, R = Atspi.StateType, Atspi.Role


def safe(fn, default=None):
    try:
        return fn()
    except GLib.Error:
        return default


def _roles(*names):
    # tolerate role names missing in older libatspi versions
    return {getattr(R, n) for n in names if hasattr(R, n)}


TOGGLE_ROLES = _roles(
    "TOGGLE_BUTTON",
    "CHECK_BOX",
    "RADIO_BUTTON",
    "SWITCH",
    "CHECK_MENU_ITEM",
    "RADIO_MENU_ITEM",
)
SCROLL_ROLES = _roles(
    "SCROLL_PANE",
    "LIST",
    "TREE",
    "TREE_TABLE",
    "TABLE",
    "DOCUMENT_WEB",
    "DOCUMENT_TEXT",
    "DOCUMENT_FRAME",
)


def _has_action(acc):
    iface = safe(lambda: acc.get_action_iface())
    return (
        iface is not None
        and (safe(lambda: Atspi.Action.get_n_actions(iface), 0) or 0) > 0
    )


def _matches(acc, ss, event_name):
    """Affordance filter. ss is the already-fetched state set."""
    enabled = ss.contains(S.ENABLED) or ss.contains(S.SENSITIVE)
    if event_name == "click":
        # selectable elements (tabs, list rows) are clicked even with no Action interface
        return enabled and (_has_action(acc) or ss.contains(S.SELECTABLE))
    if event_name == "toggle":
        return enabled and (
            ss.contains(S.CHECKABLE) or safe(acc.get_role) in TOGGLE_ROLES
        )
    if event_name == "select":
        return enabled and (ss.contains(S.SELECTABLE) or _has_action(acc))
    if event_name == "expand":
        return ss.contains(S.EXPANDABLE) and not ss.contains(S.EXPANDED)
    if event_name == "collapse":
        return ss.contains(S.EXPANDABLE) and ss.contains(S.EXPANDED)
    if event_name == "type":
        return enabled and ss.contains(S.EDITABLE)
    if event_name == "scroll":
        return safe(acc.get_role) in SCROLL_ROLES  # heuristic: no SCROLLABLE state exists
    if event_name == "focus":
        return ss.contains(S.FOCUSABLE)
    # None / "none" / unknown -> any interactive element
    return enabled and (_has_action(acc) or ss.contains(S.FOCUSABLE))


_generation = 0


def get_candidates(acc, event_name=None, depth=50, max_nodes=5000):
    """Return {"<id> | <path>": accessible} for showing elements that support event_name.
    id   = "<generation>:<n>", so an ID from an older snapshot is detectable as stale.
    path = names of named ancestors plus the element itself, joined by " > "."""
    global _generation
    _generation += 1
    gen = _generation
    n = 0  # running element number
    candidates = {}
    visited = 0

    def walk(node, level, path):
        nonlocal n, visited
        if level >= depth or visited >= max_nodes:
            return
        for i in range(safe(node.get_child_count, 0) or 0):
            if visited >= max_nodes:
                return
            child = safe(lambda: node.get_child_at_index(i))
            if child is None:
                continue
            visited += 1
            ss = safe(child.get_state_set)
            if ss is None or ss.contains(S.DEFUNCT) or not ss.contains(S.SHOWING):
                continue  # prune the hidden subtree
            n += 1
            cid = f"{gen}:{n}"
            name = safe(child.get_name, "") or ""
            role = safe(child.get_role_name, "") or ""
            label = f"{role}:{name}" if name else role
            child_path = f"{path} > {label}" if path else label
            if safe(lambda: _matches(child, ss, event_name), False):
                candidates[f"{cid} | {child_path}"] = child
            # unnamed wrappers stay out of the path (cheap compaction)
            walk(child, level + 1, child_path if name else path)

    walk(acc, 0, "")
    return candidates

def candidates_to_str(cands, include_states=False):
    lines = []
    for key, acc in cands.items():
        line = key
        if include_states:
            ss = safe(acc.get_state_set)
            if ss is not None:
                states = ",".join(sorted(s.value_nick for s in ss.get_states()
                                         if s.value_nick in KEEP_STATES))
                line += f" [{states}]"
        lines.append(line)
    return "\n".join(lines)

KEEP_STATES = {"checked", "pressed", "selected", "expanded", "collapsed",
               "expandable", "editable", "focused", "enabled"}

def find_active_window():
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = safe(lambda: desktop.get_child_at_index(i))
        if app is None:
            continue
        for j in range(safe(app.get_child_count, 0)):
            win = safe(lambda: app.get_child_at_index(j))
            if win and safe(
                lambda: win.get_state_set().contains(Atspi.StateType.ACTIVE), False
            ):
                return win
    return None

def describe(acc, coord_type=Atspi.CoordType.SCREEN):
    """Return a string like: ('Save', 'push button', (812, 64, 90, 32))
    Coordinates are (x, y, width, height). Falls back to None if the element
    has no Component interface or the read fails."""
    name = safe(acc.get_name, "") or ""
    role = safe(acc.get_role_name, "") or ""

    rect = safe(lambda: acc.get_extents(coord_type))   # Atspi.Accessible.get_extents (newer libatspi)
    if rect is None:
        comp = safe(acc.get_component_iface)
        rect = safe(lambda: Atspi.Component.get_extents(comp, coord_type)) if comp else None

    coords = (rect.x, rect.y, rect.width, rect.height) if rect else None
    return str((name, role, coords))




"""Why isn't the other terminal tab in the candidate list?

Walks the active window WITHOUT pruning and, for every element whose role contains
a fragment (default "page tab"), prints which filters would drop it.

    python -m ostrich.context.diag_drops            # page tabs
    python -m ostrich.context.diag_drops "tab"      # any role containing "tab"

Adjust the import if your helpers live elsewhere. Nothing is clicked.
"""
import sys

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

from ostrich.context import test as ctx  # find_active_window, get_candidates, _matches

S = Atspi.StateType


def safe(fn, default=None):
    try:
        return fn()
    except GLib.Error:
        return default
    except Exception:  # noqa: BLE001
        return default


def walk(node, depth, hidden_ancestor, out, cap=40, budget=[6000]):
    if depth >= cap or budget[0] <= 0:
        return
    for i in range(safe(node.get_child_count, 0) or 0):
        child = safe(lambda: node.get_child_at_index(i))
        if child is None:
            continue
        budget[0] -= 1
        ss = safe(child.get_state_set)
        showing = bool(ss and ss.contains(S.SHOWING))
        hid = hidden_ancestor
        if hid is None and not showing:
            hid = f"{safe(child.get_role_name, '?')}:{safe(child.get_name, '')}"
        out.append((child, depth, hidden_ancestor, ss))
        walk(child, depth + 1, hid, out, cap, budget)


def main():
    frag = (sys.argv[1] if len(sys.argv) > 1 else "page tab").lower()
    win = ctx.find_active_window()
    if win is None:
        print("no active window")
        return
    wbox = safe(lambda: win.get_extents(Atspi.CoordType.SCREEN))
    print("window:", safe(win.get_name, "?"), (wbox.x, wbox.y, wbox.width, wbox.height) if wbox else None)

    nodes = []
    walk(win, 0, None, nodes)
    hits = [n for n in nodes if frag in (safe(n[0].get_role_name, "") or "").lower()]
    print(f"{len(nodes)} nodes walked, {len(hits)} with role containing {frag!r}\n")

    for acc, depth, hidden_anc, ss in hits:
        name = safe(acc.get_name, "") or ""
        role = safe(acc.get_role_name, "")
        parent = safe(acc.get_parent)
        print(f"[{depth}] {role}: {name[:60]!r}   parent={safe(lambda: parent.get_role_name())}")
        if ss is None:
            print("    state set unreadable -> dropped (no states)")
            continue
        states = sorted(s.value_nick for s in ss.get_states())
        print("    states :", states)

        r = safe(lambda: acc.get_extents(Atspi.CoordType.SCREEN))
        box = (r.x, r.y, r.width, r.height) if r else None
        print("    extents:", box)

        iface = safe(acc.get_action_iface)
        n = (safe(lambda: Atspi.Action.get_n_actions(iface), 0) or 0) if iface else 0
        names = [safe(lambda i=i: Atspi.Action.get_action_name(iface, i)) for i in range(n)]
        print("    actions:", names)

        reasons = []
        if hidden_anc:
            reasons.append(f"pruned: ancestor not SHOWING ({hidden_anc})")
        if not ss.contains(S.SHOWING):
            reasons.append("not SHOWING")
        if not (ss.contains(S.ENABLED) or ss.contains(S.SENSITIVE)):
            reasons.append("not ENABLED/SENSITIVE")
        if box is None or box[2] <= 0 or box[3] <= 0:
            reasons.append("zero/unreadable extents (dropped by resolve_context)")
        for action in ("click", "select", "focus"):
            ok = safe(lambda a=action: ctx._matches(acc, ss, a), False)
            if not ok:
                reasons.append(f"fails affordance filter for {action!r}")
        print("    would be dropped:", reasons or "no")
        print()


if __name__ == "__main__":
    main()
import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi


class Node:
    def __init__(self, name, role, description, states, bbox, parent):
        self.name = name
        self.role = role
        self.description = description
        self.states = states
        self.bbox = bbox

        self.parent = parent


def get_bbox(node):
    try:
        r = node.get_extents(Atspi.CoordType.SCREEN)
        return {"x": r.x, "y": r.y, "width": r.width, "height": r.height}
    except Exception:
        return None


def get_states(node):
    try:
        ss = node.get_state_set()
        return [s.value_nick for s in ss.get_states()]
    except Exception:
        return []


def get_key(acc):
    try:
        return (acc.app.bus_name, acc.path)
    except Exception as e:
        return None


def create_node(acc):
    try:
        name = acc.get_name()
        role = acc.get_role_name()
        description = acc.get_description()
        states = get_states(acc)
        bbox = get_bbox(acc)

        parent = acc.get_parent()
        return Node(name, role, description, states, bbox, parent)
    except Exception:
        return None


def build_virtual_ui_tree():
    tree = dict()

    desktop = Atspi.get_desktop(0)

    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        key = get_key(app)
        node = create_node(app)

        tree[key] = node
    return tree

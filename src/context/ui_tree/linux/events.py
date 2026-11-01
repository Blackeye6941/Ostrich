import logging
import threading
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

import re
import subprocess

from context.tree_pipeline import (
    SKIP_APPS,
    get_screen_bounds,
    build_node,
    prune_pipeline,
    serialize_tree,
)

log = logging.getLogger("atspi")

EVENT_TYPES = ("window:activate", "window:deactivate", "object:state-changed:active")
WINDOW_ROLES = {"frame", "window", "dialog", "alert"}


def _get_window_screen_offset(title: str) -> tuple[int, int]:
    """Get the actual screen position (x, y) of a window by title via wmctrl.

    Returns (0, 0) if wmctrl is unavailable or the window is not found.
    Must ONLY be called on the AT-SPI thread.
    """
    try:
        r = subprocess.run(["wmctrl", "-l", "-G"], capture_output=True, text=True, timeout=2)
        for line in r.stdout.splitlines():
            if title and title.lower() in line.lower():
                parts = line.split()
                if len(parts) >= 5:
                    return int(parts[2]), int(parts[3])
    except Exception as exc:
        log.debug("wmctrl window offset lookup failed: %s", exc)
    return 0, 0


def _emit_deactivate(app_name: str, title: str, on_event):
    """Emit window:deactivate event."""
    on_event({
        "kind": "window:deactivate",
        "app": app_name,
        "title": title,
        "role": "frame",
        "tree": None,
        "nodes": [],
        "win_x": 0,
        "win_y": 0,
    })


def _process_and_emit(src, kind: str, on_event):
    """Build accessible tree for window and dispatch to on_event callback."""
    try:
        app = src.get_application() if src else None
        app_name = (app.get_name() or "").strip() if app else ""
        title = (src.get_name() or "").strip() if src else ""
        role = (src.get_role_name() or "").strip() if src else ""

        if not title or app_name.lower() in SKIP_APPS:
            return

        screen_bounds = get_screen_bounds()
        tracker = [0]
        raw_tree = build_node(src, path=(), tracker=tracker)
        if raw_tree:
            pruned_forest, funnel = prune_pipeline(raw_tree, screen_bounds)
            log.info(
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

        win_x, win_y = _get_window_screen_offset(title)
        log.info("Tree built for '%s' (%d nodes), window offset=(%d,%d)", title, len(nodes), win_x, win_y)

        event_data = {
            "kind": kind,
            "app": app_name,
            "title": title,
            "role": role,
            "tree": tree_str,
            "nodes": nodes,
            "win_x": win_x,
            "win_y": win_y,
        }
        on_event(event_data)
        return len(nodes)
    except Exception as exc:
        log.exception("Failed to build accessible tree: %s", exc)
        return 0


def run_atspi(on_event, stop: threading.Event | None = None):
    """Blocks until `stop` is set. on_event receives a plain dict.

    Builds, prunes, and serializes the accessible tree before passing to on_event.
    Listens to window events and continuously monitors desktop active windows.
    """
    Atspi.init()
    current_active_key = [None]
    current_node_count = [0]
    last_poll_time = [0.0]

    def handle(event, *_):
        src = getattr(event, "source", None)
        if not src:
            return

        ev_type = getattr(event, "type", "")
        role = ""
        try:
            role = src.get_role_name() or ""
        except Exception:
            pass

        app = None
        try:
            app = src.get_application()
        except Exception:
            pass
        app_name = (app.get_name() or "").strip() if app else ""
        title = ""
        try:
            title = (src.get_name() or "").strip()
        except Exception:
            pass

        if ev_type == "window:activate":
            current_active_key[0] = (app_name.lower(), title.lower())
            cnt = _process_and_emit(src, "window:activate", on_event)
            current_node_count[0] = cnt or 0
            last_poll_time[0] = time.time()

        elif ev_type == "window:deactivate":
            if current_active_key[0] == (app_name.lower(), title.lower()):
                current_active_key[0] = None
                current_node_count[0] = 0
            _emit_deactivate(app_name, title, on_event)

        elif ev_type == "object:state-changed:active":
            if role not in WINDOW_ROLES:
                return

            is_active = (getattr(event, "detail1", 0) == 1)
            try:
                state_set = src.get_state_set()
                if state_set:
                    is_active = "active" in {s.value_nick for s in state_set.get_states()}
            except Exception:
                pass

            if is_active:
                key = (app_name.lower(), title.lower())
                if current_active_key[0] != key:
                    current_active_key[0] = key
                    cnt = _process_and_emit(src, "window:activate", on_event)
                    current_node_count[0] = cnt or 0
                    last_poll_time[0] = time.time()
            else:
                if current_active_key[0] == (app_name.lower(), title.lower()):
                    current_active_key[0] = None
                    current_node_count[0] = 0
                _emit_deactivate(app_name, title, on_event)

    listener = Atspi.EventListener.new(handle)
    for t in EVENT_TYPES:
        try:
            listener.register(t)
        except Exception as exc:
            log.warning("Could not register AT-SPI event '%s': %s", t, exc)

    loop = GLib.MainLoop()

    def check_poll():
        if stop is not None and stop.is_set():
            loop.quit()
            return False

        # Active desktop poll to catch windows that opened without activate events
        try:
            desktop = Atspi.get_desktop(0)
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
                        if role not in WINDOW_ROLES:
                            continue
                        states = {s.value_nick for s in win.get_state_set().get_states()}
                        if "active" in states:
                            title = (win.get_name() or "").strip()
                            if not title:
                                continue
                            key = (app_name.lower(), title.lower())
                            now = time.time()
                            # Refresh if new window OR if captured early before child widgets loaded (< 10 nodes)
                            if key != current_active_key[0] or (current_node_count[0] < 10 and now - last_poll_time[0] >= 1.0):
                                current_active_key[0] = key
                                last_poll_time[0] = now
                                cnt = _process_and_emit(win, "window:activate", on_event)
                                current_node_count[0] = cnt or 0
                            return True
        except Exception as exc:
            log.debug("Active window polling error: %s", exc)

        return True

    GLib.timeout_add(300, check_poll)
    log.info("AT-SPI listener started")
    try:
        loop.run()
    finally:
        for t in EVENT_TYPES:
            try:
                listener.deregister(t)
            except Exception:
                pass
        log.info("AT-SPI listener stopped")

import logging
import os
import sys
import threading
import time

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

import needle

# Shared state between threads
active_window: dict | None = None
window_version: int = 0
window_lock = threading.Lock()
window_cond = threading.Condition(window_lock)
atspi_ready = threading.Event()
stop_event = threading.Event()

EVENT_TYPES = ("window:activate", "window:deactivate")

logging.basicConfig(
    filename="atspi.log",
    level=logging.INFO,
    format="%(asctime)s %(threadName)s %(message)s",
)


def accessible_to_string(
    acc: Atspi.Accessible,
    max_depth: int = 10,
    current_depth: int = 0,
    max_children: int = 50,
    filter_invisible: bool = True,
) -> str:
    """Construct a clean, hierarchical string representation of an AT-SPI Accessible tree.

    Must ONLY be called on the atspi thread.
    """
    if acc is None or current_depth > max_depth:
        return ""

    try:
        states = set()
        state_set = acc.get_state_set()
        if state_set:
            states = {s.value_nick for s in state_set.get_states()}

        if filter_invisible and ("visible" not in states and "showing" not in states):
            if current_depth > 0:
                return ""

        role = acc.get_role_name() or "unknown"
        name = (acc.get_name() or "").strip()
        description = (acc.get_description() or "").strip()

        bbox_str = ""
        try:
            r = acc.get_extents(Atspi.CoordType.SCREEN)
            if r and (r.width > 0 or r.height > 0):
                bbox_str = f" bbox=({r.x},{r.y},{r.width}x{r.height})"
        except Exception:
            pass

        details = [f"role='{role}'"]
        if name:
            details.append(f"name='{name}'")
        if description and description != name:
            details.append(f"desc='{description}'")
        if states:
            interesting_states = [
                s for s in ("focused", "checked", "selected", "editable", "sensitive", "expanded")
                if s in states
            ]
            if interesting_states:
                details.append(f"states=[{','.join(interesting_states)}]")

        indent = "  " * current_depth
        node_line = f"{indent}- {' '.join(details)}{bbox_str}"

        child_lines = []
        child_count = acc.get_child_count()
        limit = min(child_count, max_children)

        for i in range(limit):
            try:
                child = acc.get_child_at_index(i)
                if child:
                    child_str = accessible_to_string(
                        child,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                        max_children=max_children,
                        filter_invisible=filter_invisible,
                    )
                    if child_str:
                        child_lines.append(child_str)
            except Exception:
                continue

        if child_count > limit:
            child_lines.append(f"{'  ' * (current_depth + 1)}... ({child_count - limit} more children)")

        if child_lines:
            return "\n".join([node_line] + child_lines)
        return node_line

    except Exception as exc:
        return f"{'  ' * current_depth}- [Error reading accessible: {exc}]"


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

    # If activated, build the accessible tree BEFORE taking the lock
    tree_str = ""
    if event_kind == "window:activate":
        try:
            tree_str = accessible_to_string(event.source)
        except Exception as exc:
            logging.warning("Failed to build accessible tree: %exc", exc)
            tree_str = f"[Failed to build tree: {exc}]"

    # Store plain data under window_lock
    with window_cond:
        if event_kind == "window:activate":
            window_version += 1
            active_window = dict(info, tree=tree_str, version=window_version)
            logging.info("Activated window (version %d): %s", window_version, active_window.get("title"))
            window_cond.notify_all()
        elif active_window and active_window.get("title") == info.get("title"):
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
            logging.info("Processing new window state version %d: %s", last_processed_version, current_data.get("title"))
            # print(f"Active Window: {current_data.get('title')} (v{current_data.get('version')})")
            # print(current_data.get("tree"))

            # TODO: Add your model reasoning/execution logic here
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
        print(f"ERROR: Failed to initialize AT-SPI: {exc}", file=sys.stderr)
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

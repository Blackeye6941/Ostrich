import threading
import logging
import time
from collections import deque

from context.ui_tree.linux.events import run_atspi

active_window = None
window_history = deque(maxlen=500)   # oldest entries drop off automatically
window_lock = threading.Lock()       # one lock guards BOTH variables
stop_event = threading.Event()

logging.basicConfig(
    filename="atspi.log",
    level=logging.INFO,
    format="%(asctime)s %(threadName)s %(message)s",
)


def _record(state):
    """Append a state change to history. Caller must already hold window_lock."""
    window_history.append({"time": time.time(), "window": state})


def on_event(info):
    """Writer side: runs for every AT-SPI event."""
    global active_window
    with window_lock:
        if info["kind"] == "window:activate": 
            active_window = dict(info)        # copy so later mutation can't alter history
            _record(active_window)
            logging.info(f"{active_window}")
        elif active_window and active_window["title"] == info["title"]:
            active_window = None              # lost focus
            _record(None)                     # None = "no active window" at this moment


def writer():
    try:
        run_atspi(on_event)
    except Exception:
        logging.exception("AT-SPI loop crashed")
    finally:
        stop_event.set()


def format_entry(entry):
    ts = time.strftime("%H:%M:%S", time.localtime(entry["time"]))
    w = entry["window"]
    return f"[{ts}] {w['title'] if w else '(no active window)'}"


def reader():
    prompt = "Show? [c = current / h = history / q = quit]: "
    while not stop_event.is_set():
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            break

        if answer in ("c", "current"):
            with window_lock:
                snapshot = active_window
            print(snapshot if snapshot else "No active window right now.")

        elif answer in ("h", "history"):
            with window_lock:
                snapshot = list(window_history)   # copy, then release the lock
            if not snapshot:
                print("History is empty.")
            for entry in snapshot:                # print outside the lock
                print(format_entry(entry))

        elif answer in ("q", "quit"):
            break

    stop_event.set()


if __name__ == "__main__":
    threading.Thread(target=writer, name="writer", daemon=True).start()
    reader_thread = threading.Thread(target=reader, name="reader")
    reader_thread.start()
    reader_thread.join()
    print("Bye")
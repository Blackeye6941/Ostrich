"""
Integrated Experiment: Open Settings & Click Buttons with Action Execution.

Demonstrates the complete end-to-end flow:
1. Launches GNOME Settings using open_app via the system executor.
2. Background AT-SPI event listener catches the window activation and builds the UI context tree.
3. Multi-threaded agent worker receives instructions:
   - "click on Wi-Fi button"
   - "click on Bluetooth button"
   - "click on Sound button"
   - "click on Power button"
4. Agent 1 prunes context and selects the target UI element.
5. Agent 2 uses Needle to determine the function (mouse_click) and grounded coordinates.
6. ActionExecutor executes the action (with dry_run option).
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time

from context.ui_tree.linux.events import run_atspi
from models.model import load_needle_model
from agents.coordinator import run_agent_worker
from agents.executor import ActionExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(message)s",
)

log = logging.getLogger("integrated_experiment")

# Shared state between AT-SPI listener and Agent thread
_lock = threading.Lock()
active_window: dict | None = None
window_updated = threading.Event()
stop_event = threading.Event()

task_queue: queue.Queue = queue.Queue()
result_queue: queue.Queue = queue.Queue()


def get_active_window() -> dict | None:
    """Thread-safe snapshot reader of active_window."""
    with _lock:
        if active_window is None:
            return None
        return dict(active_window)


def on_event(info: dict):
    """Event callback invoked by run_atspi on window state changes."""
    global active_window
    kind = info.get("kind")
    title = info.get("title") or ""
    with _lock:
        if kind == "window:activate":
            active_window = dict(info)
            window_updated.set()
            log.info("AT-SPI: Window activated -> '%s' (%d UI nodes)", title, len(info.get("nodes") or []))
        elif kind == "window:deactivate":
            if (
                active_window
                and active_window.get("title") == title
                and active_window.get("app") == info.get("app")
            ):
                active_window = None
                log.info("AT-SPI: Window deactivated -> '%s'", title)


def run_experiment(dry_run: bool = False):
    print("==========================================================================")
    print("INTEGRATED EXPERIMENT: Open Settings & Click Buttons")
    print(f"Mode: {'DRY RUN (simulation)' if dry_run else 'LIVE EXECUTION'}")
    print("==========================================================================\n")

    needle_model = load_needle_model()

    # 1. Start AT-SPI listener thread (Thread 1)
    t_atspi = threading.Thread(
        target=run_atspi,
        args=(on_event, stop_event),
        name="atspi-thread",
        daemon=True,
    )
    t_atspi.start()
    log.info("Started AT-SPI listener thread")

    # 2. Start Agent worker thread (Thread 2)
    t_agent = threading.Thread(
        target=run_agent_worker,
        args=(
            get_active_window,
            task_queue,
            result_queue,
            stop_event,
            needle_model,
            True,     # execute_actions
            dry_run,  # dry_run
        ),
        name="agent-worker-thread",
    )
    t_agent.start()
    log.info("Started Agent worker thread")

    executor = ActionExecutor(dry_run=dry_run)

    try:
        # Step 1: Open GNOME Settings
        print("\n[Step 1] Instruction: 'open settings'")
        launch_res = executor.execute("open_app", {"app_name": "gnome-control-center"})
        print(f"  -> Launch result: {launch_res}")

        if not launch_res.get("success"):
            print("  -> ERROR: Could not launch gnome-control-center. Aborting.")
            return

        # Wait for AT-SPI event listener to capture Settings window activation.
        # We use the window_updated event for immediate notification, with a 15s deadline.
        print("\nWaiting for Settings window to activate (up to 15s)...")
        deadline = time.time() + 15.0
        captured_win = None
        switched_focus = False

        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            window_updated.wait(timeout=min(0.5, remaining))
            window_updated.clear()
            win = get_active_window()
            if (
                win
                and (
                    "settings" in (win.get("title") or "").lower()
                    or "control" in (win.get("app") or "").lower()
                )
                and win.get("nodes")
            ):
                captured_win = win
                # Once Settings has fully loaded its child widgets, we have >= 10 nodes
                if len(win.get("nodes", [])) >= 10:
                    break

            # If not captured after 2 seconds, explicitly bring window to focus
            if not switched_focus and (deadline - time.time()) < 13.0:
                switched_focus = True
                executor.execute("switch_window", {"title": "Settings"})

        if captured_win:
            print(
                f"Captured live active window: '{captured_win['title']}' "
                f"with {len(captured_win['nodes'])} UI nodes "
                f"(screen offset: win_x={captured_win.get('win_x', 0)}, win_y={captured_win.get('win_y', 0)})."
            )
        else:
            print(
                "WARNING: Settings window was not captured by AT-SPI within 15s.\n"
                "Falling back to preloaded static context for testing."
            )
            import json
            from pathlib import Path
            sample_path = Path(__file__).resolve().parent.parent / "context" / "settings_real_tree.json"
            if sample_path.exists():
                with sample_path.open(encoding="utf-8") as f:
                    with _lock:
                        global active_window
                        active_window = json.load(f)
                        active_window.setdefault("win_x", 0)
                        active_window.setdefault("win_y", 0)
                        for n in active_window.get("nodes", []):
                            n["bbox_is_screen"] = True
                print(f"Loaded {len(active_window.get('nodes', []))} nodes from fallback context.")
            else:
                print("  -> No fallback context file found either. Skipping click instructions.")
                return

        # Instructions to test
        instructions = [
            "click on Wi-Fi button",
            "click on Bluetooth button",
            "click on Sound button",
            "click on Power button",
        ]

        for idx, inst in enumerate(instructions, 1):
            print(f"\n[Step 2.{idx}] Instruction: '{inst}'")
            task_queue.put(inst)

            try:
                res = result_queue.get(timeout=15.0)
            except queue.Empty:
                print("  -> ERROR: Timeout waiting for agent response")
                continue

            elem = res.get("selected_element")
            fn = res.get("selected_function")
            args = res.get("arguments", {})
            execution = res.get("execution", {})

            elem_str = f"[{elem['id']}] {elem['role']} '{elem['name']}' @{elem['bbox']}" if elem else "None"
            print(f"  -> Agent 1 (UI Element) : {elem_str}")
            print(f"  -> Agent 2 (Function)   : {fn}")
            print(f"  -> Agent 2 (Arguments)  : {args}")
            print(f"  -> Executor Result      : {execution}")

            # Brief pause between clicks
            time.sleep(0.8)

    finally:
        # Cleanup
        print("\nCleaning up and stopping threads...")
        stop_event.set()
        task_queue.put(None)
        t_agent.join(timeout=2.0)
        t_atspi.join(timeout=2.0)

        # Close GNOME Settings process
        subprocess.run(["pkill", "-f", "gnome-control-center"], capture_output=True)
        print("Experiment completed cleanly.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run integrated settings automation experiment.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without actual mouse/OS clicks")
    args = parser.parse_args()

    run_experiment(dry_run=args.dry_run)

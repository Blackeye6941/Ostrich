# OstrichFlow UI Agent Demo

"""
Terminal UI demo: scripted voice-style commands checked against the real UI.

Run from the project root:

    python -m ostrich.agents.demo
    python -m ostrich.agents.demo --settle 2 --gap 3
    python -m ostrich.agents.demo --route-only
    python -m ostrich.agents.demo --commands my_commands.txt

How it works:
  - Each command goes through Agent._run() (classifier -> planner -> execution).
  - UI observers capture state before and after execution.
  - Assertions validate whether the expected UI change actually happened.
  - Commands without assertions are marked EXECUTED, not PASS.
  - Results are written to demo_results.txt.

Keep this terminal window focused and do not touch the mouse while it runs.
"""

import argparse
import sys
import time
import traceback

from dataclasses import dataclass
from typing import Callable, Optional, Any

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

from ostrich.agents.orchestrator import Agent
from ostrich.context.test import find_active_window, get_candidates


# ---------------------------------------------------------
# Test models
# ---------------------------------------------------------

ORD = [
    "first", "second", "third", "fourth",
    "fifth", "sixth", "seventh", "eighth"
]


@dataclass
class Step:
    command: str
    expect: str = ""

    # Captures the UI state before and after execution.
    observe: Optional[Callable[[], Any]] = None

    # Compares before and after states.
    check: Optional[Callable[[Any, Any], bool]] = None

    # Determines whether the test can execute.
    precondition: Optional[Callable[[Any], bool]] = None


@dataclass
class StepResult:
    number: int
    command: str
    status: str
    detail: str
    elapsed: float


# ---------------------------------------------------------
# UI observers
# ---------------------------------------------------------

def tab_state():
    """
    Count page tabs in the active window and identify
    the selected tab (1-based).
    """

    win = find_active_window()

    if win is None:
        return None

    try:
        tabs = [
            acc
            for acc in get_candidates(win, "select").values()
            if acc.get_role_name() == "page tab"
        ]

        selected = 0

        for i, acc in enumerate(tabs, 1):
            if acc.get_state_set().contains(
                Atspi.StateType.SELECTED
            ):
                selected = i

        return {
            "count": len(tabs),
            "selected": selected,
        }

    except Exception:
        return None


def window_state():
    """
    Capture the current active window state.

    This is a placeholder observer. Replace the implementation
    with your GNOME/AT-SPI window-state API.

    It should return something like:

        {
            "iconified": False,
            "maximized": True
        }
    """

    win = find_active_window()

    if win is None:
        return None

    try:
        state = win.get_state_set()

        return {
            "iconified": state.contains(
                Atspi.StateType.ICONIFIED
            ),
            "maximized": (
                state.contains(Atspi.StateType.MAXIMIZED)
                or state.contains(Atspi.StateType.MAXIMIZED_HORIZ)
                or state.contains(Atspi.StateType.MAXIMIZED_VERT)
            ),
        }

    except Exception:
        return None


# ---------------------------------------------------------
# Test definitions
# ---------------------------------------------------------

def build_steps(home):

    return [

        # Tab operations

        Step(
            command="create a new tab",
            expect="tab count increases by one",
            observe=tab_state,
            check=lambda before, after: (
                after["count"] == before["count"] + 1
            ),
        ),

        Step(
            command="switch to the first terminal tab",
            expect="first tab selected",
            observe=tab_state,
            precondition=lambda state: (
                state is not None and state["count"] >= 1
            ),
            check=lambda before, after: (
                after["selected"] == 1
            ),
        ),

        Step(
            command="switch to the second terminal tab",
            expect="second tab selected",
            observe=tab_state,
            precondition=lambda state: (
                state is not None and state["count"] >= 2
            ),
            check=lambda before, after: (
                after["selected"] == 2
            ),
        ),

        Step(
            command=f"switch to the {ORD[home - 1]} terminal tab",
            expect=f"back on tab {home}",
            observe=tab_state,
            precondition=lambda state: (
                state is not None and state["count"] >= home
            ),
            check=lambda before, after: (
                after["selected"] == home
            ),
        ),

        Step(
            command="minimize this terminal window",
            expect="window minimized",
            observe=window_state,
            check=lambda before, after: (
                not before["iconified"] and after["iconified"]
            ),
        ),
    ]


# ---------------------------------------------------------
# Step execution
# ---------------------------------------------------------

def run_step(agent, step, settle, route_only):

    before = None
    start_time = time.time()

    try:

        # Capture initial UI state.
        if step.observe:
            before = step.observe()

        # Check preconditions.
        if step.precondition:

            if not step.precondition(before):
                return (
                    "SKIP",
                    "Precondition not satisfied",
                    time.time() - start_time,
                )

        # Classification-only mode.
        if route_only:

            response = agent.routing(step.command)

            route = (
                "direct"
                if agent.state.direct
                else "planner"
            )

            return (
                "ROUTED",
                f"response={response} route={route} "
                f"action={agent.state.action}",
                time.time() - start_time,
            )

        # Execute the complete agent workflow.
        agent._run(step.command)

        elapsed = time.time() - start_time

        # No assertion configured.
        if not step.observe or not step.check:

            return (
                "EXECUTED",
                "Command executed; no UI verification configured",
                elapsed,
            )

        # Wait for UI and accessibility tree to settle.
        time.sleep(settle)

        # Capture final UI state.
        after = step.observe()

        if before is None or after is None:

            return (
                "NOCHECK",
                "Could not capture UI state",
                elapsed,
            )

        # Validate UI state.
        passed = step.check(before, after)

        status = "PASS" if passed else "FAIL"

        detail = (
            f"{step.expect} | "
            f"before={before} | after={after}"
        )

        return status, detail, elapsed

    except Exception as exc:

        traceback.print_exc()

        return (
            "ERROR",
            f"{type(exc).__name__}: {exc}",
            time.time() - start_time,
        )


# ---------------------------------------------------------
# Custom command loading
# ---------------------------------------------------------

def load_commands(path):

    with open(path, "r", encoding="utf-8") as fh:

        return [
            Step(command=line.strip())
            for line in fh
            if line.strip()
            and not line.lstrip().startswith("#")
        ]


# ---------------------------------------------------------
# Summary
# ---------------------------------------------------------

def print_summary(results, log_path):

    lines = [
        "",
        "=" * 80,
        "OSTRICHFLOW DEMO SUMMARY",
        "=" * 80,
    ]

    for result in results:

        lines.append(
            f"{result.number:02d}. "
            f"{result.status:9} "
            f"{result.command!r:45} "
            f"{result.detail} "
            f"[{result.elapsed:.2f}s]"
        )

    counts = {}

    for result in results:
        counts[result.status] = (
            counts.get(result.status, 0) + 1
        )

    lines.extend([
        "",
        "-" * 80,
        "RESULT COUNTS",
        "-" * 80,
    ])

    for status, count in sorted(counts.items()):
        lines.append(f"{status:12}: {count}")

    lines.append("=" * 80)

    summary = "\n".join(lines)

    print(summary)

    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(summary + "\n")

    print(f"\nResults written to: {log_path}")

    return counts


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--settle",
        type=float,
        default=1.5,
        help="Seconds to wait after each action before checking",
    )

    parser.add_argument(
        "--gap",
        type=float,
        default=2.0,
        help="Seconds between steps",
    )

    parser.add_argument(
        "--countdown",
        type=int,
        default=3,
        help="Seconds before the first step",
    )

    parser.add_argument(
        "--route-only",
        action="store_true",
        help="Classify commands without executing them",
    )

    parser.add_argument(
        "--commands",
        help="Text file containing one command per line",
    )

    parser.add_argument(
        "--log",
        default="demo_results.txt",
        help="Path to write the test summary",
    )

    args = parser.parse_args()

    # -----------------------------------------------------
    # Initial state
    # -----------------------------------------------------

    initial_state = tab_state()

    if initial_state is None and not args.commands:

        print(
            "Could not read active window tabs. "
            "Is AT-SPI enabled?"
        )

        sys.exit(1)

    home = (
        initial_state["selected"]
        if initial_state and initial_state["selected"]
        else 1
    )

    print(
        f"Starting state: "
        f"{initial_state['count'] if initial_state else '?'} tabs"
    )

    # -----------------------------------------------------
    # Build tests
    # -----------------------------------------------------

    if args.commands:
        steps = load_commands(args.commands)
    else:
        steps = build_steps(home)

    print(f"\nLoaded {len(steps)} test steps.")

    # -----------------------------------------------------
    # Countdown
    # -----------------------------------------------------

    for remaining in range(args.countdown, 0, -1):

        print(f"Starting in {remaining}...", flush=True)
        time.sleep(1)

    # -----------------------------------------------------
    # Agent initialization
    # -----------------------------------------------------

    agent = Agent()

    results = []

    # -----------------------------------------------------
    # Execute tests
    # -----------------------------------------------------

    for number, step in enumerate(steps, 1):

        print("\n" + "=" * 80)

        print(
            f"Step {number}/{len(steps)}: "
            f"{step.command!r}"
        )

        print(f"Expected: {step.expect or '-'}")

        print("=" * 80, flush=True)

        status, detail, elapsed = run_step(
            agent=agent,
            step=step,
            settle=args.settle,
            route_only=args.route_only,
        )

        print(
            f"-> {status}: {detail} "
            f"[{elapsed:.2f}s]",
            flush=True,
        )

        results.append(
            StepResult(
                number=number,
                command=step.command,
                status=status,
                detail=detail,
                elapsed=elapsed,
            )
        )

        if number < len(steps):
            time.sleep(args.gap)

    # -----------------------------------------------------
    # Final summary
    # -----------------------------------------------------

    counts = print_summary(results, args.log)

    # FAIL or ERROR means the demo failed.
    # SKIP, NOCHECK and EXECUTED are not counted as PASS.
    if counts.get("FAIL", 0) or counts.get("ERROR", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
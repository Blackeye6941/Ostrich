"""
Ostrich CLI — Desktop AI Agent
================================
Interactive chat interface for Ostrich.

Usage:
    python -m ostrich                    # Interactive chat (system tools)
    python -m ostrich "mute audio"       # Single command
    python -m ostrich --nav              # Desktop UI navigation mode
    python -m ostrich --all-tools        # Chat with all tools enabled
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from ostrich.agents.simple_agent import SimpleAgent
from ostrich.agents.desktop_nav_agent import DesktopNavAgent
from ostrich.models.registry import system_tools, tools as all_tools

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ── ANSI colors ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[90m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"


def _banner(mode: str) -> None:
    print(f"\n{CYAN}{BOLD}{'─' * 60}{RESET}")
    print(f"{CYAN}{BOLD}  🦅 Ostrich Desktop Agent  {DIM}[{mode}]{RESET}")
    print(f"{CYAN}{BOLD}{'─' * 60}{RESET}")
    print(f"  {DIM}Type your instruction. 'help' for tips. 'exit' to quit.{RESET}\n")


def _print_result(tool_name: str, tool_args: dict, result: Any) -> None:
    print(f"  {DIM}Tool   :{RESET} {BOLD}{tool_name}{RESET}")
    if tool_args:
        print(f"  {DIM}Args   :{RESET} {json.dumps(tool_args)}")
    print(f"  {GREEN}✓{RESET} {result}\n")


def _print_error(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}\n")


HELP_TEXT = """
Available commands:
  mute audio / unmute audio      — Toggle mute
  set volume to 60               — Set volume level
  get brightness                 — Query screen brightness
  set brightness 80              — Set brightness
  wifi status / enable wifi      — Wi-Fi controls
  bluetooth status / on / off    — Bluetooth controls
  battery status                 — Battery info
  lock screen                    — Lock the system

Navigation mode (--nav):
  click the submit button        — Click a UI element
  open calculator                — Launch an app
  switch to chrome               — Focus a window

Type 'exit' or Ctrl+C to quit.
"""


def run_chat(agent: SimpleAgent) -> None:
    """Interactive chat loop for tool calling."""
    _banner("System Tools")

    while True:
        try:
            user_input = input(f"{CYAN}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            print(f"{DIM}Goodbye.{RESET}")
            break
        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        print(f"  {DIM}Thinking...{RESET}", end="\r", flush=True)

        prediction = agent.predict(user_input)

        # Clear the "Thinking..." line
        print(" " * 30, end="\r")

        if not prediction.get("success") or not prediction.get("tool"):
            _print_error(prediction.get("error") or "No matching tool found.")
            continue

        tool_name = prediction["tool"]
        tool_args = prediction["args"]
        exec_res  = agent.execute(tool_name, tool_args)

        if exec_res.get("success"):
            _print_result(tool_name, tool_args, exec_res.get("result"))
        else:
            _print_error(exec_res.get("error") or "Execution failed.")


def run_nav_chat(agent: DesktopNavAgent) -> None:
    """Interactive chat loop for desktop UI navigation."""
    _banner("UI Navigation")

    while True:
        try:
            user_input = input(f"{CYAN}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            print(f"{DIM}Goodbye.{RESET}")
            break
        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        print(f"  {DIM}Navigating...{RESET}", end="\r", flush=True)

        result = agent.navigate(user_input)

        print(" " * 30, end="\r")

        if result.get("status") == "success":
            fn = result.get("selected_function", "?")
            args = result.get("arguments", {})
            exec_info = result.get("execution") or {}
            _print_result(fn, args, exec_info.get("result") or "Done")
        else:
            _print_error(result.get("message") or "Navigation failed.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ostrich",
        description="Ostrich Desktop AI Agent",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Single command to execute directly (non-interactive).",
    )
    parser.add_argument(
        "--nav",
        action="store_true",
        help="Use the desktop UI navigation agent.",
    )
    parser.add_argument(
        "--all-tools",
        action="store_true",
        help="Load all tools (system + UI + mouse) instead of system tools only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended actions without executing them.",
    )

    args = parser.parse_args(argv)

    if args.nav:
        agent = DesktopNavAgent(execute_actions=not args.dry_run, dry_run=args.dry_run)

        if args.query:
            result = agent.navigate(args.query)
            print(json.dumps(result, indent=2, default=str))
        else:
            run_nav_chat(agent)
    else:
        selected_tools = all_tools if args.all_tools else system_tools
        agent = SimpleAgent(tools=selected_tools)

        if args.query:
            prediction = agent.predict(args.query)
            tool_name  = prediction.get("tool")
            tool_args  = prediction.get("args", {})
            print(f"Tool: {tool_name}")
            print(f"Args: {json.dumps(tool_args)}")
            exec_res = agent.execute(tool_name, tool_args)
            if exec_res.get("success"):
                print(f"Result: {exec_res.get('result')}")
            else:
                print(f"Error: {exec_res.get('error')}", file=sys.stderr)
                sys.exit(1)
        else:
            run_chat(agent)


if __name__ == "__main__":
    main()

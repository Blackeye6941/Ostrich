"""
Main Entry Point
================
Runs the Tool Agent:
- Takes user instruction.
- Uses Needle model.complete to resolve the exact tool and arguments.
- Executes the tool and displays execution feedback in real-time.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

try:
    from agents.simple_agent import SimpleAgent, execute_tool
    from models.model import system_tools, tools as all_tools
except ImportError:
    from src.agents.simple_agent import SimpleAgent, execute_tool
    from src.models.model import system_tools, tools as all_tools

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def interactive_chat(agent: SimpleAgent):
    """Run an interactive CLI chat loop for tool execution."""
    print("=" * 65)
    print("🚀 Ostrich Tool Agent Initialized")
    print("=" * 65)
    print("Available tools include volume, brightness, wifi, bluetooth, battery, etc.")
    print("Type your instruction (e.g., 'mute audio', 'set brightness to 70')")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            user_input = input("User> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "q"}:
            print("Exiting.")
            break

        print("\nThinking...", end="", flush=True)

        # Step 1: Use model.complete to extract the exact tool and args
        prediction = agent.predict(user_input)

        if not prediction.get("success") or not prediction.get("tool"):
            print("\r" + " " * 20 + "\r", end="")
            msg = prediction.get("error") or prediction.get("message") or "No matching tool found."
            print(f"⚠️  {msg}\n")
            continue

        tool_name = prediction["tool"]
        tool_args = prediction["args"]

        print("\r" + " " * 20 + "\r", end="")
        print(f"🔧 Tool     : {tool_name}")
        print(f"📋 Arguments: {json.dumps(tool_args)}")

        # Step 2: Run the executor function that takes this input and runs the function
        exec_res = agent.execute(tool_name, tool_args)

        if exec_res.get("success"):
            print(f"✅ Result   : {exec_res.get('result')}\n")
        else:
            print(f"❌ Error    : {exec_res.get('error')}\n")


def main():
    parser = argparse.ArgumentParser(description="Ostrich Tool Agent CLI")
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Optional single user command to execute directly.",
    )
    parser.add_argument(
        "--all-tools",
        action="store_true",
        help="Load all available tools (system + UI + mouse) instead of system tools only.",
    )

    args = parser.parse_args()

    selected_tools = all_tools if args.all_tools else system_tools
    agent = SimpleAgent(tools=selected_tools)

    if args.query:
        # Direct execution of a single instruction
        prediction = agent.predict(args.query)
        tool_name = prediction.get("tool")
        tool_args = prediction.get("args")
        print(f"🔧 Tool     : {tool_name}")
        print(f"📋 Arguments: {json.dumps(tool_args)}")

        exec_res = agent.execute(prediction)
        if exec_res.get("success"):
            print(f"✅ Result   : {exec_res.get('result')}")
        else:
            print(f"❌ Error    : {exec_res.get('error')}")
    else:
        # Start interactive session
        interactive_chat(agent)


if __name__ == "__main__":
    main()

"""
Desktop Navigation Agent Verification Script
============================================
Tests:
1. Resolving target windows from user instructions.
2. Retrieving UI context from @src/context/.
3. Grounding and selecting target UI nodes.
4. Parameterizing and executing actions on nodes.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.desktop_nav_agent import DesktopNavAgent
from models.model import load_needle_model


def run_tests():
    print("=" * 70)
    print("DesktopNavAgent Verification Test Suite")
    print("=" * 70)

    model = load_needle_model()
    # Use dry_run=True for safe testing without dispatching real mouse clicks
    agent = DesktopNavAgent(needle_model=model, execute_actions=True, dry_run=True)

    # -----------------------------------------------------------------------
    # Test 1: Window Resolution
    # -----------------------------------------------------------------------
    print("\n--- 1. Testing Target Window Resolution ---")
    mock_windows = [
        {"id": 101, "name": "google-chrome", "title": "New Tab - Google Chrome", "focus": False},
        {"id": 102, "name": "gnome-calculator", "title": "Calculator", "focus": False},
        {"id": 103, "name": "gnome-terminal", "title": "Terminal", "focus": True},
    ]

    res1 = agent.resolve_target_window("click 7 in calculator", mock_windows)
    print("Query 'click 7 in calculator' ->", res1)
    assert res1 is not None
    assert "calculator" in res1["name"].lower() or "calculator" in res1["title"].lower()

    res2 = agent.resolve_target_window("switch to chrome and search", mock_windows)
    print("Query 'switch to chrome and search' ->", res2)
    assert res2 is not None
    assert "chrome" in res2["name"].lower()

    res3 = agent.resolve_target_window("click save button", mock_windows)
    print("Query 'click save button' (default active) ->", res3)
    assert res3 is not None
    assert res3["is_focused"] is True

    print("✔ Target window resolution passed!")

    # -----------------------------------------------------------------------
    # Test 2: UI Context Retrieval from @src/context/
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing UI Context Retrieval from @src/context/ ---")
    calc_ctx = agent.fetch_ui_context("calculator")
    print(f"Calculator UI context: title='{calc_ctx.get('title')}', nodes={len(calc_ctx.get('nodes', []))}")
    assert calc_ctx is not None
    assert len(calc_ctx["nodes"]) > 0

    settings_ctx = agent.fetch_ui_context("settings")
    print(f"Settings UI context: title='{settings_ctx.get('title')}', nodes={len(settings_ctx.get('nodes', []))}")
    assert settings_ctx is not None
    assert len(settings_ctx["nodes"]) > 0

    print("✔ UI context retrieval passed!")

    # -----------------------------------------------------------------------
    # Test 3: End-to-End Processing on Real UI Data (Calculator)
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing End-to-End Node Action (Calculator) ---")
    test_cases_calc = [
        ("click button 7 in calculator", "7"),
        ("click button 8 in calculator", "8"),
        ("click plus button in calculator", "+"),
    ]

    for instruction, expected_name in test_cases_calc:
        print(f"\n[Test] Instruction: \"{instruction}\"")
        result = agent.process(instruction)
        print("Status          :", result.get("status"))
        print("Window Title    :", result.get("window_title"))
        node = result.get("selected_node")
        print(f"Selected Node   : [{node.get('id')}] '{node.get('name')}' ({node.get('role')}) bbox={node.get('bbox')}")
        print("Action          :", result.get("action"))
        print("Execution Result:", result.get("execution"))

        assert result.get("status") == "success"
        assert expected_name.lower() in node.get("name", "").lower(), f"Expected {expected_name}, got {node.get('name')}"
        assert result.get("action", {}).get("function") in ("mouse_click", "mouse_select")
        # Ensure coordinates are within the node's bbox
        bx, by, bw, bh = node["bbox"]
        ax = result["action"]["arguments"]["x"]
        ay = result["action"]["arguments"]["y"]
        assert bx <= ax <= bx + bw, f"x={ax} not in [{bx}, {bx+bw}]"
        assert by <= ay <= by + bh, f"y={ay} not in [{by}, {by+bh}]"

    # -----------------------------------------------------------------------
    # Test 4: End-to-End Processing on Real UI Data (Settings)
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing End-to-End Node Action (Settings) ---")
    test_cases_settings = [
        ("click Network in settings", "Network"),
        ("click Bluetooth in settings", "Bluetooth"),
        ("click Wi-Fi in settings", "Wi-Fi"),
    ]

    for instruction, expected_name in test_cases_settings:
        print(f"\n[Test] Instruction: \"{instruction}\"")
        result = agent.process(instruction)
        node = result.get("selected_node")
        print(f"Selected Node   : [{node.get('id')}] '{node.get('name')}' ({node.get('role')})")
        print("Action          :", result.get("action"))
        assert result.get("status") == "success"
        assert expected_name.lower() in node.get("name", "").lower(), f"Expected {expected_name}, got {node.get('name')}"

    print("\n" + "=" * 70)
    print("✔ ALL DESKTOP NAVIGATION AGENT TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()

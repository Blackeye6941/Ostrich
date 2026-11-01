"""
Desktop Navigation Agent Module
===============================
An autonomous desktop navigation agent that:
1. Analyzes user intent to determine target applications or windows.
2. Navigates / switches to target windows (using desktop navigation tools).
3. Retrieves rich UI context trees from @src/context/ (live AT-SPI or snapshots).
4. Prunes and identifies the target UI node corresponding to user intent.
5. Grounds coordinates and determines the appropriate action (click, double click, move, etc.).
6. Executes actions on target nodes using purely mouse movements.
7. Executes multi-step, complicated mathematical calculations in a calculator using purely mouse movements.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any, Callable

try:
    from tools.ui_tools import list_windows, switch_window, open_app
    from tools.mouse_tools import mouse_click, mouse_double_click, mouse_move, mouse_select
except ImportError:
    from src.tools.ui_tools import list_windows, switch_window, open_app
    from src.tools.mouse_tools import mouse_click, mouse_double_click, mouse_move, mouse_select

try:
    from context import get_ui_context, deterministic_prune, resolve_app_name
except ImportError:
    from src.context import get_ui_context, deterministic_prune, resolve_app_name

try:
    from agents.ui_selection_agent import UIElementSelectionAgent
    from agents.function_selection_agent import FunctionSelectionAgent
    from agents.executor import ActionExecutor
    from models.model import load_needle_model
except ImportError:
    from src.agents.ui_selection_agent import UIElementSelectionAgent
    from src.agents.function_selection_agent import FunctionSelectionAgent
    from src.agents.executor import ActionExecutor
    from src.models.model import load_needle_model

log = logging.getLogger("desktop_nav_agent")


class DesktopNavAgent:
    """Desktop Navigation and Action Agent.

    Coordinates window-level navigation, UI context retrieval, element grounding,
    and action execution.

    Parameters
    ----------
    needle_model : Any | None
        Underlying Needle model instance for embedding or completions.
    execute_actions : bool
        Whether to physically execute the chosen actions (True) or plan only (False).
    dry_run : bool
        If True, log intended actions without dispatching OS calls.
    top_candidates : int
        Number of candidate UI nodes to retain during context pruning.
    """

    def __init__(
        self,
        needle_model: Any | None = None,
        execute_actions: bool = True,
        dry_run: bool = False,
        top_candidates: int = 5,
    ):
        self.needle_model = needle_model or load_needle_model()
        self.execute_actions = execute_actions
        self.dry_run = dry_run
        self.top_candidates = top_candidates

        self.ui_agent = UIElementSelectionAgent(
            needle_model=self.needle_model,
            top_candidates=top_candidates,
        )
        self.fn_agent = FunctionSelectionAgent(needle_model=self.needle_model)
        self.executor = ActionExecutor(dry_run=dry_run)

    # -----------------------------------------------------------------------
    # Step 1: Target Window Resolution
    # -----------------------------------------------------------------------

    def resolve_target_window(
        self,
        instruction: str,
        open_windows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Analyze user instruction to identify if a specific window/app is targeted."""
        inst_lower = instruction.strip().lower()

        # Fetch open windows if not provided
        if open_windows is None:
            try:
                win_res = list_windows()
                open_windows = win_res.get("windows", []) if win_res.get("success") else []
            except Exception as exc:
                log.debug("Failed to list open desktop windows: %s", exc)
                open_windows = []

        # 1. Match against known open window titles or app names
        best_match = None
        for win in open_windows:
            title = (win.get("title") or "").lower()
            name = (win.get("name") or "").lower()

            if (name and name in inst_lower) or (title and any(word in inst_lower for word in title.split() if len(word) > 3)):
                best_match = win
                break

        if best_match:
            return {
                "target": best_match.get("title") or best_match.get("name"),
                "title": best_match.get("title"),
                "name": best_match.get("name"),
                "id": best_match.get("id"),
                "is_focused": best_match.get("focus", False),
                "is_open": True,
            }

        # 2. Check for explicit window targeting phrases (e.g. "in calculator", "to settings", "on chrome")
        match = re.search(
            r"\b(?:in|on|to|switch to|open|inside|app)\s+([a-zA-Z0-9_\-]+)",
            inst_lower,
        )
        if match:
            app_candidate = match.group(1).strip()
            resolved = resolve_app_name(app_candidate)
            return {
                "target": resolved,
                "title": app_candidate.capitalize(),
                "name": resolved,
                "id": None,
                "is_focused": False,
                "is_open": False,
            }

        # 3. Default to current focused window if available
        for win in open_windows:
            if win.get("focus"):
                return {
                    "target": win.get("title") or win.get("name"),
                    "title": win.get("title"),
                    "name": win.get("name"),
                    "id": win.get("id"),
                    "is_focused": True,
                    "is_open": True,
                }

        return None

    # -----------------------------------------------------------------------
    # Step 2: Window Navigation
    # -----------------------------------------------------------------------

    def navigate_to_window(self, target_window: dict[str, Any] | str) -> dict[str, Any]:
        """Switch to or launch the target window."""
        if isinstance(target_window, dict):
            target_str = target_window.get("title") or target_window.get("name") or target_window.get("target")
            is_focused = target_window.get("is_focused", False)
            is_open = target_window.get("is_open", True)
        else:
            target_str = str(target_window)
            is_focused = False
            is_open = True

        if not target_str:
            return {"success": False, "error": "No valid window target provided."}

        if is_focused:
            return {"success": True, "action": "none", "message": f"Window '{target_str}' is already focused."}

        log.info("Navigating to target window: '%s'", target_str)

        try:
            res = switch_window(target_str)
            if res.get("success"):
                return {
                    "success": True,
                    "action": "switch_window",
                    "target": target_str,
                    "message": f"Switched to window '{target_str}'.",
                }
        except Exception as exc:
            log.debug("switch_window failed for '%s': %s", target_str, exc)

        if not is_open:
            try:
                res_open = open_app(target_str)
                return {
                    "success": res_open.get("success", False),
                    "action": "open_app",
                    "target": target_str,
                    "message": f"Launched application '{target_str}'.",
                }
            except Exception as exc:
                return {"success": False, "error": f"Failed to launch '{target_str}': {exc}"}

        return {"success": False, "error": f"Could not navigate to window '{target_str}'."}

    # -----------------------------------------------------------------------
    # Step 3: Retrieve UI Context from @src/context/
    # -----------------------------------------------------------------------

    def fetch_ui_context(self, window_query: str | None = None) -> dict[str, Any] | None:
        """Fetch the UI context (accessible node tree) from @src/context/."""
        try:
            context = get_ui_context(window_query=window_query)
            if context and context.get("nodes"):
                log.info(
                    "Retrieved UI context for '%s' (%d accessible nodes)",
                    context.get("title"),
                    len(context.get("nodes")),
                )
                return context
        except Exception as exc:
            log.exception("Error retrieving UI context for query '%s': %s", window_query, exc)

        return None

    # -----------------------------------------------------------------------
    # Step 4: Select Target Node in UI Context
    # -----------------------------------------------------------------------

    def _clean_node_instruction(self, instruction: str, target_name: str | None) -> str:
        """Remove window-targeting phrases so element selection focuses on the UI node."""
        cleaned = instruction.strip()
        if target_name:
            cleaned = re.sub(rf"\b(?:in|on|inside)\s+{re.escape(target_name)}\b", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(rf"\b(?:switch to|go to|open)\s+{re.escape(target_name)}\s*(?:and\s*)?", "", cleaned, flags=re.IGNORECASE)
            simple_name = target_name.split("-")[-1]
            if simple_name != target_name:
                cleaned = re.sub(rf"\b(?:in|on|inside)\s+{re.escape(simple_name)}\b", "", cleaned, flags=re.IGNORECASE)

        # Map verbal math operators to button symbols
        symbol_map = {
            r"\bplus\b": "+",
            r"\bminus\b": "-",
            r"\btimes\b": "*",
            r"\bdivided by\b": "/",
        }
        for pat, repl in symbol_map.items():
            cleaned = re.sub(pat, repl, cleaned, flags=re.IGNORECASE)

        return cleaned.strip()

    def select_node(
        self,
        instruction: str,
        ui_context: dict[str, Any],
        target_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Ground the target UI element in the window's UI context nodes."""
        node_query = self._clean_node_instruction(instruction, target_name)
        log.info("Node selection query after cleanup: '%s'", node_query)
        return self.ui_agent.select_element(node_query, ui_context)

    # -----------------------------------------------------------------------
    # Step 5: Determine & Parameterize Action on Node
    # -----------------------------------------------------------------------

    def select_action(
        self,
        instruction: str,
        selected_node: dict[str, Any] | None,
        ui_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Determine the function call and grounded coordinates for the target node."""
        return self.fn_agent.select_function(
            instruction=instruction,
            selected_element=selected_node,
            active_window=ui_context,
        )

    # -----------------------------------------------------------------------
    # Step 6: Action Execution
    # -----------------------------------------------------------------------

    def execute_action(self, func_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the chosen tool action."""
        return self.executor.execute(func_name, arguments)

    # -----------------------------------------------------------------------
    # Step 7: Single Instruction Processor
    # -----------------------------------------------------------------------

    def process(
        self,
        instruction: str,
        ui_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the full desktop navigation workflow for an instruction."""
        inst = instruction.strip()
        if not inst:
            return {"status": "error", "message": "Empty instruction provided."}

        log.info("DesktopNavAgent processing instruction: '%s'", inst)

        # 1. Resolve target window from instruction
        target_win = self.resolve_target_window(inst)
        target_name = target_win.get("target") if target_win else None
        if not target_name and target_win:
            target_name = target_win.get("name") or target_win.get("title")

        # 2. Navigate to target window if needed
        nav_report = None
        if target_win and not target_win.get("is_focused") and self.execute_actions:
            nav_report = self.navigate_to_window(target_win)
            log.info("Navigation report: %s", nav_report)

        # 3. Retrieve UI context from @src/context/
        active_ctx = ui_context
        if active_ctx is None:
            active_ctx = self.fetch_ui_context(window_query=target_name)

        if not active_ctx or not active_ctx.get("nodes"):
            log.warning("No UI context nodes found for window '%s'", target_name)
            return {
                "status": "error",
                "message": f"Could not retrieve UI context for target window '{target_name}'.",
                "instruction": inst,
                "target_window": target_win,
                "navigation": nav_report,
            }

        # 4. Select target node in UI context
        selected_node = self.select_node(inst, active_ctx, target_name=target_name)

        # 5. Determine function and ground coordinates on the node
        action_plan = self.select_action(inst, selected_node, active_ctx)

        if not action_plan:
            return {
                "status": "error",
                "message": "Failed to resolve action for target node.",
                "instruction": inst,
                "target_window": target_win,
                "selected_node": selected_node,
            }

        func_name = action_plan.get("function")
        arguments = action_plan.get("arguments", {})

        # 6. Execute action on the node
        exec_report = None
        if self.execute_actions and func_name:
            exec_report = self.execute_action(func_name, arguments)
            log.info("Action execution report: %s", exec_report)

        return {
            "status": "success",
            "instruction": inst,
            "target_window": target_win,
            "window_navigation": nav_report,
            "window_title": active_ctx.get("title"),
            "selected_node": selected_node,
            "action": {
                "function": func_name,
                "arguments": arguments,
            },
            "execution": exec_report,
        }

    # -----------------------------------------------------------------------
    # Step 8: Multi-step Pure Mouse Calculator Calculations
    # -----------------------------------------------------------------------

    def decompose_math_expression(self, expression: str) -> list[str]:
        """Decompose a mathematical expression into sequential calculator button symbols."""
        clean = expression.strip()
        # Normalization map for symbols
        token_map = {
            "*": "×",
            "x": "×",
            "X": "×",
            "/": "÷",
            "-": "−",
            "=": "=",
            "(": "(",
            ")": ")",
            ".": ".",
            "+": "+",
        }

        tokens: list[str] = []
        i = 0
        while i < len(clean):
            ch = clean[i]
            if ch in " \t,":
                i += 1
                continue

            # Multi-character operations
            if clean[i : i + 2].lower() == "x2":
                tokens.append("x2")
                i += 2
                continue
            if clean[i : i + 3].lower() == "mod":
                tokens.append("mod")
                i += 3
                continue
            if clean[i : i + 4].lower() == "sqrt" or clean[i : i + 1] == "√":
                tokens.append("√")
                i += 4 if clean[i : i + 4].lower() == "sqrt" else 1
                continue
            if clean[i : i + 5].lower() == "clear":
                tokens.append("C")
                i += 5
                continue
            if ch in ("C", "c"):
                tokens.append("C")
                i += 1
                continue

            if ch in token_map:
                tokens.append(token_map[ch])
            elif ch.isdigit():
                tokens.append(ch)
            else:
                tokens.append(ch)
            i += 1

        # Ensure final '=' is present to evaluate
        if tokens and tokens[-1] != "=":
            tokens.append("=")

        return tokens

    def calculate(
        self,
        expression: str,
        ui_context: dict[str, Any] | None = None,
        live: bool = False,
        delay_between_clicks: float = 0.2,
    ) -> dict[str, Any]:
        """Perform a complicated calculation on a calculator using PURELY mouse movements.

        Every operation is executed strictly by moving the mouse to the center of the
        calculator button's bounding box and performing a mouse click.
        Zero keyboard inputs are used.

        Parameters
        ----------
        expression : str
            The mathematical expression to evaluate (e.g. '(48 + 52) * 4 =').
        ui_context : dict[str, Any] | None
            Pre-loaded calculator UI context, or None to fetch dynamically from @src/context/.
        live : bool
            Whether to ensure live calculator window is open on screen for visible execution.
        delay_between_clicks : float
            Delay in seconds between mouse clicks for visible user pacing.

        Returns
        -------
        dict[str, Any]
            Detailed report including the token sequence, mouse trajectory, coordinates,
            total distance traveled by the mouse, and mathematical result.
        """
        # 1. If live mode requested, ensure calculator is running and focused
        if live:
            import subprocess
            try:
                win_res = list_windows()
                open_wins = win_res.get("windows", []) if win_res.get("success") else []
                is_running = any("calculator" in (w.get("name") or "").lower() or "calculator" in (w.get("title") or "").lower() for w in open_wins)
                if not is_running:
                    subprocess.Popen(["gnome-calculator"])
                    time.sleep(1.2)
                switch_window("Calculator")
                time.sleep(0.6)
            except Exception as exc:
                log.debug("Live calculator window setup: %s", exc)

        # 2. Fetch or use provided UI context
        calc_ctx = ui_context
        if calc_ctx is None:
            calc_ctx = self.fetch_ui_context("calculator")

        if not calc_ctx or not calc_ctx.get("nodes"):
            return {
                "status": "error",
                "message": "Calculator UI context could not be loaded from @src/context/.",
                "expression": expression,
            }

        nodes = calc_ctx["nodes"]

        # Build fast lookup map for push button nodes by name
        button_map: dict[str, dict[str, Any]] = {}
        for n in nodes:
            if n.get("role") in ("push button", "toggle button") and n.get("name"):
                button_map[n["name"]] = n

        # Fallback map for any node matching name
        for n in nodes:
            if n.get("name") and n["name"] not in button_map:
                button_map[n["name"]] = n

        # 2. Decompose expression into sequential button tokens
        tokens = self.decompose_math_expression(expression)

        trajectory: list[dict[str, Any]] = []
        total_distance = 0.0
        current_x, current_y = 0, 0

        # 3. Execute purely mouse movements for each button
        for step_idx, sym in enumerate(tokens, 1):
            if sym not in button_map:
                return {
                    "status": "error",
                    "message": f"Button symbol '{sym}' not found on calculator keypad.",
                    "expression": expression,
                    "failed_step": step_idx,
                    "failed_symbol": sym,
                    "completed_steps": trajectory,
                }

            node = button_map[sym]
            bbox = node.get("bbox", (0, 0, 0, 0))
            bx, by, bw, bh = bbox

            # Calculate exact center coordinates on the button
            target_x = bx + bw // 2
            target_y = by + bh // 2

            # Calculate Euclidean distance traveled by mouse
            if step_idx > 1:
                dist = math.hypot(target_x - current_x, target_y - current_y)
            else:
                dist = 0.0
            total_distance += dist

            # Pure Mouse Action: Move to button, then click button
            move_res = None
            click_res = None
            if self.execute_actions:
                # 1. Pure mouse movement to button
                move_res = self.executor.execute("mouse_move", {"x": target_x, "y": target_y})
                # 2. Pure mouse click at target coordinates
                click_res = self.executor.execute("mouse_click", {"x": target_x, "y": target_y})

            step_record = {
                "step": step_idx,
                "symbol": sym,
                "node_id": node.get("id"),
                "node_name": node.get("name"),
                "node_role": node.get("role"),
                "bbox": bbox,
                "mouse_coords": (target_x, target_y),
                "mouse_distance_px": round(dist, 1),
                "mouse_actions": ["mouse_move", "mouse_click"],
                "move_execution": move_res,
                "click_execution": click_res,
            }
            trajectory.append(step_record)

            current_x, current_y = target_x, target_y
            if delay_between_clicks > 0:
                time.sleep(delay_between_clicks)

        # 4. Calculate expected mathematical result
        # Convert symbols to Python math syntax for evaluation
        py_expr = expression.replace("×", "*").replace("÷", "/").replace("−", "-").replace("=", "").strip()
        # Handle x2
        py_expr = re.sub(r"(\d+)\s*x2", r"(\1**2)", py_expr)
        # Handle C (clear)
        if "C" in py_expr:
            py_expr = py_expr.split("C")[-1].strip()

        expected_val = None
        try:
            expected_val = eval(py_expr, {"__builtins__": None}, {})
            if isinstance(expected_val, float) and expected_val.is_integer():
                expected_val = int(expected_val)
        except Exception:
            expected_val = None

        return {
            "status": "success",
            "expression": expression,
            "tokens": tokens,
            "mouse_only": True,
            "total_mouse_steps": len(trajectory),
            "total_distance_px": round(total_distance, 1),
            "expected_result": expected_val,
            "trajectory": trajectory,
        }

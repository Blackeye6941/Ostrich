"""
Agent 2: Function Selection.

Responsible for:
1. Using the Needle model in src/models to identify the correct function or action
   corresponding to the selected UI element and user instruction.
2. Grounding parameters (e.g., coordinates x, y from element bbox, application names).
3. Ensuring the selected function is relevant to the requested operation.
"""

from __future__ import annotations

import logging
from typing import Any

from models.model import load_needle_model

log = logging.getLogger("agent2_function_selection")


class FunctionSelectionAgent:
    """Agent responsible for selecting and parameterizing functions using Needle."""

    def __init__(self, needle_model: Any | None = None):
        self.needle_model = needle_model or load_needle_model()

    def select_function(
        self,
        instruction: str,
        selected_element: dict[str, Any] | None = None,
        active_window: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Identify the function and arguments corresponding to the instruction and element.

        Parameters
        ----------
        instruction : str
            The user command / request.
        selected_element : dict[str, Any] | None
            The UI element chosen by Agent 1.
        active_window : dict[str, Any] | None
            The current active window info.

        Returns
        -------
        dict[str, Any] | None
            Dictionary with {"function": str, "arguments": dict, "raw_response": dict}
            or None if no valid function could be identified.
        """
        if not instruction or not instruction.strip():
            log.warning("Empty instruction provided to FunctionSelectionAgent")
            return None

        prompt = self._build_function_query(instruction, selected_element, active_window)
        log.info("Function query prompt: %s", prompt)

        try:
            response = self.needle_model.complete(prompt)
        except Exception as exc:
            log.exception("Needle model completion failed: %s", exc)
            return None

        calls = response.get("function_calls") or []
        if not calls:
            # Fallback to suppressed calls if function_calls is empty
            calls = response.get("suppressed_calls") or []

        if not calls:
            log.warning("No function call returned by Needle model for '%s'", instruction)
            return None

        chosen_call = calls[0]
        func_name = chosen_call.get("name")
        arguments = dict(chosen_call.get("arguments") or {})

        # Ground coordinates if selected_element has a valid bounding box and tool requires x, y.
        # bbox may be in screen coords (bbox_is_screen=True) or window-relative coords
        # (bbox_is_screen=False).  Only add the window's screen offset when the bbox is
        # window-relative; screen-coord bboxes already hold absolute positions.
        if selected_element and func_name in ("mouse_click", "mouse_double_click", "mouse_move"):
            bbox = selected_element.get("bbox", (0, 0, 0, 0))
            if len(bbox) == 4 and bbox[2] > 0 and bbox[3] > 0:
                bbox_is_screen = selected_element.get("bbox_is_screen", False)
                if bbox_is_screen:
                    # bbox already holds absolute screen coordinates.
                    center_x = bbox[0] + bbox[2] // 2
                    center_y = bbox[1] + bbox[3] // 2
                else:
                    # bbox is window-relative; apply the window's screen offset.
                    win_x = (active_window or {}).get("win_x", 0)
                    win_y = (active_window or {}).get("win_y", 0)
                    center_x = win_x + bbox[0] + bbox[2] // 2
                    center_y = win_y + bbox[1] + bbox[3] // 2
                arguments["x"] = center_x
                arguments["y"] = center_y

        log.info("Selected function: %s with arguments: %s", func_name, arguments)
        return {
            "function": func_name,
            "arguments": arguments,
            "raw_response": response,
        }

    def _build_function_query(
        self,
        instruction: str,
        selected_element: dict[str, Any] | None,
        active_window: dict[str, Any] | None,
    ) -> str:
        """Construct an unambiguous query for the Needle model."""
        inst_clean = instruction.strip()
        inst_lower = inst_clean.lower()

        # If a UI element was selected, provide its coordinates and role
        if selected_element:
            bbox = selected_element.get("bbox", (0, 0, 0, 0))
            x, y, w, h = bbox
            # Apply window screen offset only when bbox is window-relative.
            bbox_is_screen = selected_element.get("bbox_is_screen", False)
            if bbox_is_screen:
                cx = x + w // 2
                cy = y + h // 2
            else:
                win_x = (active_window or {}).get("win_x", 0)
                win_y = (active_window or {}).get("win_y", 0)
                cx = win_x + x + w // 2
                cy = win_y + y + h // 2

            if "double" in inst_lower:
                action = f"double click at x={cx} y={cy}"
            elif "right click" in inst_lower:
                action = f"click at x={cx} y={cy} with right button"
            elif "move" in inst_lower or "hover" in inst_lower:
                action = f"mouse_move to x={cx} y={cy}"
            else:
                action = f"click at x={cx} y={cy}"

            return action

        # If no UI element is selected, pass the instruction directly (e.g. window management, open app)
        return inst_clean

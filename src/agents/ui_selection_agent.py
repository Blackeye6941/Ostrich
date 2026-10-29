"""
Agent 1: UI Element Selection.

Responsible for:
1. Deterministic context pruning of candidate UI elements from active window context.
2. Grounded candidate ranking / LLM selection.
3. Returning the target UI element or None if not found.
"""

from __future__ import annotations

import logging
from typing import Any

from context.pruning import deterministic_prune, calculate_element_score

log = logging.getLogger("agent1_ui_selection")


class UIElementSelectionAgent:
    """Agent responsible for selecting target UI elements from UI context."""

    def __init__(self, needle_model: Any | None = None, top_candidates: int = 5):
        self.needle_model = needle_model
        self.top_candidates = top_candidates

    def select_element(
        self,
        instruction: str,
        active_window: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Select the target UI element based on instruction and active window UI context.

        Parameters
        ----------
        instruction : str
            The user request / command.
        active_window : dict[str, Any] | None
            The shared active_window dictionary containing 'nodes' and 'title'.

        Returns
        -------
        dict[str, Any] | None
            The selected UI element dict, or None if no matching element is found.
        """
        if not instruction or not instruction.strip():
            log.warning("Empty instruction provided to UIElementSelectionAgent")
            return None

        if not active_window:
            log.warning("No active window context available for UI element selection")
            return None

        nodes: list[dict[str, Any]] = active_window.get("nodes") or []
        if not nodes:
            log.warning("Active window '%s' has no UI nodes", active_window.get("title"))
            return None

        # Step 1: Deterministic context pruning
        candidates = deterministic_prune(nodes, instruction, top_k=self.top_candidates)
        if not candidates:
            log.warning("No UI elements survived pruning for instruction: %s", instruction)
            return None

        log.info(
            "Pruned %d nodes down to %d candidates for instruction: '%s'",
            len(nodes),
            len(candidates),
            instruction,
        )

        # Step 2: Grounded final selection using LLM (Needle) if available, with scoring fallback
        selected = self._llm_select(instruction, candidates)
        if selected:
            log.info(
                "Selected element [%s] '%s' (%s) at %s",
                selected.get("id"),
                selected.get("name"),
                selected.get("role"),
                selected.get("bbox"),
            )
        return selected

    def _llm_select(
        self,
        instruction: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Ground the selection in candidates using Needle embedding or fallback score."""
        if not candidates:
            return None

        if len(candidates) == 1:
            return candidates[0]

        # Use Needle model embeddings if available
        if self.needle_model is not None and hasattr(self.needle_model, "embed"):
            try:
                q_emb = self.needle_model.embed(instruction)
                best_sim = -float("inf")
                best_cand = None

                for cand in candidates:
                    cand_desc = f"{cand.get('role')} {cand.get('name')} {cand.get('desc', '')}".strip()
                    c_emb = self.needle_model.embed(cand_desc)
                    # Dot product of normalized embeddings
                    sim = sum(a * b for a, b in zip(q_emb, c_emb))
                    # Add bonus if name is directly in instruction
                    name = (cand.get("name") or "").lower()
                    if name and name in instruction.lower():
                        sim += 0.05
                    if sim > best_sim:
                        best_sim = sim
                        best_cand = cand

                if best_cand:
                    return best_cand
            except Exception as exc:
                log.warning("Needle embed selection failed: %s; falling back to scoring", exc)

        # Deterministic score ranking fallback
        from context.pruning import tokenize
        q_tokens = tokenize(instruction)
        best_cand = max(candidates, key=lambda c: calculate_element_score(c, instruction, q_tokens))
        return best_cand

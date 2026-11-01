"""
Deterministic Pruning of UI Context Candidates for Agent 1.
"""

from __future__ import annotations

import re
from typing import Any

# Match referents or instruction patterns
_REFERENTS_RE = re.compile(
    r"\b(that|this|it|him|her|them|first|second|third|last|next|previous)\b", re.I
)
_TOKEN_RE = re.compile(r"[a-z0-9_-]+", re.I)

# Common stopwords to exclude from candidate matching tokens
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "in", "on", "at", "for", "from",
    "with", "by", "of", "please", "can", "you", "now", "want", "need",
    "click", "tap", "press", "select", "choose", "open", "double", "right",
    "button", "icon", "element", "item", "ui", "screen", "window",
}


def tokenize(text: str) -> set[str]:
    """Extract normalized alphanumeric words from text excluding stopwords."""
    if not text:
        return set()
    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}
    return tokens - _STOPWORDS


def calculate_element_score(node: dict[str, Any], query: str, query_tokens: set[str]) -> float:
    """Calculate deterministic matching score between an instruction query and a UI element."""
    name = (node.get("name") or "").strip().lower()
    desc = (node.get("desc") or "").strip().lower()
    role = (node.get("role") or "").strip().lower()
    states = node.get("states") or []

    combined_text = f"{name} {desc}"
    node_tokens = tokenize(combined_text)

    score = 0.0

    # Direct substring / exact name match
    if name:
        if name in query.lower():
            score += 15.0
        if query.lower() in name:
            score += 10.0

    # Token overlap with instruction query
    overlap = query_tokens.intersection(node_tokens)
    score += len(overlap) * 5.0

    # Prefix match bonus
    for q_tok in query_tokens:
        for n_tok in node_tokens:
            if n_tok.startswith(q_tok) or q_tok.startswith(n_tok):
                score += 2.0

    # Role matching bonus (e.g. user says 'button' and role is 'push button')
    query_lower = query.lower()
    if role in query_lower:
        score += 3.0
    elif "button" in query_lower and "button" in role:
        score += 2.5
    elif ("text" in query_lower or "input" in query_lower or "write" in query_lower) and (
        "entry" in role or "text" in role
    ):
        score += 3.0
    elif ("tab" in query_lower) and "tab" in role:
        score += 3.0
    elif ("item" in query_lower or "list" in query_lower) and "item" in role:
        score += 2.0

    # Interactive state bonuses
    if "focused" in states:
        score += 1.5
    if "selected" in states:
        score += 1.0
    if "editable" in states:
        score += 0.5

    # Check bounding box validity (grounded on screen)
    bbox = node.get("bbox", (0, 0, 0, 0))
    if len(bbox) == 4 and bbox[2] > 0 and bbox[3] > 0:
        score += 0.5
    else:
        score -= 5.0  # heavily penalize zero-size elements

    return score


def deterministic_prune(
    nodes: list[dict[str, Any]],
    instruction: str,
    top_k: int = 5,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Prune candidate UI elements deterministically down to the top_k most relevant nodes.

    Parameters
    ----------
    nodes : list[dict[str, Any]]
        Flat list of candidate UI element dicts from the serialized tree.
    instruction : str
        The user instruction / query.
    top_k : int
        Maximum number of candidate elements to retain for the final LLM selection step.
    min_score : float
        Minimum score threshold required for consideration.

    Returns
    -------
    list[dict[str, Any]]
        Ranked list of top_k pruned candidates.
    """
    if not nodes:
        return []

    q_tokens = tokenize(instruction)

    # Filter out empty or completely ungrounded nodes first
    valid_nodes = []
    for n in nodes:
        bbox = n.get("bbox", (0, 0, 0, 0))
        # Ensure bounding box has valid width and height
        if len(bbox) >= 4 and bbox[2] > 0 and bbox[3] > 0:
            valid_nodes.append(n)

    if not valid_nodes:
        valid_nodes = nodes

    # Score each node
    scored: list[tuple[float, dict[str, Any]]] = []
    for node in valid_nodes:
        s = calculate_element_score(node, instruction, q_tokens)
        scored.append((s, node))

    # Sort descending by score, maintaining stable order on tie
    scored.sort(key=lambda item: item[0], reverse=True)

    # Filter by min_score if positive matches exist
    positive_scored = [node for score, node in scored if score > min_score]
    if positive_scored:
        return positive_scored[:top_k]

    # Fallback to top_k of scored if no positive score met
    return [node for _, node in scored[:top_k]]

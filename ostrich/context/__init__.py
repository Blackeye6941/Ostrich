"""UI context extraction and pruning."""

from ostrich.context.tree_pipeline import (
    INTERACTIVE_ROLES,
    SERIALIZE_STATES,
    SKIP_APPS,
    get_screen_bounds,
    count_nodes,
    count_forest,
    build_node,
    prune_visibility,
    prune_structure,
    prune_dedupe,
    prune_pipeline,
    serialize_tree,
    get_ui_context,
)
from ostrich.context.pruning import (
    deterministic_prune,
    calculate_element_score,
)
from ostrich.context.app_aliases import resolve_app_name

__all__ = [
    "INTERACTIVE_ROLES",
    "SERIALIZE_STATES",
    "SKIP_APPS",
    "get_screen_bounds",
    "count_nodes",
    "count_forest",
    "build_node",
    "prune_visibility",
    "prune_structure",
    "prune_dedupe",
    "prune_pipeline",
    "serialize_tree",
    "get_ui_context",
    "deterministic_prune",
    "calculate_element_score",
    "resolve_app_name",
]

from models.model import load_needle_model
from pydantic import BaseModel, Field
from context.ui_tree.linux.linux import build_virtual_ui_tree
import re

tree = build_virtual_ui_tree()

agent = load_needle_model()

SYSTEM = re.compile(r"^(gsd-|ibus|mutter|gjs|xdg-|update-notifier|evolution-alarm|gnome-shell)")
REFERENTS = re.compile(r"\b(that|this|it|him|her|them|first|second|third|last|next|previous)\b", re.I)

def running_apps(nodes, cap=6):
    seen = []
    for n in nodes:
        if not SYSTEM.match(n.name) and n.name not in seen:
            seen.append(n.name)
    return seen[:cap]

def build_query(utterance, nodes):
    q = f"say: {utterance.strip()}"
    if REFERENTS.search(utterance):          # only pay for context when needed
        q += "\napps: " + ", ".join(running_apps(nodes))
    return q


experiments = [
    "Open google chrome",
    "switch to vs code",
    "maximize chrome",
    "minimize chrome",
    "split vs code with terminal"
]

def run_model(user: str):
    nodes = [value.name for _, value in tree.items()]
    query_with_context = build_query(user, nodes)
    response = agent.complete(query_with_context.strip())
    return response

import time

for exp in experiments:
    start = time.perf_counter()
    response = run_model(exp)
    duration = time.perf_counter() - start

    print(f"function call: {response['function_calls']}")
    print(f"suppressed calls: {response['suppressed_calls']}")
    print(f"Duration: {duration:.3f} s")          # e.g. "Duration: 0.482 s"



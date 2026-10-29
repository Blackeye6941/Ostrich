import json
from enum import Enum
from typing import Callable

from openai import OpenAI


class Agent(str, Enum):
    SYSTEM = "system"
    NAVIGATION = "navigation"
    FILE_MANAGER = "file_manager"


SYSTEM_PROMPT = (
    "You are a router. Pick the single best agent for the user's message.\n"
    "- system: OS actions (volume, wifi, apps, power, settings)\n"
    "- navigation: directions, maps, places, URLs\n"
    "- file_manager: create, find, move, rename, delete files and folders"
)

SCHEMA = {
    "type": "object",
    "properties": {"agent_type": {"type": "string", "enum": [a.value for a in Agent]}},
    "required": ["agent_type"],
    "additionalProperties": False,
}


def route(client: OpenAI, text: str, model: str = "local-model") -> Agent:
    """Classify user intent into an Agent; falls back to SYSTEM on bad output."""
    try:
        res = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "target_agents", "schema": SCHEMA, "strict": True},
            },
        )
        return Agent(json.loads(res.choices[0].message.content)["agent_type"])
    except Exception:
        return Agent.SYSTEM


def start_chat(
    handlers: dict[Agent, Callable[[str], str]],
    base_url: str = "http://localhost:8080/v1",
) -> None:
    """Chat loop that routes each message to the matching handler."""
    client = OpenAI(base_url=base_url, api_key="not-needed")
    while (text := input("User> ").strip()) not in {"exit", "q"}:
        agent = route(client, text)
        print(f"[{agent.value}] {handlers[agent](text)}")


if __name__ == "__main__":
    start_chat({a: (lambda t, a=a: f"{a.value} agent got: {t}") for a in Agent})
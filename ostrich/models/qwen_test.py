from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",
)

response = client.chat.completions.create(
    model="local-model",
    messages=[
        {
            "role": "system",
            "content": "You select UI elements. Return only a target ID.",
        },
        {
            "role": "user",
            "content": """
Instruction: Click the Search button.

Elements:
[
  {"id": 1, "name": "Search", "role": "push button"},
  {"id": 2, "name": "Address bar", "role": "text"},
  {"id": 3, "name": "Settings", "role": "push button"}
]
""",
        },
    ],
    temperature=0,
    max_tokens=40,
)

print(response.choices[0].message.content)

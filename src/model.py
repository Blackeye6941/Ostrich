import needle

from tools.desktop_navigation import (
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
)

agent = needle.Needle(
    tools=[
        open_app,
        list_windows,
        switch_window,
        maximize_window,
        minimize_window,
        split_screen,
    ]
)


def chat_loop():
    print("=" * 50)
    print("Desktop Navigator Agent CLI")
    print(
        "Type your instruction (e.g. 'open notepad', 'list windows', "
        "'minimize chrome', 'maximize code', 'split screen')."
    )
    print("Type 'exit' or 'quit' to leave.")
    print("=" * 50)

    while True:
        try:
            user_input = input("\nYou > ").strip()
            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit", "q"}:
                print("Goodbye!")
                break

            response = agent.run(user_input)

            if isinstance(response, dict) and "results" in response:
                print(f"Agent > {response['results']}")
            else:
                print(f"Agent > {response}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting chat. Goodbye!")
            break
        except Exception as err:
            print(f"Error: {err}")


if __name__ == "__main__":
    chat_loop()

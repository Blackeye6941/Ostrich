from .models.registry import load_needle_model

agent = load_needle_model()

while True:
    user = str(input("User> "))

    if user in ['exit', 'q']:
        break

    response = agent.run(user)
    print(response)








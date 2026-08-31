import mlflow

mlflow.crewai.autolog()

# Optional: Set a tracking URI and an experiment name if you have a tracking server
mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment("CrewAI")
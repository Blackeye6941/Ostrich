import os
import platform
from crewai import LLM, Agent, Task, Crew, Process
from crewai.project import CrewBase, agent, task, crew
import mlflow

llm = LLM(
    model="gemini/gemini-3.5-flash",
    api_key=os.environ["GEMINI_API_KEY"],
    temperature = 0.4
)

@CrewBase
class CodeCrew:
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def code_generator(self) -> Agent:
        return Agent(
            config=self.agents_config['code_generator'],
            llm=llm
        )
    @task
    def code_generator_task(self) -> Task:
        return Task(
            config=self.tasks_config['generate_script_task'],
            agent=self.code_generator()
        )
    @crew 
    def crew(self) -> Crew:
        return Crew(
            agents = self.agents,
            tasks = self.tasks,
            process = Process.sequential,
            verbose = True,
            max_rpm=3,
        )
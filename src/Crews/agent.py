from crewai import LLM, Agent, Task, Crew, Process
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import FileWriterTool
from config.vars import vars

llm = LLM(
    model="gemini/gemini-3.5-flash",
    api_key=vars['GEMINI_API_KEY'],
    temperature=0.1
)

@CrewBase
class OstrichCrew():
    "The Ostrich Crew is responsible for generating appropriate bash/python code based on user's prompt and write to a file"

    agents_config="../config/agents.yaml"
    tasks_config="../config/tasks.yaml"

    @agent
    def code_generator(self) -> Agent:
        return Agent(
            config=self.agents_config['code_generator'],
            llm=llm,
            tools=[
                FileWriterTool()
            ],
            max_rpm=3
        )
    
    @task
    def generate_code(self) -> Task:
        return Task(
            config=self.tasks_config['generate_script_task'],
            agent=self.code_generator()
        )

    @crew
    def ostrich_crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            max_rpm=3
        )

if __name__ == "__main__":

    inputs = {
        "target_os": "linux",
        "voice_command": "Can you open google chrome"
    }

    crew = OstrichCrew()
    crew.ostrich_crew().kickoff(inputs=inputs)
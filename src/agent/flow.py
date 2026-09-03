from pydantic import BaseModel
from crewai.flow.flow import Flow, listen, start
from agent.crews.code_crew.code_generator import CodeCrew
import platform
import os
from pathlib import Path
import uuid

class State(BaseModel):
    os: str = ""
    command: str = ""
    script_path: str = ""
    is_destructive: bool = False
    user_approved: bool = False
    output: str = ""


class OstrichFlow(Flow[State]):
    """Flow for execution of User commands"""

    @start()
    def get_user_input(self):
        """Get user Command for script generation"""
        print("Getting inputs")
        self.state.command = input("Enter command to perform: ")
        if not self.state.os:
            self.state.os = platform.system()
        return self.state

    @listen(get_user_input)
    def generate_code(self):
        """Generate script and add it to temp file"""
        result = CodeCrew().crew().kickoff(
            inputs = {
                'text_command' : self.state.command,
                'target_os' : self.state.os
            }
        )

        #Create Output Dir if not exists
        output_dir = Path.home() / "temp_ostrich"
        output_dir.mkdir(exist_ok=True, parents=True)

        #Create a unique filepath and write script
        id = uuid.uuid4()
        file_path = output_dir / f"script_{id}.sh"
        file_path.write_text(result.raw)
        
        #Save script path to state
        self.state.script_path = str(file_path)
        return self.state.script_path

    """def plan(self):
        pass

    @listen
    def safety_check():
        pass

    @listen
    def execute():
        pass

    @listen
    def review():
        pass
    """

def kickoff():
    """Run Ostrich flow"""
    OstrichFlow().kickoff()
    print("=====Flow COmplete=====")

if __name__ == "__main__":
    kickoff()


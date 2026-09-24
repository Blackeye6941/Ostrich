from pydantic import BaseModel
from crewai.flow.flow import Flow, listen, start
from agent.crews.code_crew.code_generator import CodeCrew
from crewai.experimental import ConversationState
from crewai.experimental.conversational import ConversationConfig
import platform
import os
from pathlib import Path
import uuid
import subprocess
import mlflow
import time
import select

mlflow.crewai.autolog()

class Window(BaseModel):
    id: str
    app: str
    handle: str
    title: str
    status: str

class LastAction(BaseModel):
    type: str
    window_id: str
    element: str

class ActionState(BaseModel):
    id: str
    type: str
    params: dict
    window_id: str
    requires_approval: bool
    status: str

class DesktopState(ConversationState):
    os: str = ""
    windows: Window
    active_window: str
    last_action: LastAction

   
@ConversationConfig(defer_trace_finalization=True)
class OstrichFlow(Flow[State]):
    """Flow for execution of User commands"""

    _shell_process: subprocess.Popen | None = None  # not a pydantic field, just an instance attr

    def _get_shell(self):
        if self._shell_process is None or self._shell_process.poll() is not None:
            self._shell_process = subprocess.Popen(
                ["bash"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        return self._shell_process

    conversational = True

    @start()
    def platform_setup(self):
        """Get user Command for script generation"""
        if not self.state.os:
            self.state.os = platform.system()
        return self.state

    @listen(platform_setup)
    def generate_code(self):
        """Generate script and add it to temp file"""
        result = CodeCrew().crew().kickoff(
            inputs = {
                'text_command' : self.state.current_user_message,
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

    @listen(generate_code)
    def execute_code(self):
        """Executes code in a subprocess"""

        shell = self._get_shell()
        sentinel = f"__DONE_{uuid.uuid4().hex}__"

        command = "bash"

        if self.state.script_path.endswith(".py"):
            command = "python3"

        command = f'{command} "{self.state.script_path}"; echo {sentinel} $?\n'
        shell.stdin.write(command)
        shell.stdin.flush()

        output_lines = []
        exit_code = None
        deadline = time.monotonic() + 30  # your timeout budget

        while time.monotonic() < deadline:
            ready, _, _ = select.select([shell.stdout], [], [], 1.0)
            if not ready:
                continue
            line = shell.stdout.readline()
            if not line:
                break
            if line.startswith(sentinel):
                exit_code = int(line.strip().split()[-1])
                break
            output_lines.append(line)
        else:
            self.state.error = "Script timed out"
            self.state.output = "".join(output_lines)
            return self.state.output

        self.state.output = "".join(output_lines)
        if exit_code != 0:
            self.state.error = f"Script exited with code {exit_code}"
        return self.state.output
        
        
def kickoff():
    """Run Ostrich flow"""
    flow = OstrichFlow()
    flow.chat()

if __name__ == "__main__":
    kickoff()


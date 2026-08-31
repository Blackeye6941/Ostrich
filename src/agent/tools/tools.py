from crewai.tools import BaseTool;
from pydantic import BaseModel, Field
import subprocess

class BackgrounExecInput(BaseModel):
    command: str = Field(..., description="Shell command or script path to execute")

class BackgroundShellTool(BaseTool):
    name: str = "Background Shell Tool"
    description: str = "open a shell in background as a subprocess and executes a command" 
    args_schema: type[BaseModel] = BackgrounExecInput

    def _run(self, command: str) -> str:
        process = subprocess.Popen(
            command, 
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True
        )

        return f"started in background with PID {process.pid}"
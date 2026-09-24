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
    planned_actions: list[ActionState]

   
@ConversationConfig(defer_trace_finalization=True)
class OstrichFlow(Flow[State]):
    """Flow for execution of User commands"""

    conversational = True

    @start()
    def platform_setup(self):
        """Get user Command for script generation"""
        if not self.state.os:
            self.state.os = platform.system()
        return self.state

    @listen(platform_setup)
    def generate_tasks(self):
        """Generate tasks and update the action items"""
        pass
    
    """
    @listen(generate_tasks)
    def check_safety(self):
        pass
    """

    @listen(generate_code)
    def execute_task(self):
        """Executes code in a subprocess"""
        pass

    @listen(execute_task)
    def update_state(self):
        """Update the ui-state"""
        pass
        
        
def kickoff():
    """Run Ostrich flow"""
    flow = OstrichFlow()
    flow.chat()

if __name__ == "__main__":
    kickoff()


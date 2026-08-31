from pydantic import BaseModel, listen, start
from crewai.flow.flow import Flow

class State(BaseModel):
    os: str = "linux"
    script_path: str
    is_destructive: bool = False
    user_approved: bool = False
    output: str


class OstrichFlow(Flow[State]):

    @start
    def plan(self):
        """ Planning Crew """
        pass

    @listen
    def safety_check():
        """ Safety Crew """
        pass

    @listen
    def execute():
        """ Executor Crew """
        pass

    @listen
    def review():
        """ Reviwer crew """
        pass


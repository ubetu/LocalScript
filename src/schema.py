from pydantic import BaseModel, Field
from langgraph.graph import MessagesState
from enum import StrEnum

class State(MessagesState):
    questions: list[str] | None
    answer: str | None
    plan: str
    code: str
    tests: list[str]


# TODO: improve it
class QuestionsSchema(BaseModel):
    questions: list[str] | None = Field(description="Questions that you want to ask.")

class TestsSchema(BaseModel):
    tests: list[str] = Field(description="Your tests to check the plan implementation")



class MessageRequest(BaseModel):
    content: str


class Role(StrEnum):
    USER = "user"
    SYSTEM = "system"

class MessageResponse(BaseModel):
    role: Role
    content: str

class WfVarSchema(BaseModel):
    wf: dict

class SessionCreateRequest(BaseModel):
    wf_var: WfVarSchema

class SessionCreateResponse(BaseModel):
    session_id: str


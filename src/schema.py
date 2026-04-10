from pydantic import BaseModel, Field
from langgraph.graph import MessagesState
from enum import StrEnum


class State(MessagesState):
    pass  # TODO: define state


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
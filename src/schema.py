from pydantic import BaseModel
from langgraph.graph import MessagesState
from enum import StrEnum
from .lua_utils import LuaCheckResult

class State(MessagesState):
    code: str | None
    linter_result: LuaCheckResult
    task: str
    possile_input: str | None

# TODO: improve it
class QuestionsSchema(BaseModel):
    questions: list[str] | None = None

class TaskEntities(BaseModel):
    task: str
    possible_input: str | None = None
    code: str | None = None


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


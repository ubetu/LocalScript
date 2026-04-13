from pydantic import BaseModel
from langgraph.graph import MessagesState
from enum import StrEnum
from .lua.lua_utils import LuaCheckResult
from .lua.lua_tests import LuaRunResult

class State(MessagesState):
    code: str | None
    static_result: LuaCheckResult
    dynamic_result: LuaRunResult
    task: str
    possile_input: str | None
    fix_attempts: int


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


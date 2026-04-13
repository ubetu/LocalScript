from pydantic import BaseModel, Field
from langgraph.graph import MessagesState
from enum import StrEnum
from .lua import LuaCheckResult, LuaRunResult


class State(MessagesState):
    code: str | None
    static_result: LuaCheckResult
    dynamic_result: LuaRunResult
    task: str
    possible_input: str | None
    fix_attempts: int
    json_key: str | None
    formatted_output: str | None


# TODO: improve it
class QuestionsSchema(BaseModel):
    questions: list[str] | None = None

class TaskEntities(BaseModel):
    task: str
    code: str | None = None
    json_key: str | None = None


class MessageRequest(BaseModel):
    content: str


class Role(StrEnum):
    USER = "user"
    SYSTEM = "system"


class ConversationMessage(BaseModel):
    role: Role
    content: str


class WfVarSchema(BaseModel):
    wf: dict

class SessionCreateRequest(BaseModel):
    wf_var: WfVarSchema

class SessionCreateResponse(BaseModel):
    session_id: str


class SessionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    DONE = "done"
    ERROR = "error"


class LuaIssueMessageOut(BaseModel):
    line: int | None = None
    column: int | None = None
    message: str


class LuaIssueOut(BaseModel):
    type: str
    severity: str
    message: LuaIssueMessageOut


class LuaCheckResultOut(BaseModel):
    passed: bool
    exit_code: int
    errors: list[LuaIssueOut] = []
    warnings: list[LuaIssueOut] = []


class LuaRunResultOut(BaseModel):
    success: bool
    output: str | None = None
    error: str | None = None
    line: str | None = None
    column: int | None = None


class CodeResult(BaseModel):
    raw_code: str = Field(description="The raw Lua code without wrapper")
    formatted_output: str = Field(description="JSON-wrapped output: {key: 'lua{...}lua'}")
    static_result: LuaCheckResultOut | None = None
    dynamic_result: LuaRunResultOut | None = None


class MessageResponse(BaseModel):
    status: SessionStatus
    question: str | None = Field(None, description="Set when status=awaiting_input")
    result: CodeResult | None = Field(None, description="Set when status=done")


class SessionStatusResponse(BaseModel):
    session_id: str
    status: SessionStatus
    result: CodeResult | None = None
    question: str | None = None
    error_detail: str | None = None

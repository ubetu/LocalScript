from pydantic import BaseModel, Field
from langgraph.graph import MessagesState
from .lua import LuaCheckResult, LuaRunResult


class ReviewResult(BaseModel):
    is_correct: bool
    concerns: str | None = None


class State(MessagesState):
    code: str | None
    static_result: LuaCheckResult
    dynamic_result: LuaRunResult
    review_result: ReviewResult | None
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
    possible_input: str | None = None
    json_key: str | None = None


class MessageRequest(BaseModel):
    content: str
    session_id: str | None = Field(
        None,
        description="Optional session ID for follow-up messages. If not provided, a new session will be created.",
    )


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
    formatted_output: str = Field(
        description="JSON-wrapped output: {key: 'lua{...}lua'}"
    )
    static_result: LuaCheckResultOut | None = None
    dynamic_result: LuaRunResultOut | None = None


class MessageResponse(BaseModel):
    question: str | None = Field(
        None, description="Set when agent needs more info from user"
    )
    result: CodeResult | None = Field(None, description="Set when status=done")
    session_id: str = Field(
        description="Session ID to be used for follow-up messages. Should be returned in every response."
    )

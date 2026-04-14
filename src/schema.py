from pydantic import BaseModel, Field
from langgraph.graph import MessagesState
from .lua import LuaCheckResult, LuaRunResult


class ReviewResult(BaseModel):
    is_correct: bool = Field(description="True if the code correctly solves the task, false otherwise.")
    concerns: str | None = Field(None, description="What the code does wrong and what it should do instead. Cite specific lines. Null if is_correct is true.")


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
    qa_performed: bool


class QuestionsSchema(BaseModel):
    reasoning: str = Field(description="Step-by-step analysis before deciding whether to ask questions")
    questions: list[str] | None = Field(None, description="Clarifying questions to ask the user. Null or empty if the task is clear enough to write code.")

class TaskEntities(BaseModel):
    reasoning: str = Field(description="Step-by-step analysis before extracting fields.")
    task: str = Field(description="The task description exactly as the user wrote it, without JSON context and without code.")
    code: str | None = Field(None, description="Existing Lua code the user wants to modify. Null if the user asks to write new code.")
    possible_input: str | None = Field(None, description="The JSON context provided by the user (wf.vars / wf.initVariables). Null if not provided.")
    json_key: str | None = Field(None, description="Single JSON key indicating where to store the result (e.g. 'result'). Not a path. Null if not specified.")


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

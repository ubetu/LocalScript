from typing import Any

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
    questions: list[str] | None = Field(None, description="Clarifying questions to ask the user. If reasoning identified missing or ambiguous information, this MUST be a non-empty list. Null only if the task is fully clear and no questions are needed.")

class TaskEntities(BaseModel):
    reasoning: str = Field(description="Step-by-step analysis before extracting fields.")
    task: str = Field(description="The task description exactly as the user wrote it, without JSON context and without code.")
    json_key: str | None = Field(None, description="Single JSON key indicating where to store the result (e.g. 'result'). Not a path. Null if not specified.")


class MessageRequest(BaseModel):
    content: str
    session_id: str | None = Field(
        None,
        description="Optional session ID for follow-up messages. If not provided, a new session will be created.",
    )
    wf_context: dict[str, Any] | None = Field(
        None,
        description="Optional wf.vars JSON context (e.g. {\"wf\": {\"vars\": {...}}}). "
                    "Passed directly to the graph, skipping LLM extraction.",
    )
    existing_code: str | None = Field(
        None,
        description="Optional pre-existing Lua code in lua{...}lua format. "
                    "Unwrapped and passed directly to the graph, skipping LLM extraction.",
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


class DebugInfo(BaseModel):
    raw_code: str = Field(description="Raw Lua code without lua{...}lua wrapper")
    static_result: LuaCheckResultOut | None = None
    dynamic_result: LuaRunResultOut | None = None


class MessageResponse(BaseModel):
    session_id: str = Field(
        description="Session ID to be used for follow-up messages. Should be returned in every response."
    )
    question: str | None = Field(
        None, description="Set when agent needs more info from user"
    )
    result: dict[str, Any] | None = Field(
        None, description="Parsed lua{...}lua output, e.g. {\"key\": \"lua{...}lua\"}. Set when done."
    )
    debug: DebugInfo | None = Field(
        None, description="Present only when LOCALSCRIPT_DEBUG is set"
    )

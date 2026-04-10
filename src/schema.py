from pydantic import BaseModel, Field
from langgraph.graph import MessagesState
from enum import StrEnum
from .lua_utils import LuaCheckResult
from .lua_tests import TestSuiteResult

class State(MessagesState):
    plan: str
    code: str
    test: TestSchema
    linter_result: LuaCheckResult
    test_result: TestSuiteResult | None


# TODO: improve it
class QuestionsSchema(BaseModel):
    questions: list[str] | None = Field(description="Questions that you want to ask.")

class TestSchema(BaseModel):
    input: str = Field()
    output: str = Field()


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


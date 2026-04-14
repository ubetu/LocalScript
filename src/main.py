import json
import uuid
from dataclasses import dataclass

from fastapi import FastAPI
from langchain_core.messages import HumanMessage

from .graph import graph
from .schema import (
    CodeResult,
    LuaCheckResultOut,
    LuaIssueMessageOut,
    LuaIssueOut,
    LuaRunResultOut,
    MessageRequest,
    MessageResponse,
)

import logging
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="LocalScript API",
    description="Generate and validate Lua scripts through an LLM-driven agentic pipeline.",
    version="0.1.0",

)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _to_code_result(state_values: dict) -> CodeResult:
    raw_code = state_values.get("code") or ""
    formatted_output = state_values.get("formatted_output") or ""

    static = state_values.get("static_result")
    static_out = None
    if static is not None:
        static_out = LuaCheckResultOut(
            passed=static.passed,
            exit_code=static.exit_code,
            errors=[
                LuaIssueOut(
                    type=e.type,
                    severity=e.severity,
                    message=LuaIssueMessageOut(
                        line=e.message.line,
                        column=e.message.column,
                        message=e.message.message,
                    ),
                )
                for e in static.errors
            ],
            warnings=[
                LuaIssueOut(
                    type=w.type,
                    severity=w.severity,
                    message=LuaIssueMessageOut(
                        line=w.message.line,
                        column=w.message.column,
                        message=w.message.message,
                    ),
                )
                for w in static.warnings
            ],
        )

    dynamic = state_values.get("dynamic_result")
    dynamic_out = None
    if dynamic is not None:
        dynamic_out = LuaRunResultOut(
            success=dynamic.success,
            output=dynamic.output,
            error=dynamic.error,
            line=dynamic.line,
            column=dynamic.column,
        )

    return CodeResult(
        raw_code=raw_code,
        formatted_output=formatted_output,
        static_result=static_out,
        dynamic_result=dynamic_out,
    )


async def _invoke(session_id: str, graph_input) -> MessageResponse:
    config = _config(session_id)

    result = await graph.ainvoke(graph_input, config)

    if "__interrupt__" in result:
        question = str(result["__interrupt__"][0].value)
        return MessageResponse(question=question, result=None, session_id=session_id)

    state = graph.get_state(config)
    if state.next == ():
        return MessageResponse(result=_to_code_result(state.values), question=None, session_id=session_id)

    return MessageResponse(result=None, question=None, session_id=session_id)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/generate", response_model=MessageResponse)
async def generate(request: MessageRequest) -> MessageResponse:
    session_id = request.session_id or str(uuid.uuid4())[:8]
    graph_input = {"messages": [HumanMessage(content=request.content)]}
    result =  await _invoke(session_id, graph_input)
    return result


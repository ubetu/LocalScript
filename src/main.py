import json
import logging
import os
import uuid

from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from .graph import graph
from .lua import unwrap_lua_code
from .schema import (
    DebugInfo,
    LuaCheckResultOut,
    LuaIssueMessageOut,
    LuaIssueOut,
    LuaRunResultOut,
    MessageRequest,
    MessageResponse,
)

logging.basicConfig(level=logging.INFO)

_DEBUG = bool(os.getenv("LOCALSCRIPT_DEBUG"))

app = FastAPI(
    title="LocalScript API",
    description="Generate and validate Lua scripts through an LLM-driven agentic pipeline.",
    version="0.1.0",

)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(session_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": session_id}}


def _build_debug(state_values: dict) -> DebugInfo:
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

    return DebugInfo(
        raw_code=state_values.get("code") or "",
        static_result=static_out,
        dynamic_result=dynamic_out,
    )


async def _invoke(session_id: str, graph_input) -> MessageResponse:
    config = _config(session_id)

    result = await graph.ainvoke(graph_input, config)

    if "__interrupt__" in result:
        question = str(result["__interrupt__"][0].value)
        return MessageResponse(question=question, session_id=session_id)

    state = graph.get_state(config)
    if state.next == ():
        formatted_output = state.values.get("formatted_output") or ""
        result_dict = json.loads(formatted_output) if formatted_output else None
        debug = _build_debug(state.values) if _DEBUG else None
        return MessageResponse(result=result_dict, debug=debug, session_id=session_id)

    return MessageResponse(session_id=session_id)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/generate", response_model=MessageResponse)
async def generate(request: MessageRequest) -> MessageResponse:
    session_id = request.session_id or str(uuid.uuid4())[:8]
    graph_input: dict = {"messages": [HumanMessage(content=request.content)]}

    if request.wf_context is not None:
        graph_input["possible_input"] = json.dumps(request.wf_context, ensure_ascii=False)

    if request.existing_code is not None:
        code = unwrap_lua_code(request.existing_code)
        if request.session_id is None:
            graph_input["code"] = code
        else:
            graph_input["messages"] = [HumanMessage(
                content=request.content + f"\n\nExisting code:\n```lua\n{code}\n```"
            )]

    result = await _invoke(session_id, graph_input)
    return result


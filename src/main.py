import json
import uuid
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from .graph import graph
from .schema import (
    CodeResult,
    ConversationMessage,
    LuaCheckResultOut,
    LuaIssueMessageOut,
    LuaIssueOut,
    LuaRunResultOut,
    MessageRequest,
    MessageResponse,
    Role,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStatus,
    SessionStatusResponse,
)

app = FastAPI(
    title="LocalScript API",
    description="Generate and validate Lua scripts through an LLM-driven agentic pipeline.",
    version="0.1.0",
)


# ── Session registry ──────────────────────────────────────────────────────────

@dataclass
class SessionMeta:
    session_id: str
    wf_var_json: str
    status: SessionStatus = SessionStatus.PENDING


sessions: dict[str, SessionMeta] = {}


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
    session = sessions[session_id]
    config = _config(session_id)

    session.status = SessionStatus.RUNNING
    result = await graph.ainvoke(graph_input, config)

    if "__interrupt__" in result:
        question = str(result["__interrupt__"][0].value)
        session.status = SessionStatus.AWAITING_INPUT
        return MessageResponse(status=SessionStatus.AWAITING_INPUT, question=question)

    state = graph.get_state(config)
    if state.next == ():
        session.status = SessionStatus.DONE
        return MessageResponse(status=SessionStatus.DONE, result=_to_code_result(state.values))

    session.status = SessionStatus.ERROR
    return MessageResponse(status=SessionStatus.ERROR)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post(
    "/sessions",
    response_model=SessionCreateResponse,
    status_code=201,
    summary="Create a new code generation session",
    tags=["sessions"],
)
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    sid = uuid.uuid4().hex[:12]
    wf_json = json.dumps({"wf": request.wf_var.wf})
    sessions[sid] = SessionMeta(session_id=sid, wf_var_json=wf_json)
    return SessionCreateResponse(session_id=sid)


@app.get(
    "/sessions/{session_id}",
    response_model=SessionStatusResponse,
    summary="Get session status and result",
    tags=["sessions"],
)
async def get_session(session_id: str) -> SessionStatusResponse:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions[session_id]
    config = _config(session_id)

    result = None
    question = None

    if session.status == SessionStatus.DONE:
        state = graph.get_state(config)
        result = _to_code_result(state.values)
    elif session.status == SessionStatus.AWAITING_INPUT:
        state = graph.get_state(config)
        if state.interrupts:
            question = str(state.interrupts[0].value)

    return SessionStatusResponse(
        session_id=session_id,
        status=session.status,
        result=result,
        question=question,
    )


@app.post(
    "/sessions/{session_id}/messages",
    response_model=MessageResponse,
    summary="Send a message and drive the pipeline",
    description=(
        "Starts the graph on first call. If the graph needs clarification "
        "(status=awaiting_input), send the answer as the next message to resume. "
        "Returns status=done with the generated Lua code when complete."
    ),
    tags=["messages"],
)
async def send_message(session_id: str, message: MessageRequest) -> MessageResponse:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions[session_id]

    if session.status == SessionStatus.AWAITING_INPUT:
        return await _invoke(session_id, Command(resume=message.content))

    if session.status in (SessionStatus.DONE, SessionStatus.ERROR):
        raise HTTPException(status_code=409, detail=f"Session already in terminal state: {session.status}")

    combined = f"{message.content}\n\nContext: {session.wf_var_json}"
    return await _invoke(session_id, {"messages": [HumanMessage(content=combined)]})


@app.get(
    "/sessions/{session_id}/messages",
    response_model=list[ConversationMessage],
    summary="Get conversation history",
    tags=["messages"],
)
async def get_messages(session_id: str) -> list[ConversationMessage]:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    config = _config(session_id)
    try:
        state = graph.get_state(config)
    except Exception:
        return []
    messages = []
    for msg in state.values.get("messages", []):
        role = Role.USER if msg.type == "human" else Role.SYSTEM
        messages.append(ConversationMessage(role=role, content=msg.content))
    return messages

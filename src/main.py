from fastapi import FastAPI, HTTPException
from schema import State, SessionCreateRequest, SessionCreateResponse, MessageResponse, MessageRequest

import uuid

app = FastAPI()

SESSION_TTL = 1800
sessions: dict[str, State] = {}

@app.post("/sessions")
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    sid = str(uuid.uuid4().hex[:12])
    sessions[sid] = State()
    return SessionCreateResponse(session_id=sid)

@app.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, message: MessageRequest) -> MessageResponse:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    state = sessions[session_id]
    state.add_message("user", message.content)
    return MessageResponse(content="Message received")

@app.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str) -> list[MessageResponse]:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    state = sessions[session_id]
    return [MessageResponse(role=msg.role, content=msg.content) for msg in state.messages]
"""
Chat API:
  POST /chat/start
  POST /chat/end
  WS   /chat/ws/{session_id}
  GET  /chat/sessions
  GET  /chat/session/{id}/messages
  DELETE /chat/session/{id}
"""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.cache_service import cache
from app.services.llm_service import llm_service
from app.services.mcp_service import mcp_service
from app.core.security import get_current_user_id
from app.core.logging import get_logger
from app.core.config import get_settings

# LangGraph Agent
from app.agents.graph import agent_graph

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)
settings = get_settings()

MAX_MESSAGE_BYTES = 32_768  # 32 KB — reject oversized payloads early


# ─────────────────────────────────────────────────────────────
# Connection Manager
# ─────────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self._connections: dict = {}

    async def connect(self, ws: WebSocket, session_id: str):
        await ws.accept()
        self._connections[session_id] = ws
        logger.debug(f"WS connected: {session_id}")

    def disconnect(self, session_id: str):
        self._connections.pop(session_id, None)
        logger.debug(f"WS disconnected: {session_id}")

    async def send_json(self, session_id: str, data: dict):
        ws = self._connections.get(session_id)
        if ws:
            await ws.send_text(json.dumps(data))

    async def send_error(self, session_id: str, error: str):
        await self.send_json(session_id, {"type": "error", "text": error})


manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────
# Session Lifecycle
# ─────────────────────────────────────────────────────────────
@router.post("/start")
async def start_session(user_id: int = Depends(get_current_user_id)):
    session_id = cache.create_session(user_id)
    logger.info(f"Session started: {session_id}")
    return {"session_id": session_id}


@router.post("/end")
async def end_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if not cache.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = cache.end_session(session_id)
    session_data["session_id"] = session_id

    if session_data["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your session")

    await mcp_service.save_session(db, session_data)

    logger.info(f"Session saved: {session_id}")
    return {"message": "Session saved"}


# ─────────────────────────────────────────────────────────────
# Session History
# ─────────────────────────────────────────────────────────────
@router.get("/sessions")
async def list_sessions(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await mcp_service.get_user_sessions(db, user_id=user_id)


@router.get("/session/{session_id}/messages")
async def session_messages(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if cache.session_exists(session_id):
        data = cache.get_session(session_id)
        if data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not your session")
        return cache.get_conversation(session_id)

    return await mcp_service.get_session_messages(db, session_id=session_id)


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await mcp_service.delete_session(db, session_id=session_id)
    return {"message": "Session deleted"}


# ─────────────────────────────────────────────────────────────
# WebSocket Chat (LangGraph + Streaming)
# ─────────────────────────────────────────────────────────────
async def _heartbeat(websocket: WebSocket, session_id: str, interval: int):
    """Send periodic pings so idle connections don't silently drop."""
    try:
        while True:
            await asyncio.sleep(interval)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except Exception:
        pass  # connection already closed — heartbeat task will be cancelled


@router.websocket("/ws/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    await manager.connect(websocket, session_id)

    # Validate session
    if not cache.session_exists(session_id):
        await manager.send_error(session_id, "Invalid or expired session")
        await websocket.close()
        manager.disconnect(session_id)
        return

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(
        _heartbeat(websocket, session_id, settings.WS_HEARTBEAT_INTERVAL)
    )

    try:
        while True:
            raw = await websocket.receive_text()

            # ── Size guard ──────────────────────────────────────────
            if len(raw.encode()) > MAX_MESSAGE_BYTES:
                await manager.send_error(session_id, "Message too large")
                continue

            # ── Parse payload ───────────────────────────────────────
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"message": raw}

            # Ignore client pong frames
            if payload.get("type") == "pong":
                continue

            user_message = payload.get("message", "")
            mode = payload.get("mode", "auto")
            file_path = payload.get("file_path")

            if not user_message.strip():
                continue

            user_id = cache.get_user_id(session_id)

            # Store user message
            cache.add_message(session_id, "user", user_message)

            # ── Always initialise both variables before branching ────
            tokens: int = 0
            response_text: str = ""

            # ── LangGraph path (dataset present) ────────────────────
            if file_path:
                try:
                    state = {
                        "user_id": user_id,
                        "message": user_message,
                        "mode": mode,
                        "file_path": file_path,
                        "logs": [],
                        "retry_count": 0,
                    }

                    result = await agent_graph.ainvoke(state)

                    # Stream execution logs
                    for log in result.get("logs", []):
                        await manager.send_json(session_id, {"type": "step", "text": log})

                    response_text = result.get("final", "")
                    # tokens stays 0 for the agent path (no LLM token count exposed)

                except Exception as e:
                    logger.exception("LangGraph execution failed")
                    await manager.send_error(session_id, str(e))
                    continue

            # ── LLM fallback (no dataset) ────────────────────────────
            else:
                try:
                    current_conv = cache.get_conversation(session_id)

                    full_context = await mcp_service.build_context(
                        db,
                        user_id=user_id,
                        current_message=user_message,
                        current_conversation=current_conv,
                    )

                    result = await llm_service.generate(full_context)

                    response_text = result["text"]
                    tokens = result["tokens"]

                except Exception as e:
                    logger.exception("LLM generation failed")
                    await manager.send_error(session_id, str(e))
                    continue

            # Store assistant message
            cache.add_message(session_id, "assistant", response_text, tokens=tokens)

            # Send final response
            await manager.send_json(session_id, {
                "type": "final",
                "text": response_text,
                "tokens": tokens,
                "mode": mode,
            })

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: {session_id}")

    except Exception as e:
        logger.exception(f"WS error: {e}")

    finally:
        heartbeat_task.cancel()
        manager.disconnect(session_id)
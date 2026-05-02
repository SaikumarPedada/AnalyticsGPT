"""
MCP (Memory & Context Persistence) service.
Responsible for:
  - Saving sessions + messages to PostgreSQL
  - Querying conversation history for context window reconstruction
  - Indexing messages into Qdrant for semantic retrieval
  - Building the full context (sliding window + semantic hits) for the LLM
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime
from typing import List, Dict, Optional
import json

from app.models import ChatSession, Message, User, UserMemory
from app.services.qdrant_service import qdrant_service
from app.services.embedding_service import embedding_service
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


class MCPService:

    # ── Save session ──────────────────────────────────────────────────────────
    async def save_session(self, db: AsyncSession, session_data: dict) -> None:
        """
        Persist a completed session:
        1. Insert ChatSession row
        2. Batch-insert all Message rows
        3. Index message embeddings into Qdrant
        4. Update user.last_session_ended
        """
        session_id = session_data["session_id"]
        user_id = session_data["user_id"]
        conversation = session_data.get("conversation", [])

        # Generate a title from the first user message
        first_user = next((m["content"] for m in conversation if m["role"] == "user"), None)
        title = (first_user[:72] + "…") if first_user and len(first_user) > 72 else first_user

        session_row = ChatSession(
            session_id=session_id,
            user_id=user_id,
            title=title,
            session_start=session_data["start_time"],
            session_end=datetime.utcnow(),
            tokens_consumed=session_data.get("tokens", 0),
            tools_used=json.dumps(session_data.get("tools", [])),
        )
        db.add(session_row)
        await db.flush()   # get session_id into DB before messages FK

        messages = []
        for msg in conversation:
            m = Message(
                session_id=session_id,
                user_id=user_id,
                role=msg["role"],
                content=msg["content"],
                tokens=msg.get("tokens", 0),
            )
            messages.append(m)

        db.add_all(messages)
        await db.flush()   # get message_ids back

        # Update last_session_ended on the user
        await db.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(last_session_ended=datetime.utcnow())
        )

        await db.commit()

        # Async index into Qdrant (best-effort, don't block commit)
        try:
            await self._index_session_to_qdrant(messages)
        except Exception as e:
            logger.warning(f"Qdrant indexing skipped: {e}")

        logger.info(f"Session {session_id} saved ({len(messages)} messages, {session_data.get('tokens', 0)} tokens)")

    # ── Qdrant indexing ───────────────────────────────────────────────────────
    async def _index_session_to_qdrant(self, messages: List[Message]) -> None:
        """Embed all messages and upsert into Qdrant."""
        points = []
        for msg in messages:
            if not msg.content or not msg.message_id:
                continue
            vector = embedding_service.embed(msg.content)
            points.append({
                "id": msg.message_id,
                "vector": vector,
                "user_id": msg.user_id,
                "session_id": msg.session_id,
                "role": msg.role,
                "content": msg.content,
            })
        if points:
            qdrant_service.upsert_batch(points)

    # ── Context reconstruction ────────────────────────────────────────────────
    async def build_context(
        self,
        db: AsyncSession,
        user_id: int,
        current_message: str,
        current_conversation: List[Dict],
        history_limit: int = None,
    ) -> List[Dict]:
        """
        Combine:
          1. Semantic hits from Qdrant (relevant past messages)
          2. Sliding-window recent messages from PostgreSQL
          3. Current in-progress conversation from cache
        Deduplicated and ordered chronologically.
        """
        limit = history_limit or settings.MCP_HISTORY_LIMIT

        # 1. Semantic retrieval
        semantic_hits = []
        try:
            query_vec = embedding_service.embed(current_message)
            hits = qdrant_service.search(query_vec, user_id=user_id, limit=5)
            semantic_hits = [{"role": h["role"], "content": h["content"]} for h in hits]
        except Exception as e:
            logger.warning(f"Semantic retrieval skipped: {e}")

        # 2. Recent history from DB
        recent = await self.get_last_messages(db, user_id=user_id, limit=limit)

        # 3. Deduplicate: prefer recent window over semantic hits
        recent_contents = {m["content"] for m in recent}
        unique_semantic = [m for m in semantic_hits if m["content"] not in recent_contents]

        # Build final context: [semantic background | recent history | current turn]
        return unique_semantic + recent + current_conversation

    # ── History queries ───────────────────────────────────────────────────────
    async def get_last_messages(
        self, db: AsyncSession, user_id: int, limit: int = 10
    ) -> List[Dict]:
        result = await db.execute(
            select(Message)
            .where(Message.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = result.scalars().all()
        return [{"role": m.role, "content": m.content} for m in reversed(messages)]

    async def get_session_messages(
        self, db: AsyncSession, session_id: str
    ) -> List[Dict]:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()
        return [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "tokens": m.tokens,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]

    async def get_user_sessions(
        self, db: AsyncSession, user_id: int, limit: int = 50
    ) -> List[Dict]:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
            .limit(limit)
        )
        sessions = result.scalars().all()
        return [
            {
                "session_id": s.session_id,
                "title": s.title,
                "session_start": s.session_start.isoformat() if s.session_start else None,
                "session_end": s.session_end.isoformat() if s.session_end else None,
                "tokens_consumed": s.tokens_consumed,
                "created_at": s.created_at.isoformat(),
            }
            for s in sessions
        ]

    async def delete_session(self, db: AsyncSession, session_id: str) -> None:
        # Delete Qdrant vectors first
        try:
            qdrant_service.delete_session_vectors(session_id)
        except Exception as e:
            logger.warning(f"Qdrant delete skipped: {e}")

        await db.execute(Message.__table__.delete().where(Message.session_id == session_id))
        await db.execute(ChatSession.__table__.delete().where(ChatSession.session_id == session_id))
        await db.commit()
        logger.info(f"Session {session_id} deleted")

    # ── User memory ───────────────────────────────────────────────────────────
    async def get_user_memory(self, db: AsyncSession, user_id: int) -> List[Dict]:
        result = await db.execute(
            select(UserMemory).where(UserMemory.user_id == user_id)
        )
        return [{"key": m.key, "value": m.value} for m in result.scalars().all()]

    async def upsert_user_memory(
        self, db: AsyncSession, user_id: int, key: str, value: str, session_id: Optional[str] = None
    ) -> None:
        existing = await db.execute(
            select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == key)
        )
        row = existing.scalar_one_or_none()
        if row:
            row.value = value
            row.source_session_id = session_id
        else:
            db.add(UserMemory(user_id=user_id, key=key, value=value, source_session_id=session_id))
        await db.commit()


mcp_service = MCPService()

"""
Semantic memory via Qdrant.
Each vector point = one message, payload carries metadata.
Used to surface relevant past context beyond the sliding-window history.
"""
from typing import List, Dict, Optional
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


class QdrantService:
    def __init__(self):
        self.client = None
        self.collection = settings.QDRANT_COLLECTION

    def _get_client(self):
        if self.client:
            return self.client
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self.client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

        # Create collection if it does not exist
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection not in existing:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=settings.QDRANT_VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Qdrant collection created: {self.collection}")
        return self.client

    # ── Upsert ────────────────────────────────────────────────────────────────
    def upsert_message(
        self,
        message_id: int,
        embedding: List[float],
        user_id: int,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        from qdrant_client.models import PointStruct

        client = self._get_client()
        client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(
                    id=message_id,
                    vector=embedding,
                    payload={
                        "user_id": user_id,
                        "session_id": session_id,
                        "role": role,
                        "content": content,
                    },
                )
            ],
        )

    def upsert_batch(self, points: List[Dict]) -> None:
        """
        points: list of dicts with keys:
          id, vector, user_id, session_id, role, content
        """
        from qdrant_client.models import PointStruct

        client = self._get_client()
        client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload={
                        "user_id": p["user_id"],
                        "session_id": p["session_id"],
                        "role": p["role"],
                        "content": p["content"],
                    },
                )
                for p in points
            ],
        )

    # ── Search ────────────────────────────────────────────────────────────────
    def search(
        self,
        query_vector: List[float],
        user_id: int,
        limit: int = 5,
        score_threshold: float = 0.55,
    ) -> List[Dict]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = self._get_client()
        results = client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return [
            {
                "score": r.score,
                "role": r.payload["role"],
                "content": r.payload["content"],
                "session_id": r.payload["session_id"],
            }
            for r in results
        ]

    # ── Delete ────────────────────────────────────────────────────────────────
    def delete_session_vectors(self, session_id: str) -> None:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = self._get_client()
        client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
            ),
        )

    def health(self) -> bool:
        try:
            self._get_client()
            return True
        except Exception:
            return False


qdrant_service = QdrantService()

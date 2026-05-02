import os
from typing import List
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


class EmbeddingService:
    def __init__(self):
        self.model = None

    def load_model(self) -> None:
        if self.model:
            return

        from sentence_transformers import SentenceTransformer

        if os.path.exists(settings.BGE_MODEL_PATH):
            logger.info(f"Loading embedding model from local path: {settings.BGE_MODEL_PATH}")
            self.model = SentenceTransformer(settings.BGE_MODEL_PATH)
        else:
            logger.info(f"Downloading embedding model: {settings.EMBEDDING_MODEL_NAME}")
            self.model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME, device="cpu")

        logger.info("Embedding model ready")

    def embed(self, text: str) -> List[float]:
        self.load_model()
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        self.load_model()
        return self.model.encode(texts, normalize_embeddings=True).tolist()


embedding_service = EmbeddingService()

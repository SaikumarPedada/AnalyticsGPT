import os
import sys
import time
import subprocess
import socket
import gc
from typing import List
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

DAEMON_URL = "http://127.0.0.1:8001"


class EmbeddingService:
    def __init__(self):
        self.model = None
        self.last_accessed = time.time()
        self.daemon_started = False

    def _is_daemon_running(self) -> bool:
        """Check if the daemon port 8001 is open and accepting TCP connections."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", 8001))
            s.close()
            return True
        except Exception:
            return False

    def _start_daemon(self) -> None:
        """Spawn the daemon process as a background task."""
        if self.daemon_started:
            return

        logger.info("Spawning embedding daemon process on port 8001...")
        try:
            # Spawn daemon script
            cmd = [sys.executable, "-m", "app.services.embedding_daemon"]
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                close_fds=True
            )
            self.daemon_started = True
            # Allow a brief moment for startup
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Failed to spawn embedding daemon: {e}")

    def load_model(self) -> None:
        """In-process loader fallback with 1 hour idle check."""
        self.last_accessed = time.time()
        if self.model:
            return

        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model in-process: {settings.EMBEDDING_MODEL_NAME}")
        self.model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME, device="cpu")
        logger.info("In-process embedding model ready")

    def _check_inprocess_idle_timeout(self) -> None:
        """Unload in-process model if idle for more than 1 hour."""
        if self.model and (time.time() - self.last_accessed > 3600):
            logger.info("In-process embedding model unused for 1 hour. Unloading.")
            self.model = None
            gc.collect()

    def embed(self, text: str) -> List[float]:
        self._check_inprocess_idle_timeout()
        self.last_accessed = time.time()

        # Try daemon first
        if not self._is_daemon_running():
            self._start_daemon()

        if self._is_daemon_running():
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(f"{DAEMON_URL}/embed", json={"text": text})
                    if resp.status_code == 200:
                        return resp.json()
            except Exception as e:
                logger.warning(f"Daemon query failed, falling back to local: {e}")

        # Fallback to local load
        self.load_model()
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        self._check_inprocess_idle_timeout()
        self.last_accessed = time.time()

        # Try daemon first
        if not self._is_daemon_running():
            self._start_daemon()

        if self._is_daemon_running():
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(f"{DAEMON_URL}/embed_batch", json={"texts": texts})
                    if resp.status_code == 200:
                        return resp.json()
            except Exception as e:
                logger.warning(f"Daemon batch query failed, falling back to local: {e}")

        # Fallback to local load
        self.load_model()
        return self.model.encode(texts, normalize_embeddings=True).tolist()


embedding_service = EmbeddingService()

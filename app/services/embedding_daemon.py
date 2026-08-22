import sys
import time
import asyncio
import gc
from fastapi import FastAPI, Body
import uvicorn
from sentence_transformers import SentenceTransformer

app = FastAPI()

model = None
last_accessed = time.time()


def load_model():
    global model, last_accessed
    last_accessed = time.time()
    if model is None:
        print("Loading embedding model in daemon...")
        model = SentenceTransformer("BAAI/bge-small-en", device="cpu")
        print("Embedding model loaded in daemon.")


@app.post("/embed")
async def embed(text: str = Body(embed=True)):
    global last_accessed
    load_model()
    last_accessed = time.time()
    return model.encode(text, normalize_embeddings=True).tolist()


@app.post("/embed_batch")
async def embed_batch(texts: list[str] = Body(embed=True)):
    global last_accessed
    load_model()
    last_accessed = time.time()
    return model.encode(texts, normalize_embeddings=True).tolist()


async def check_idle_timeout():
    global model
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        if model is not None and (time.time() - last_accessed > 3600):
            print("Embedding model unused for 1 hour. Unloading to free memory.")
            model = None
            gc.collect()


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(check_idle_timeout())


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    uvicorn.run(app, host="127.0.0.1", port=port)

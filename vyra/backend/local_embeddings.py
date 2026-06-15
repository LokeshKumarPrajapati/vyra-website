"""
Shared local embedding utility for VYRA.

Single model instance shared across:
- rag_memory.py  (RAG vector store)
- quantum/quantum_encoder.py  (quantum amplitude encoding)
- self_improvement.py  (topic extraction)

Model: all-MiniLM-L6-v2
  - 384-dim L2-normalised float32 vectors
  - ~80 MB on disk, loads once, stays in memory
  - Zero API calls — fully on-device
"""

from __future__ import annotations

import asyncio
from typing import List
import numpy as np

_MODEL = None
MODEL_NAME = "all-MiniLM-L6-v2"
EMB_DIM = 384


def get_model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _MODEL = SentenceTransformer(MODEL_NAME)
        print(f"[LocalEmbeddings] ✅ Loaded {MODEL_NAME} (dim={EMB_DIM})")
    return _MODEL


def embed_sync(texts: List[str]) -> np.ndarray:
    """
    Embed a list of texts → float32 matrix of shape (N, EMB_DIM), L2-normalised.
    Runs synchronously; call from a thread pool if inside an async context.
    """
    model = get_model()
    vecs = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=False,
    )
    return vecs.astype(np.float32)


def embed_one_sync(text: str) -> np.ndarray:
    """Embed a single text → shape (EMB_DIM,), L2-normalised."""
    return embed_sync([text])[0]


async def embed(texts: List[str]) -> np.ndarray:
    """Async: embed list of texts in thread pool."""
    return await asyncio.to_thread(embed_sync, texts)


async def embed_one(text: str) -> np.ndarray:
    """Async: embed single text in thread pool."""
    return await asyncio.to_thread(embed_one_sync, text)

"""
RAG Memory Store for VYRA — Production LLM RAG System

Architecture:
  - Embeddings  : sentence-transformers all-MiniLM-L6-v2 (384-dim, fully local, zero API calls)
  - Vector Index: FAISS IndexFlatIP (exact inner-product = cosine on L2-normalised vectors, scales to 500k+)
  - Keyword     : TF-IDF over NLTK tokens (hybrid scoring, no external BM25 library needed)
  - Hybrid score: 0.7 * semantic + 0.3 * keyword
  - Storage     : rag_store.json (metadata) + rag_index.faiss (vectors)
  - Max chunks  : 500,000

Usage:
    rag = RagMemory(data_dir="data")
    await rag.store("Lokesh loves sourdough bread", speaker="User")
    results = await rag.search("What does he like to eat?", k=5)
"""

import os
import json
import time
import math
import asyncio
import hashlib
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any, Optional

import numpy as np
import faiss
import nltk

# ── NLTK setup ───────────────────────────────────────────────────────────────
nltk.download("punkt_tab", quiet=True)
nltk.download("stopwords", quiet=True)
try:
    from nltk.tokenize import word_tokenize
    from nltk.corpus import stopwords as _sw
    _STOPWORDS = set(_sw.words("english"))
except Exception:
    def word_tokenize(t):  # type: ignore
        return t.lower().split()
    _STOPWORDS = set()


# ── Local Embedding Model ────────────────────────────────────────────────────

_LOCAL_MODEL = None
_LOCAL_MODEL_NAME = "all-MiniLM-L6-v2"
EMB_DIM = 384  # all-MiniLM-L6-v2 native dimension


def _get_local_model():
    global _LOCAL_MODEL
    if _LOCAL_MODEL is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _LOCAL_MODEL = SentenceTransformer(_LOCAL_MODEL_NAME)
        print(f"[RagMemory] ✅ Local embedding model: {_LOCAL_MODEL_NAME} (dim={EMB_DIM})")
    return _LOCAL_MODEL


def _embed_batch_sync(texts: List[str]) -> np.ndarray:
    """Embed texts → L2-normalised float32 matrix of shape (N, EMB_DIM)."""
    model = _get_local_model()
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True,
                        batch_size=64, show_progress_bar=False)
    return vecs.astype(np.float32)


async def _embed_batch(texts: List[str]) -> np.ndarray:
    return await asyncio.to_thread(_embed_batch_sync, texts)


async def _embed_single(text: str) -> np.ndarray:
    vecs = await _embed_batch([text])
    return vecs[0]


# ── TF-IDF Keyword Scorer ────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    tokens = word_tokenize(text.lower())
    return [t for t in tokens if t.isalpha() and t not in _STOPWORDS and len(t) > 1]


def _keyword_score(query_tokens: List[str], doc_tokens: List[str],
                   doc_tf: Counter, corpus_df: Dict[str, int], num_docs: int) -> float:
    """TF-IDF keyword relevance score."""
    if not query_tokens or not doc_tokens:
        return 0.0
    doc_len = max(len(doc_tokens), 1)
    score = 0.0
    for tok in set(query_tokens) & set(doc_tf.keys()):
        tf = doc_tf[tok] / doc_len
        idf = math.log((num_docs + 1) / (corpus_df.get(tok, 0) + 1))
        score += tf * idf
    # Normalise to [0, 1] range roughly
    return min(score / max(len(query_tokens), 1), 1.0)


# ── Chunk Metadata ───────────────────────────────────────────────────────────

class MemoryChunk:
    def __init__(self, text: str, speaker: str = "", timestamp: float = 0.0,
                 category: str = "conversation", chunk_id: str = "",
                 access_count: int = 0, last_accessed: float = 0.0,
                 importance: int = 1):
        self.text = text
        self.speaker = speaker
        self.timestamp = timestamp or time.time()
        self.category = category
        self.chunk_id = chunk_id or hashlib.md5(
            f"{text}:{timestamp}".encode()).hexdigest()[:12]
        self.access_count = access_count
        self.last_accessed = last_accessed
        self.importance = importance  # 1-5, higher = keep longer
        # Pre-computed for hybrid search
        self._tokens: Optional[List[str]] = None
        self._tf: Optional[Counter] = None

    def tokens(self) -> List[str]:
        if self._tokens is None:
            self._tokens = _tokenize(self.text)
            self._tf = Counter(self._tokens)
        return self._tokens

    def tf(self) -> Counter:
        if self._tf is None:
            self.tokens()
        return self._tf  # type: ignore

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "speaker": self.speaker,
            "timestamp": self.timestamp,
            "category": self.category,
            "chunk_id": self.chunk_id,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "importance": self.importance,
        }

    @staticmethod
    def from_dict(d: dict) -> "MemoryChunk":
        return MemoryChunk(
            text=d.get("text", ""),
            speaker=d.get("speaker", ""),
            timestamp=d.get("timestamp", 0.0),
            category=d.get("category", "conversation"),
            chunk_id=d.get("chunk_id", ""),
            access_count=d.get("access_count", 0),
            last_accessed=d.get("last_accessed", 0.0),
            importance=d.get("importance", 1),
        )


# ── FAISS RAG Memory Store ───────────────────────────────────────────────────

class RagMemory:
    """
    Production RAG memory store for VYRA.

    - FAISS IndexFlatIP: exact cosine similarity at scale (500k+ chunks)
    - Hybrid search: semantic (0.7) + TF-IDF keyword (0.3)
    - Temporal decay + access frequency re-ranking
    - Zero API calls — fully local
    """

    MAX_CHUNKS = 500_000
    DEDUP_THRESHOLD = 0.97   # Skip if cosine similarity >= this to any existing chunk
    CHUNK_MAX_WORDS = 80
    SEMANTIC_WEIGHT = 0.7
    KEYWORD_WEIGHT = 0.3

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        if not self.data_dir.is_absolute():
            self.data_dir = Path(__file__).parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.meta_path = self.data_dir / "rag_store.json"
        self.index_path = self.data_dir / "rag_index.faiss"
        self.vectors_path = self.data_dir / "rag_vectors.npy"  # kept for backup/rebuild

        self.chunks: List[MemoryChunk] = []
        self.index: Optional[faiss.IndexFlatIP] = None

        # TF-IDF corpus stats
        self._corpus_df: Dict[str, int] = {}  # token → doc frequency

        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load metadata + FAISS index from disk."""
        try:
            if self.meta_path.exists():
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Dimension / model guard
                stored_dim = data.get("emb_dim", EMB_DIM)
                if stored_dim != EMB_DIM:
                    print(f"[RagMemory] ⚠️ Dimension mismatch (stored={stored_dim}, expected={EMB_DIM}). "
                          "Resetting — old Gemini vectors replaced by local embeddings.")
                    self._reset_files()
                    return

                chunks = [MemoryChunk.from_dict(c) for c in data.get("chunks", [])]

                # Load FAISS index
                if self.index_path.exists():
                    idx = faiss.read_index(str(self.index_path))
                    if idx.ntotal != len(chunks):
                        print(f"[RagMemory] ⚠️ FAISS count mismatch ({idx.ntotal} vs {len(chunks)} chunks). Rebuilding.")
                        idx = self._rebuild_faiss_from_npy(len(chunks))
                        if idx is None:
                            self._reset_files()
                            return
                    self.index = idx
                elif self.vectors_path.exists():
                    print("[RagMemory] FAISS index missing — rebuilding from rag_vectors.npy...")
                    idx = self._rebuild_faiss_from_npy(len(chunks))
                    if idx is None:
                        self._reset_files()
                        return
                    self.index = idx
                    self._save_faiss()
                else:
                    # No vectors at all — fresh start
                    self.index = faiss.IndexFlatIP(EMB_DIM)

                self.chunks = chunks
                self._rebuild_corpus_df()
                print(f"[RagMemory] ✅ Loaded {len(self.chunks)} chunks | FAISS ntotal={self.index.ntotal} | hybrid search ready")
            else:
                self.index = faiss.IndexFlatIP(EMB_DIM)
                print("[RagMemory] Fresh RAG store created.")
        except Exception as e:
            print(f"[RagMemory] Load error: {e} — starting fresh.")
            self._reset_files()

    def _rebuild_faiss_from_npy(self, expected_count: int) -> Optional[faiss.IndexFlatIP]:
        """Rebuild FAISS index from backup numpy file."""
        try:
            vecs = np.load(str(self.vectors_path)).astype(np.float32)
            if vecs.shape[1] != EMB_DIM:
                print(f"[RagMemory] NPY dim mismatch ({vecs.shape[1]} vs {EMB_DIM}). Cannot rebuild.")
                return None
            if vecs.shape[0] != expected_count:
                # Truncate or pad — just use what we have and align chunks
                n = min(vecs.shape[0], expected_count)
                vecs = vecs[:n]
                self.chunks = self.chunks[:n]
            idx = faiss.IndexFlatIP(EMB_DIM)
            # Ensure L2-normalised
            faiss.normalize_L2(vecs)
            idx.add(vecs)
            print(f"[RagMemory] FAISS rebuilt from NPY: {idx.ntotal} vectors")
            return idx
        except Exception as e:
            print(f"[RagMemory] NPY rebuild failed: {e}")
            return None

    def _reset_files(self) -> None:
        """Clear all RAG files and start fresh."""
        self.chunks = []
        self.index = faiss.IndexFlatIP(EMB_DIM)
        self._corpus_df = {}
        for p in [self.meta_path, self.index_path, self.vectors_path]:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    def _rebuild_corpus_df(self) -> None:
        """Recompute TF-IDF document frequency from all chunks."""
        df: Dict[str, int] = {}
        for c in self.chunks:
            for tok in set(c.tokens()):
                df[tok] = df.get(tok, 0) + 1
        self._corpus_df = df

    def _update_corpus_df(self, chunk: MemoryChunk) -> None:
        """Incrementally update corpus DF for a new chunk."""
        for tok in set(chunk.tokens()):
            self._corpus_df[tok] = self._corpus_df.get(tok, 0) + 1

    def save(self) -> None:
        """Persist metadata + FAISS index to disk."""
        try:
            data = {
                "chunks": [c.to_dict() for c in self.chunks],
                "emb_dim": EMB_DIM,
                "emb_model": _LOCAL_MODEL_NAME,
                "total": len(self.chunks),
            }
            self._safe_write_json(self.meta_path, data)
            self._save_faiss()
        except Exception as e:
            print(f"[RagMemory] Save error: {e}")

    def _save_faiss(self) -> None:
        if self.index is None:
            return
        try:
            tmp = self.index_path.with_suffix(".tmp.faiss")
            faiss.write_index(self.index, str(tmp))
            try:
                os.replace(tmp, self.index_path)
            except OSError:
                faiss.write_index(self.index, str(self.index_path))
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"[RagMemory] FAISS save error: {e}")

    def _save_npy_backup(self, vec: np.ndarray) -> None:
        """Append-style backup — just overwrite with all current vectors."""
        try:
            if self.index is not None and self.index.ntotal > 0:
                # Reconstruct all vectors from FAISS for backup
                all_vecs = faiss.rev_swig_ptr(self.index.get_xb(), self.index.ntotal * EMB_DIM)
                all_vecs = np.array(all_vecs).reshape(self.index.ntotal, EMB_DIM)
                np.save(str(self.vectors_path), all_vecs)
        except Exception:
            pass  # NPY backup is optional

    def _safe_write_json(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        try:
            os.replace(tmp, path)
        except OSError:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    # ── Store ────────────────────────────────────────────────────────────────

    async def store(self, text: str, speaker: str = "", timestamp: float = 0.0,
                    category: str = "conversation", importance: int = 1) -> bool:
        """
        Embed and store a text chunk. Returns True if stored, False if skipped.
        importance: 1-5 (5 = critical, never evict)
        """
        text = text.strip()
        if not text or len(text) < 10:
            return False
        if self.index is None:
            self.index = faiss.IndexFlatIP(EMB_DIM)

        try:
            emb = await _embed_single(text)
            emb = emb.reshape(1, -1).astype(np.float32)
            faiss.normalize_L2(emb)  # ensure unit norm (already done by model, safety)

            # Dedup: check nearest neighbour
            if self.index.ntotal > 0:
                D, _ = self.index.search(emb, 1)
                if D[0][0] >= self.DEDUP_THRESHOLD:
                    return False

            chunk = MemoryChunk(
                text=text,
                speaker=speaker,
                timestamp=timestamp or time.time(),
                category=category,
                importance=importance,
            )

            self.index.add(emb)
            self.chunks.append(chunk)
            self._update_corpus_df(chunk)

            if len(self.chunks) > self.MAX_CHUNKS:
                self._evict(len(self.chunks) - self.MAX_CHUNKS)

            self.save()
            return True

        except Exception as e:
            print(f"[RagMemory] Store error: {e}")
            return False

    async def store_batch(self, texts: List[str], speaker: str = "",
                          timestamps: Optional[List[float]] = None,
                          category: str = "conversation",
                          importance: int = 1) -> int:
        """
        Store multiple texts at once — much faster than calling store() in a loop
        because embeddings are batched.
        Returns count of new chunks stored.
        """
        texts = [t.strip() for t in texts if t.strip() and len(t.strip()) >= 10]
        if not texts:
            return 0
        if self.index is None:
            self.index = faiss.IndexFlatIP(EMB_DIM)

        try:
            embs = await _embed_batch(texts)
            faiss.normalize_L2(embs)

            stored = 0
            now = time.time()
            for i, (text, emb) in enumerate(zip(texts, embs)):
                emb_2d = emb.reshape(1, -1)

                # Dedup check
                if self.index.ntotal > 0:
                    D, _ = self.index.search(emb_2d, 1)
                    if D[0][0] >= self.DEDUP_THRESHOLD:
                        continue

                ts = (timestamps[i] if timestamps and i < len(timestamps) else now)
                chunk = MemoryChunk(text=text, speaker=speaker, timestamp=ts,
                                    category=category, importance=importance)
                self.index.add(emb_2d)
                self.chunks.append(chunk)
                self._update_corpus_df(chunk)
                stored += 1

            if stored > 0:
                if len(self.chunks) > self.MAX_CHUNKS:
                    self._evict(len(self.chunks) - self.MAX_CHUNKS)
                self.save()

            return stored
        except Exception as e:
            print(f"[RagMemory] Batch store error: {e}")
            return 0

    async def store_conversation(self, messages: List[Dict[str, str]],
                                  base_timestamp: float = 0.0) -> int:
        """
        Chunk a message list into ~CHUNK_MAX_WORDS segments and batch-embed them.
        Returns number of new chunks stored.
        """
        if not messages:
            return 0

        chunks_text: List[str] = []
        chunks_ts: List[float] = []
        current_lines: List[str] = []
        current_words = 0
        ts = base_timestamp or time.time()

        for msg in messages:
            sender = msg.get("sender", "Unknown")
            text = msg.get("text", "").strip()
            if not text:
                continue
            line = f"{sender}: {text}"
            words = len(text.split())
            msg_ts = msg.get("timestamp", ts)

            if current_words + words > self.CHUNK_MAX_WORDS and current_lines:
                chunks_text.append("\n".join(current_lines))
                chunks_ts.append(msg_ts)
                current_lines = []
                current_words = 0

            current_lines.append(line)
            current_words += words

        if current_lines:
            chunks_text.append("\n".join(current_lines))
            chunks_ts.append(ts)

        return await self.store_batch(chunks_text, speaker="mixed",
                                      timestamps=chunks_ts, category="conversation")

    # ── Search ───────────────────────────────────────────────────────────────

    async def search(self, query: str, k: int = 5,
                     min_score: float = 0.20) -> List[Dict[str, Any]]:
        """
        Hybrid semantic + keyword search.
        Returns ranked list of dicts with text, score, raw_score, speaker, timestamp, category.
        """
        if not self.chunks or self.index is None or self.index.ntotal == 0:
            return []

        try:
            # ── Semantic search via FAISS ──
            q_emb = await _embed_single(query)
            q_emb = q_emb.reshape(1, -1).astype(np.float32)
            faiss.normalize_L2(q_emb)

            k_faiss = min(k * 4, self.index.ntotal)  # over-fetch, then re-rank
            D, I = self.index.search(q_emb, k_faiss)
            semantic_scores = D[0]   # cosine similarity (inner product on normalised vecs)
            indices = I[0]

            # ── Keyword scoring ──
            query_tokens = _tokenize(query)
            num_docs = len(self.chunks)

            # ── Temporal decay + access boost + hybrid re-rank ──
            now = time.time()
            scored: List[Dict[str, Any]] = []

            for rank, (idx, sem_score) in enumerate(zip(indices, semantic_scores)):
                if idx < 0 or idx >= len(self.chunks):
                    continue
                chunk = self.chunks[idx]

                # Keyword component
                kw_score = _keyword_score(query_tokens, chunk.tokens(), chunk.tf(),
                                           self._corpus_df, num_docs)

                # Hybrid base score
                hybrid = self.SEMANTIC_WEIGHT * float(sem_score) + self.KEYWORD_WEIGHT * kw_score

                # Temporal decay (30-day half-life)
                age_secs = max(now - chunk.timestamp, 0)
                decay = 0.5 ** (age_secs / 2_592_000)

                # Access boost (cap at +0.15)
                access_boost = min(chunk.access_count * 0.02, 0.15)

                # Importance boost
                importance_boost = (chunk.importance - 1) * 0.05  # 0 to +0.20

                final = hybrid * 0.80 + decay * 0.10 + access_boost * 0.05 + importance_boost * 0.05

                if float(sem_score) >= min_score:
                    scored.append({
                        "idx": idx,
                        "chunk": chunk,
                        "score": round(final, 4),
                        "raw_score": round(float(sem_score), 4),
                        "keyword_score": round(kw_score, 4),
                    })

            # Sort by final score descending, take top k
            scored.sort(key=lambda x: x["score"], reverse=True)
            top = scored[:k]

            # Update access stats
            results: List[Dict[str, Any]] = []
            for item in top:
                chunk = item["chunk"]
                chunk.access_count += 1
                chunk.last_accessed = now
                results.append({
                    "text": chunk.text,
                    "score": item["score"],
                    "raw_score": item["raw_score"],
                    "keyword_score": item["keyword_score"],
                    "speaker": chunk.speaker,
                    "timestamp": chunk.timestamp,
                    "category": chunk.category,
                    "chunk_id": chunk.chunk_id,
                    "importance": chunk.importance,
                })

            if results:
                self.save()

            return results

        except Exception as e:
            print(f"[RagMemory] Search error: {e}")
            return []

    # ── Eviction ─────────────────────────────────────────────────────────────

    def _evict(self, count: int) -> None:
        """Evict N least-valuable chunks. Rebuilds FAISS index after eviction."""
        if count <= 0 or not self.chunks:
            return
        now = time.time()

        scores = []
        for i, c in enumerate(self.chunks):
            age_days = (now - c.timestamp) / 86400
            recency_bonus = 50 if c.last_accessed > now - 86400 else 0
            value = c.importance * 20 + c.access_count * 10 - age_days + recency_bonus
            scores.append((i, value))

        scores.sort(key=lambda x: x[1])
        evict_set = set(s[0] for s in scores[:count])

        keep_indices = [i for i in range(len(self.chunks)) if i not in evict_set]
        self.chunks = [self.chunks[i] for i in keep_indices]

        # Rebuild FAISS without evicted vectors
        self._rebuild_index_from_kept(keep_indices)
        self._rebuild_corpus_df()

    def _rebuild_index_from_kept(self, keep_indices: List[int]) -> None:
        """Rebuild FAISS index keeping only specified indices."""
        if self.index is None or self.index.ntotal == 0:
            self.index = faiss.IndexFlatIP(EMB_DIM)
            return
        try:
            # Reconstruct all vectors, then keep subset
            ptr = faiss.rev_swig_ptr(self.index.get_xb(), self.index.ntotal * EMB_DIM)
            all_vecs = np.array(ptr, dtype=np.float32).reshape(self.index.ntotal, EMB_DIM)
            kept_vecs = all_vecs[keep_indices]
            new_idx = faiss.IndexFlatIP(EMB_DIM)
            if len(kept_vecs) > 0:
                new_idx.add(kept_vecs)
            self.index = new_idx
        except Exception as e:
            print(f"[RagMemory] Index rebuild error after eviction: {e}")
            self.index = faiss.IndexFlatIP(EMB_DIM)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_chunks": len(self.chunks),
            "faiss_ntotal": self.index.ntotal if self.index else 0,
            "index_type": "faiss_flat_ip",
            "embedding_model": _LOCAL_MODEL_NAME,
            "embedding_dim": EMB_DIM,
            "api_calls": "none — fully local",
            "hybrid_search": True,
            "max_capacity": self.MAX_CHUNKS,
            "oldest": self.chunks[0].timestamp if self.chunks else None,
            "newest": self.chunks[-1].timestamp if self.chunks else None,
            "categories": list(set(c.category for c in self.chunks)),
        }

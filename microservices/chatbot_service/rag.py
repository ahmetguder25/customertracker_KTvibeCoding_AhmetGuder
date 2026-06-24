"""RAG retrieval module — Hybrid BM25 + semantic multi-query search.

Public API
----------
search_document_hybrid(user_query, n_results=20)  -> dict
    Full pipeline: expand query → multi-query semantic search + BM25 keyword
    search → Reciprocal Rank Fusion → top-N chunks.
    Returns: {"chunks": [...], "queries_used": [...]}

search_document_multi(user_query, n_results=20)   -> dict
    Legacy: multi-query semantic-only. Kept for backward compat.

search_document(user_query, n_results=4)           -> list[str]
    Legacy: single-query semantic-only.

Vector DB: ./rag_vectors.db (built by process_pdf.py)
"""

import json
import os
import re
import sqlite3
import threading

import numpy as np
import ollama
from rank_bm25 import BM25Okapi

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "rag_vectors.db")
EMBED_MODEL = "nomic-embed-text"
GEN_MODEL   = "qwen3.5:9b"

# ── Module-level cache (populated on first request, shared across all) ─────────
_cache_lock = threading.Lock()
_cache: dict = {}          # keys: "texts", "matrix", "bm25"


# ── Internal helpers ────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list:
    """Lowercase alphanumeric tokenizer — handles English + Arabic transliterations."""
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


def _load_cache() -> tuple:
    """Return (texts, matrix, bm25) — loads from SQLite and builds BM25 once,
    then caches forever in the module global for the lifetime of the Flask process.
    """
    global _cache
    with _cache_lock:
        if _cache:
            return _cache["texts"], _cache["matrix"], _cache["bm25"], _cache.get("doc_ids", [])

        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(
                f"Vector DB not found at {DB_PATH}. "
                "Please run process_pdf.py first."
            )

        print("[rag] Loading vector DB into memory ...", flush=True)
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("SELECT text, embedding, document_id FROM chunks").fetchall()
        con.close()

        if not rows:
            _cache = {"texts": [], "matrix": np.empty((0, 0), dtype=np.float32), "bm25": None, "doc_ids": []}
            return [], np.empty((0, 0), dtype=np.float32), None, []

        texts   = [r[0] for r in rows]
        doc_ids = [r[2] for r in rows]
        matrix  = np.stack(
            [np.array(json.loads(r[1]), dtype=np.float32) for r in rows]
        )  # (N, D)

        print(f"[rag] Building BM25 index over {len(texts):,} chunks ...", flush=True)
        tokenized = [_tokenize(t) for t in texts]
        bm25      = BM25Okapi(tokenized)

        _cache = {"texts": texts, "matrix": matrix, "bm25": bm25, "doc_ids": doc_ids}
        print("[rag] Cache ready.", flush=True)
        return texts, matrix, bm25, doc_ids


def _embed(text: str) -> np.ndarray:
    """L2-normalised embedding vector from nomic-embed-text."""
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    vec      = np.array(response["embedding"], dtype=np.float32)
    norm     = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _cosine_scores(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Vectorised cosine similarities: shape (N,). query_vec must be L2-normalised."""
    norms  = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms  = np.where(norms == 0, 1.0, norms)
    return (matrix / norms) @ query_vec   # (N,)


def _rrf(*ranked_lists: list, k: int = 60) -> dict:
    """Reciprocal Rank Fusion over multiple ranked text lists.

    Each element of ranked_lists is an ordered list of strings (best-first).
    Returns {text: rrf_score} dict.
    """
    scores: dict = {}
    for ranked in ranked_lists:
        for rank, text in enumerate(ranked):
            scores[text] = scores.get(text, 0.0) + 1.0 / (k + rank)
    return scores


# ── Query expansion ─────────────────────────────────────────────────────────────

_EXPAND_SYSTEM = (
    "You are a document search assistant specialised in Islamic finance and "
    "structured finance compliance. Given a user question, generate exactly "
    "3 to 4 alternative search queries that together cover all aspects needed "
    "to answer the question from a compliance document. Focus on:\n"
    "  1. The general principle or governing rule.\n"
    "  2. The specific conditions required for permissibility.\n"
    "  3. Explicit prohibitions or disqualifying factors.\n"
    "  4. Exceptions, special circumstances, or edge cases.\n\n"
    "Return ONLY a JSON array of strings. No explanation, no markdown, no preamble."
)


def expand_query(user_query: str) -> list:
    """Use qwen3.5:9b to generate 3–4 diverse sub-queries.
    Returns [original_query, variant_1, ...]. Falls back to [user_query] on error.
    """
    try:
        response = ollama.chat(
            model=GEN_MODEL,
            options={"temperature": 0.3},
            messages=[
                {"role": "system", "content": _EXPAND_SYSTEM},
                {"role": "user",   "content": f"User question: {user_query}"},
            ],
        )
        raw = response["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\n?```$",        "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(q, str) for q in parsed):
            seen, result = {user_query}, [user_query]
            for q in parsed:
                q = q.strip()
                if q and q not in seen:
                    seen.add(q)
                    result.append(q)
            return result
        return [user_query]
    except Exception as exc:
        print(f"[expand_query] fallback to single query: {exc}")
        return [user_query]


# ── Primary public API ─────────────────────────────────────────────────────────

def search_document_hybrid(user_query: str, n_results: int = 20, selected_docs: list = None) -> dict:
    """Hybrid BM25 + multi-query semantic search with Reciprocal Rank Fusion.

    Pipeline
    --------
    1. expand_query() → 1 original + 3–4 semantic variants
    2. Embed ALL queries → vectorised cosine similarity → pool & deduplicate
       (semantic ranked list)
    3. BM25 keyword search on original query
       (BM25 ranked list)
    4. RRF fusion of both ranked lists → final top-N

    BM25 adds precision for exact legal terms (Murabaha, riba, gharar…) that
    can fall into semantic blind-spots.

    Returns
    -------
    dict:
        "chunks"       : list[str]  — top-N texts, best-first
        "queries_used" : list[str]  — expanded queries that were run
    """
    texts, matrix, bm25, doc_ids = _load_cache()
    if not texts:
        return {"chunks": [], "queries_used": [user_query]}

    # Filter mask for selected documents
    mask = None
    if selected_docs and len(selected_docs) > 0:
        mask = [doc_id in selected_docs for doc_id in doc_ids]

    # ── 1. Query expansion ──────────────────────────────────────────────────────
    queries = expand_query(user_query)

    # ── 2. Multi-query semantic search ─────────────────────────────────────────
    best_sem: dict = {}
    for q in queries:
        q_vec  = _embed(q)
        scores = _cosine_scores(q_vec, matrix)    # (N,)
        for i, (text, score) in enumerate(zip(texts, scores.tolist())):
            # Apply mask if filtering
            if mask is not None and not mask[i]:
                continue
            if score > best_sem.get(text, -2.0):
                best_sem[text] = score

    sem_ranked = [t for t, _ in sorted(best_sem.items(), key=lambda x: x[1], reverse=True)]

    # ── 3. BM25 keyword search ──────────────────────────────────────────────────
    bm25_scores  = bm25.get_scores(_tokenize(user_query))   # (N,)
    # Apply mask by zeroing out scores
    if mask is not None:
        bm25_scores = np.where(mask, bm25_scores, -1.0)
        
    bm25_ranked  = [texts[i] for i in np.argsort(bm25_scores)[::-1] if mask is None or mask[i]]

    # ── 4. Reciprocal Rank Fusion ───────────────────────────────────────────────
    fused = _rrf(sem_ranked, bm25_ranked, k=60)
    top_chunks = [t for t, _ in sorted(fused.items(), key=lambda x: x[1], reverse=True)]

    return {
        "chunks":       top_chunks[:n_results],
        "queries_used": queries,
    }


# ── Legacy paths (backward compatibility) ──────────────────────────────────────

def search_document_multi(user_query: str, n_results: int = 20) -> dict:
    """Multi-query semantic-only search (no BM25). Kept for backward compat."""
    texts, matrix, _, doc_ids = _load_cache()
    if not texts:
        return {"chunks": [], "queries_used": [user_query]}

    queries   = expand_query(user_query)
    best_sem: dict = {}
    for q in queries:
        q_vec  = _embed(q)
        scores = _cosine_scores(q_vec, matrix)
        for text, score in zip(texts, scores.tolist()):
            if score > best_sem.get(text, -2.0):
                best_sem[text] = score

    ranked = sorted(best_sem.items(), key=lambda x: x[1], reverse=True)
    return {"chunks": [t for t, _ in ranked[:n_results]], "queries_used": queries}


def search_document(user_query: str, n_results: int = 4) -> list:
    """Single-query semantic-only search. Kept for backward compat."""
    texts, matrix, _, doc_ids = _load_cache()
    if not texts:
        return []
    q_vec  = _embed(user_query)
    scores = _cosine_scores(q_vec, matrix)
    return [texts[i] for i in np.argsort(scores)[::-1][:n_results]]

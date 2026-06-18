"""process_pdf.py — One-time AAOIFI PDF ingestion script.

Reads ./AOOIFI/Shariaa-Standards-ENG.pdf, splits it into chunks,
generates embeddings via Ollama nomic-embed-text, and stores them in
./rag_vectors.db (SQLite).

Run once:
    ./.venv/bin/python process_pdf.py

Re-running is safe — already-processed chunks are skipped (upsert by id).
"""

import hashlib
import json
import os
import sqlite3
import sys

import fitz  # PyMuPDF
import ollama
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
PDF_PATH  = os.path.join(BASE_DIR, "sources", "AAOIFI", "Shariaa-Standards-ENG.pdf")
DB_PATH   = os.path.join(BASE_DIR, "rag_vectors.db")

CHUNK_SIZE    = 1000
CHUNK_OVERLAP = 100
EMBED_MODEL   = "nomic-embed-text"
BATCH_REPORT  = 50  # print progress every N chunks


# ── DB Setup ───────────────────────────────────────────────────────────────────

def init_db(con: sqlite3.Connection) -> None:
    """Create the chunks table if it does not already exist."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id        TEXT PRIMARY KEY,
            text      TEXT NOT NULL,
            embedding TEXT NOT NULL
        )
    """)
    con.commit()


def chunk_exists(con: sqlite3.Connection, chunk_id: str) -> bool:
    row = con.execute("SELECT 1 FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    return row is not None


def upsert_chunk(con: sqlite3.Connection, chunk_id: str, text: str, embedding: list) -> None:
    con.execute(
        "INSERT OR REPLACE INTO chunks (id, text, embedding) VALUES (?, ?, ?)",
        (chunk_id, text, json.dumps(embedding)),
    )


# ── PDF Extraction ─────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from the PDF using PyMuPDF."""
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


# ── Embedding ──────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list:
    """Generate an embedding vector via Ollama nomic-embed-text."""
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response["embedding"]


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Validate PDF path
    if not os.path.exists(PDF_PATH):
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/5] PDF found: {PDF_PATH}")

    # Pull embedding model if not present (no-op if already pulled)
    print(f"[2/5] Ensuring Ollama model '{EMBED_MODEL}' is available ...")
    try:
        ollama.pull(EMBED_MODEL)
    except Exception as exc:
        print(f"  WARNING: pull returned: {exc} — trying to use it anyway.")

    # Extract text
    print("[3/5] Extracting text from PDF ...")
    full_text = extract_text_from_pdf(PDF_PATH)
    print(f"      Extracted {len(full_text):,} characters.")

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    chunks = splitter.split_text(full_text)
    total  = len(chunks)
    print(f"[4/5] Split into {total:,} chunks (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}).")

    # Connect to SQLite and embed
    print(f"[5/5] Embedding chunks → {DB_PATH} ...")
    con = sqlite3.connect(DB_PATH)
    init_db(con)

    skipped = 0
    processed = 0

    for idx, chunk_text in enumerate(chunks, start=1):
        # Deterministic id: sha256 of the chunk text
        chunk_id = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()

        if chunk_exists(con, chunk_id):
            skipped += 1
        else:
            embedding = embed_text(chunk_text)
            upsert_chunk(con, chunk_id, chunk_text, embedding)
            con.commit()
            processed += 1

        if idx % BATCH_REPORT == 0 or idx == total:
            pct = idx / total * 100
            print(
                f"  [{idx:>5}/{total}]  {pct:5.1f}%  "
                f"new={processed}  skipped={skipped}"
            )

    con.close()

    print()
    print("=" * 60)
    print(f"Done!  Total chunks: {total}")
    print(f"  Newly embedded : {processed}")
    print(f"  Already in DB  : {skipped}")
    print(f"  DB location    : {DB_PATH}")
    print("=" * 60)
    print()
    print("You can now restart the Flask app — the chatbot will be ready.")


if __name__ == "__main__":
    main()

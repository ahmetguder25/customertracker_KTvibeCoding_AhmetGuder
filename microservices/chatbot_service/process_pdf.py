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
            id          TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            text        TEXT NOT NULL,
            embedding   TEXT NOT NULL
        )
    """)
    con.commit()


def chunk_exists(con: sqlite3.Connection, chunk_id: str) -> bool:
    row = con.execute("SELECT 1 FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    return row is not None


def upsert_chunk(con: sqlite3.Connection, chunk_id: str, document_id: str, text: str, embedding: list) -> None:
    con.execute(
        "INSERT OR REPLACE INTO chunks (id, document_id, text, embedding) VALUES (?, ?, ?, ?)",
        (chunk_id, document_id, text, json.dumps(embedding)),
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


# ── Status Tracking ────────────────────────────────────────────────────────────

STATUS_FILE = os.path.join(BASE_DIR, "rag_status.json")

def write_status(is_active: bool, message: str) -> None:
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({"active_process": is_active, "message": message}, f)
    except Exception as e:
        print(f"Failed to write status: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    write_status(True, "Starting RAG Sync...")
    SOURCES_DIR = os.path.join(BASE_DIR, "sources")
    if not os.path.exists(SOURCES_DIR):
        print(f"ERROR: Sources directory not found at {SOURCES_DIR}", file=sys.stderr)
        sys.exit(1)

    # Pull embedding model if not present (no-op if already pulled)
    print(f"[1/4] Ensuring Ollama model '{EMBED_MODEL}' is available ...")
    try:
        ollama.pull(EMBED_MODEL)
    except Exception as exc:
        print(f"  WARNING: pull returned: {exc} — trying to use it anyway.")

    # Connect to SQLite
    print(f"[2/4] Connecting to DB → {DB_PATH} ...")
    con = sqlite3.connect(DB_PATH)
    init_db(con)

    # Find all PDFs in sources directory
    pdf_files = []
    for root, _, files in os.walk(SOURCES_DIR):
        for f in files:
            if f.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))
                
    if not pdf_files:
        print(f"WARNING: No PDFs found in {SOURCES_DIR}")
        write_status(False, "No PDFs found")
        con.close()
        sys.exit(0)

    print(f"[3/4] Found {len(pdf_files)} PDF(s). Processing...")

    total_skipped = 0
    total_processed = 0

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )

    for pdf_path in pdf_files:
        doc_id = os.path.basename(pdf_path)
        print(f"  -> Processing document: {doc_id}")
        write_status(True, f"RAG Sync: Extracting {doc_id}...")
        
        full_text = extract_text_from_pdf(pdf_path)
        chunks = splitter.split_text(full_text)
        total = len(chunks)
        print(f"     Extracted {len(full_text):,} chars, split into {total:,} chunks.")
        
        doc_skipped = 0
        doc_processed = 0

        for idx, chunk_text in enumerate(chunks, start=1):
            # Deterministic id: sha256 of the chunk text
            chunk_id = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()

            if chunk_exists(con, chunk_id):
                doc_skipped += 1
            else:
                embedding = embed_text(chunk_text)
                upsert_chunk(con, chunk_id, doc_id, chunk_text, embedding)
                con.commit()
                doc_processed += 1

            if idx % BATCH_REPORT == 0 or idx == total:
                pct = idx / total * 100
                msg = f"RAG Sync: {doc_id} - {idx}/{total} chunks ({pct:.1f}%)"
                print(f"     [{idx:>5}/{total}]  {pct:5.1f}%  new={doc_processed}  skipped={doc_skipped}")
                write_status(True, msg)
                
        total_skipped += doc_skipped
        total_processed += doc_processed

    con.close()

    print()
    print("=" * 60)
    print(f"[4/4] Done! Processed {len(pdf_files)} document(s).")
    print(f"  Newly embedded : {total_processed}")
    print(f"  Already in DB  : {total_skipped}")
    print(f"  DB location    : {DB_PATH}")
    print("=" * 60)
    print()
    print("You can now restart the Flask app — the chatbot will be ready.")
    write_status(False, "Idle")

if __name__ == "__main__":
    main()

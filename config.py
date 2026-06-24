# config.py — shared constants only, no imports from other vpa modules
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_DIR = os.path.join(BASE_DIR, "storage", "faiss_db")
DOC_DIR   = os.path.join(BASE_DIR, "doc")
BOOKS_DIR = os.path.join(BASE_DIR, "books")
CODE_DIR  = os.path.join(BASE_DIR, "code")

EMBEDDING_MODEL    = "all-MiniLM-L6-v2"
IMAGE_MODEL        = "stabilityai/stable-diffusion-xl-beta-v2-2-2"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ── Knowledge-base storage limits ──────────────────────────────────────────────
# Combined cap for doc/ + books/ (the two RAG-indexed document folders).
# Raise this if you have more disk space; lower it to keep the FAISS index small.
TOTAL_KB_MAX_MB  = 200   # hard limit: doc/ + books/ combined
BOOKS_MAX_MB     = 96    # sub-limit: books/ alone (was 48; doubled now we track combined)

def _dir_size_mb(path: str) -> float:
    """Return total MB of regular files in a directory (non-recursive)."""
    if not os.path.exists(path):
        return 0.0
    total = sum(
        os.path.getsize(os.path.join(path, f))
        for f in os.listdir(path)
        if os.path.isfile(os.path.join(path, f))
    )
    return total / (1024 * 1024)

def get_books_size_mb() -> float:
    return _dir_size_mb(BOOKS_DIR)

def get_doc_size_mb() -> float:
    return _dir_size_mb(DOC_DIR)

def get_kb_size_mb() -> float:
    """Combined size of doc/ + books/ — the two RAG-indexed folders."""
    return _dir_size_mb(DOC_DIR) + _dir_size_mb(BOOKS_DIR)


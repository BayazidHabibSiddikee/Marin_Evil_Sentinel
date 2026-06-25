# config.py — shared constants only, no imports from other vpa modules
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_DIR = os.path.join(BASE_DIR, "storage", "faiss_db")
BOOKS_DIR = os.path.join(BASE_DIR, "books")
CODE_DIR  = os.path.join(BASE_DIR, "code")

EMBEDDING_MODEL    = "all-MiniLM-L6-v2"
IMAGE_MODEL        = "black-forest-labs/flux-schnell"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ── Knowledge-base storage limits ──────────────────────────────────────────────
TOTAL_KB_MAX_MB  = 200   # hard limit: books/ cap
BOOKS_MAX_MB     = 96    # sub-limit: books/ alone

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

def get_kb_size_mb() -> float:
    """Total size of books/ — the RAG-indexed folder."""
    return _dir_size_mb(BOOKS_DIR)


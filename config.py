# config.py — shared constants only, no imports from other vpa modules
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_DIR = os.path.join(BASE_DIR, "storage", "faiss_db")
DOC_DIR = os.path.join(BASE_DIR, "doc")
BOOKS_DIR = os.path.join(BASE_DIR, "books")
CODE_DIR = os.path.join(BASE_DIR, "code")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
IMAGE_MODEL = "stabilityai/stable-diffusion-xl-beta-v2-2-2"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

def get_books_size_mb():
    if not os.path.exists(BOOKS_DIR):
        return 0
    total = sum(os.path.getsize(os.path.join(BOOKS_DIR, f)) for f in os.listdir(BOOKS_DIR) if os.path.isfile(os.path.join(BOOKS_DIR, f)))
    return total / (1024 * 1024)

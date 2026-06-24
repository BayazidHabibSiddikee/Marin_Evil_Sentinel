import asyncio
import os
import shutil
import time
import logging
from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import database
from config import get_books_size_mb, get_kb_size_mb, TOTAL_KB_MAX_MB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ── LIFESPAN (Proactive Engine) ──────────────────────────────────────────────
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    database.prune_old_messages()
    try:
        from proactive_engine import proactive_broadcaster
        asyncio.create_task(proactive_broadcaster())
    except ImportError:
        pass
    yield

app = FastAPI(title="Marin Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5090",
        "http://127.0.0.1:5090",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup static folders
os.makedirs("static/generated", exist_ok=True)
os.makedirs("books", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/books", StaticFiles(directory="books"), name="books")  # Serve library files

templates = Jinja2Templates(directory="templates")

@app.get("/health")
async def health_check():
    try:
        # Check DB connection
        database.get_state("PING")
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {"status": "ok", "db": db_status}

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return """
    <html>
    <head><title>Login</title><style>body{background:#121212;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;} form{display:flex;flex-direction:column;gap:10px;}</style></head>
    <body>
        <form method="POST" action="/login">
            <h2>Enter PIN</h2>
            <input type="password" name="pin" autofocus>
            <button type="submit">Unlock</button>
        </form>
    </body>
    </html>
    """

@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    pin = form.get("pin")
    expected_pin = database.get_state("APP_PIN")
    if expected_pin and pin != expected_pin:
        return HTMLResponse("Invalid PIN. <a href='/login'>Try again</a>", status_code=401)
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="marin_pin", value=pin, httponly=True)
    return response

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in ["/login", "/health", "/proactive/stream"] or request.url.path.startswith("/static"):
        return await call_next(request)
        
    expected_pin = database.get_state("APP_PIN")
    if expected_pin:
        cookie_pin = request.cookies.get("marin_pin")
        if cookie_pin != expected_pin:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return RedirectResponse(url="/login")
            
    return await call_next(request)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if not database.get_state("ONBOARDING_COMPLETE"):
        return RedirectResponse(url="/onboarding")
    return templates.TemplateResponse(request=request, name="landing.html", context={"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    if not database.get_state("ONBOARDING_COMPLETE"):
        return RedirectResponse(url="/onboarding")
    return templates.TemplateResponse(request=request, name="marin_chat.html", context={"request": request})

@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request):
    username = database.get_state("USER_NAME", "Bayazid")
    return templates.TemplateResponse(request=request, name="onboarding.html", context={"request": request, "username": username})

@app.get("/api/settings")
async def get_settings():
    return {
        "user_name": database.get_state("USER_NAME") or "Bayazid",
        "location": database.get_state("LOCATION") or "Rajshahi",
        "openrouter_key": database.get_state("OPENROUTER_API_KEY") or "",
        "telegram_key": database.get_state("TELEGRAM_API_KEY") or "",
        "sender_email": database.get_state("SENDER_EMAIL") or "pythonlusty@gmail.com",
        "email_pass": database.get_state("EMAIL_PASSWORD") or "",
        "image_model": database.get_state("IMAGE_MODEL") or "stabilityai/stable-diffusion-xl-beta-v2-2-2",
        "vision_model": database.get_state("VISION_MODEL") or "",
        "selected_models": database.get_state("SELECTED_MODELS") or [],
        "fallback_models": database.get_state("FALLBACK_MODELS") or [],
        "active_model": database.get_state("ACTIVE_MODEL") or "",
        "user_avatar": database.get_state("USER_AVATAR") or "",
        "hf_token": database.get_state("HF_TOKEN") or ""
    }

@app.post("/api/settings/avatar")
async def upload_avatar(avatar: UploadFile = File(...)):
    ext = os.path.splitext(avatar.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return {"error": "Unsupported image type"}
    content = await avatar.read()
    if len(content) > 2 * 1024 * 1024:
        return {"error": "Image too large (max 2MB)"}
    avatar_path = os.path.join("static", "images", "user_avatar.png")
    os.makedirs(os.path.dirname(avatar_path), exist_ok=True)
    with open(avatar_path, "wb") as f:
        f.write(content)
    url = f"/static/images/user_avatar.png?t={int(time.time())}"
    database.set_state("USER_AVATAR", url)
    return {"url": url}

@app.post("/api/settings")
async def save_settings(request: Request):
    data = await request.json()
    database.set_state("USER_NAME", data.get("user_name", "Bayazid"))
    database.set_state("LOCATION", data.get("location", "Rajshahi"))
    if data.get("openrouter_key"): database.set_state("OPENROUTER_API_KEY", data.get("openrouter_key"))
    if data.get("telegram_key"): database.set_state("TELEGRAM_API_KEY", data.get("telegram_key"))
    if data.get("sender_email"): database.set_state("SENDER_EMAIL", data.get("sender_email"))
    if data.get("email_pass"): database.set_state("EMAIL_PASSWORD", data.get("email_pass"))
    if data.get("image_model"): database.set_state("IMAGE_MODEL", data.get("image_model"))
    if data.get("vision_model") is not None: database.set_state("VISION_MODEL", data.get("vision_model"))
    if data.get("selected_models") is not None: database.set_state("SELECTED_MODELS", data.get("selected_models"))
    if data.get("fallback_models") is not None: database.set_state("FALLBACK_MODELS", data.get("fallback_models"))
    if data.get("active_model") is not None: database.set_state("ACTIVE_MODEL", data.get("active_model"))
    if "user_avatar" in data: database.set_state("USER_AVATAR", data.get("user_avatar", ""))
    if data.get("hf_token") is not None: database.set_state("HF_TOKEN", data.get("hf_token", ""))
    
    database.set_state("ONBOARDING_COMPLETE", "true")
    return {"status": "success"}
# ── LIBRARY API ─────────────────────────────────────────────────────────────
@app.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    return templates.TemplateResponse(request=request, name="library.html", context={"request": request})

@app.get("/api/rag/health")
async def rag_health_proxy():
    """Proxy to the RAG server's /health so the library UI can read storage stats."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://127.0.0.1:5091/health")
            return r.json()
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}

@app.get("/api/documents")
async def list_documents():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    doc_dir = os.path.join(base_dir, "books")
    if not os.path.exists(doc_dir):
        return {"documents": []}

    docs = []
    for f in sorted(os.listdir(doc_dir)):
        if f.endswith((".pdf", ".docx", ".txt", ".md")):
            path = os.path.join(doc_dir, f)
            size_bytes = os.path.getsize(path)
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{size_bytes / 1024:.0f} KB"
            docs.append({
                "filename": f,
                "size": size_str,
                "type": f.split(".")[-1]
            })
            if len(docs) >= 15:
                break
    return {"documents": docs}

@app.get("/api/documents/{filename}/content")
async def get_document_content(filename: str):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    doc_dir = os.path.join(base_dir, "books")
    path = os.path.realpath(os.path.join(doc_dir, filename))

    if not path.startswith(os.path.realpath(doc_dir)) or not os.path.exists(path):
        return {"error": "File not found"}

    ext = filename.split(".")[-1].lower()
    content = ""

    try:
        if ext == "pdf":
            import fitz
            try:
                import pymupdf4llm
                content = pymupdf4llm.to_markdown(path)
            except ImportError:
                doc = fitz.open(path)
                for page in doc:
                    content += page.get_text() + "\n\n"
        elif ext == "docx":
            import mammoth
            with open(path, "rb") as f:
                result = mammoth.extract_raw_text(f)
                content = result.value
        elif ext in ["txt", "md"]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        return {"content": content[:50000]}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/api/documents/{filename}")
async def delete_document(filename: str):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    doc_dir = os.path.join(base_dir, "books")
    path = os.path.realpath(os.path.join(doc_dir, filename))

    if not path.startswith(os.path.realpath(doc_dir)) or not os.path.exists(path):
        return {"error": "File not found"}

    os.remove(path)
    return {"success": True, "message": f"Deleted {filename}"}

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".docx", ".txt", ".md"):
        return {"error": "Unsupported file type. Use PDF, DOCX, TXT, or MD."}

    content = await file.read()
    upload_size_mb = len(content) / (1024 * 1024)
    current_total_mb = get_kb_size_mb()
    if current_total_mb + upload_size_mb > TOTAL_KB_MAX_MB:
        remaining = max(0.0, TOTAL_KB_MAX_MB - current_total_mb)
        return {"error": f"Knowledge-base full. Total: {current_total_mb:.1f} MB / {TOTAL_KB_MAX_MB} MB (only {remaining:.1f} MB left). Delete some documents or books first."}

    base_dir = os.path.dirname(os.path.abspath(__file__))
    doc_dir = os.path.join(base_dir, "books")
    os.makedirs(doc_dir, exist_ok=True)
    filepath = os.path.join(doc_dir, file.filename)
    with open(filepath, "wb") as f:
        f.write(content)

    return {"success": True, "filename": file.filename, "size": f"{upload_size_mb:.1f}MB"}

# ── RATE LIMITING ─────────────────────────────────────────────────────────────
chat_requests = {}
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 20

def check_rate_limit(ip: str):
    now = time.time()
    reqs = chat_requests.get(ip, [])
    reqs = [t for t in reqs if now - t < RATE_LIMIT_WINDOW]
    if len(reqs) >= RATE_LIMIT_MAX:
        return False
    reqs.append(now)
    chat_requests[ip] = reqs
    return True

# ── CORE CHAT API ─────────────────────────────────────────────────────────────

@app.get("/api/chat/history")
async def get_chat_history():
    try:
        history = database.get_history("marin", limit=50)
        return {"messages": history}
    except Exception as e:
        return {"messages": [], "error": str(e)}

@app.post("/api/chat/context")
async def save_tool_context(request: Request):
    """Save a tool result as system context so Marin knows what happened."""
    try:
        data = await request.json()
        tool_name = data.get("tool", "tool")
        result = data.get("result", "")
        if result:
            database.save_message("marin", "system", f"[TOOL: {tool_name}] {result[:2000]}")
            return {"ok": True}
        return {"ok": False, "error": "No result"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        return JSONResponse({"error": "Rate limit exceeded. Try again in a minute."}, status_code=429)

    form = await request.form()
    message = form.get("message", "")
    theme = form.get("theme", "evil")
    
    # Handle image upload if present
    image_path = None
    if "image" in form and getattr(form["image"], "filename", None):
        img_file = form["image"]
        image_path = os.path.join("static", "uploads", img_file.filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        with open(image_path, "wb") as buffer:
            shutil.copyfileobj(img_file.file, buffer)

    try:
        import proactive_engine
        proactive_engine.record_user_message("marin")
        proactive_engine.mark_session_active("marin")
    except ImportError:
        pass

    from marin import main as marin_main
    
    async def stream_generator():
        async for chunk in marin_main(message, image_path=image_path, theme=theme):
            yield chunk
            
    return StreamingResponse(stream_generator(), media_type="text/plain")

@app.get("/proactive/stream")
async def proactive_sse():
    try:
        from proactive_engine import proactive_stream
        return StreamingResponse(proactive_stream(), media_type="text/event-stream")
    except ImportError:
        return StreamingResponse(iter([]), media_type="text/event-stream")

# ── PLAYGROUND API ─────────────────────────────────────────────────────────────
class PlaygroundRequest(BaseModel):
    title: str = ""
    description: str = ""
    html: str = ""
    css: str = ""
    js: str = ""

@app.post("/api/playground/build")
async def build_playground(req: PlaygroundRequest):
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Inter', -apple-system, sans-serif; background: #0d1117; color: #e6edf3; padding: 16px; min-height: 100vh; }}
{req.css}
</style>
</head>
<body>
{req.html}
<script>
(function() {{
{req.js}
}})();
</script>
</body>
</html>"""
    return {"html": html, "title": req.title, "description": req.description}

# ── FLASHCARDS & STUDY API ────────────────────────────────────────────────────
class AddFlashcardRequest(BaseModel):
    topic: str
    front: str
    back: str

@app.post("/api/flashcards/add")
async def add_flashcard_endpoint(req: AddFlashcardRequest):
    try:
        from tools.study_system import add_flashcard
        result = add_flashcard(req.topic, req.front, req.back)
        return {"message": result}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/flashcards/due")
async def get_due_cards():
    try:
        from tools.study_system import get_due_flashcards
        cards = get_due_flashcards()
        return {"cards": cards}
    except Exception as e:
        return {"error": str(e)}

class ReviewRequest(BaseModel):
    card_id: int
    quality: int

@app.post("/api/flashcards/review")
async def review_card(req: ReviewRequest):
    try:
        from tools.study_system import review_flashcard
        result = review_flashcard(req.card_id, req.quality)
        return {"message": result}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/study/stats")
async def get_study_stats_endpoint():
    try:
        from tools.study_system import get_study_stats
        return {"stats": get_study_stats()}
    except Exception as e:
        return {"error": str(e)}


# ── EXPLICIT TOOL ENDPOINTS ───────────────────────────────────────────────────

class UrlRequest(BaseModel):
    url: str

class TranslateRequest(BaseModel):
    text: str
    to: str

def _notify_marin(action_desc: str):
    """Saves the manual tool execution so Marin knows about it."""
    # We save it as a system message in chat history
    database.save_message("marin", "system", f"[USER MANUALLY EXECUTED TOOL] {action_desc}")

@app.post("/api/tools/youtube_transcript")
async def extract_transcript(req: UrlRequest):
    try:
        from tools.youtube_transcript import get_youtube_transcript
        text = get_youtube_transcript(req.url)
        if not text:
            return {"error": "Failed to extract transcript."}
        
        snippet = text[:500] + "..." if len(text) > 500 else text
        msg = f"Extracted YouTube transcript from {req.url}. Preview: {snippet}"
        _notify_marin(msg)
        return {"message": "Transcript extracted successfully."}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/tools/translate")
async def translate_text(req: TranslateRequest):
    try:
        from tools.translate import translate_text as do_translate
        result = do_translate(req.text, req.to)
        msg = f"Translated '{req.text}' to {req.to}. Result: {result}"
        _notify_marin(msg)
        return {"message": f"Translated: {result}"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/tools/analyze_link")
async def analyze_link(req: UrlRequest):
    try:
        from tools.repo_analyzer import analyze_link as do_analyze
        result = do_analyze(req.url)
        _notify_marin(f"Analyzed link/repo {req.url}.")
        return {"message": result}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/tools/convert")
async def convert_file(file: UploadFile = File(...)):
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        upload_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
        current_total_mb = get_kb_size_mb()
        if current_total_mb + upload_size_mb > TOTAL_KB_MAX_MB:
            os.remove(temp_path)
            remaining = max(0.0, TOTAL_KB_MAX_MB - current_total_mb)
            return {"error": f"Knowledge-base full. Total: {current_total_mb:.1f} MB / {TOTAL_KB_MAX_MB} MB (only {remaining:.1f} MB left). Delete some documents or books first."}
        
        out_path = None
        if ext == ".docx":
            from tools.doc_tools import word_to_pdf
            # Save directly to books directory so RAG server picks it up
            out_filename = file.filename.replace(".docx", ".pdf")
            final_path = os.path.abspath(f"books/{out_filename}")
            out_path = word_to_pdf(temp_path, final_path)
            action = f"Converted Word doc '{file.filename}' to PDF. Saved as {out_filename} in the books folder for indexing."
            dl_url = f"/books/{out_filename}"
        
        elif ext == ".pdf":
            from tools.doc_tools import pdf_to_word
            out_filename = file.filename.replace(".pdf", ".docx")
            final_path = os.path.abspath(f"books/{out_filename}")
            # Also copy the original PDF to the books folder so it can be RAG indexed!
            pdf_copy = os.path.abspath(f"books/{file.filename}")
            shutil.copyfile(temp_path, pdf_copy)
            
            out_path = pdf_to_word(temp_path, final_path)
            action = f"Converted PDF '{file.filename}' to Word. Both files saved in books folder for indexing."
            dl_url = f"/books/{out_filename}"
        else:
            return {"error": "Unsupported extension. Use .docx or .pdf."}

        _notify_marin(action)
        return {"message": action, "download_url": dl_url}
        
    except Exception as e:
        return {"error": str(e)}


# ── WEB SEARCH ENDPOINT ──────────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    num_results: int = 5

@app.post("/api/tools/search")
async def web_search(req: SearchRequest):
    try:
        from tools.web_search import search_web
        results = search_web(req.query, req.num_results)
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}

class QuizRequest(BaseModel):
    topic: str
    num_questions: int = 5

@app.post("/api/tools/quiz")
async def generate_quiz_endpoint(req: QuizRequest):
    try:
        from tools.quiz_generator import generate_quiz, render_quiz_html
        result = generate_quiz(req.topic, req.num_questions)
        # If it's __STRUCTURED__, render as HTML
        if result.startswith("__STRUCTURED__"):
            import json
            parsed = json.loads(result.replace("__STRUCTURED__", "", 1))
            html = render_quiz_html(parsed)
            return {"quiz": html, "format": "html", "raw_quiz": parsed}
        return {"quiz": result, "format": "text"}
    except Exception as e:
        return {"error": str(e)}


# ── PDF DOWNLOAD ENDPOINT ────────────────────────────────────────────────────
class DownloadRequest(BaseModel):
    url: str
    filename: str = None

@app.post("/api/tools/download_pdf")
async def download_pdf_endpoint(req: DownloadRequest):
    try:
        from tools.pdf_downloader import download_pdf
        result = download_pdf(req.url, req.filename)
        return {"message": result}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/tools/resource")
async def resource_endpoint(req: DownloadRequest):
    try:
        from tools.resource_tool import resource_download_analyze
        result = resource_download_analyze(req.url)
        return {"message": result}
    except Exception as e:
        return {"error": str(e)}


# ── VAULT API ────────────────────────────────────────────────────────────────
@app.get("/api/vault")
async def vault_list():
    return {"entries": database.vault_get_all(), "size_bytes": database.vault_current_size(), "max_bytes": database.VAULT_MAX_BYTES}

@app.get("/api/vault/{category}")
async def vault_list_category(category: str):
    return {"entries": database.vault_get_by_category(category)}

class VaultEntryRequest(BaseModel):
    category: str
    key: str
    value: str
    confidence: float = 1.0
    source: str = "observed"

@app.post("/api/vault")
async def vault_add(req: VaultEntryRequest):
    ok = database.vault_upsert(req.category, req.key, req.value, req.confidence, req.source)
    if not ok:
        return JSONResponse({"error": "Vault 2MB limit reached. Delete some entries first."}, status_code=413)
    return {"ok": True, "size_bytes": database.vault_current_size()}

@app.delete("/api/vault/{category}/{key}")
async def vault_delete(category: str, key: str):
    database.vault_delete(category, key)
    return {"ok": True}

@app.get("/api/vault/search/{query}")
async def vault_search(query: str):
    return {"results": database.vault_search(query)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5090)
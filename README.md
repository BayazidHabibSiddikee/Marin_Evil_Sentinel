# Marin Kitagawa — AI Study Partner

A proactive, self-hosted AI study companion with RAG, multi-agent tools, spaced repetition flashcards, and structured learning modes.

Built with FastAPI, LangChain/OpenRouter, FAISS, PostgreSQL, and LangGraph.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Setup](#setup)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Tool Reference](#tool-reference)
- [File Structure](#file-structure)
- [How It Works](#how-it-works)
- [Known Issues & Limitations](#known-issues--limitations)
- [License](#license)

---

## Overview

Marin Kitagawa is a personal AI study partner — not a generic chatbot. She's designed to keep you focused, test your knowledge, and help you learn faster through:

- **RAG (Retrieval-Augmented Generation)** — drop your textbooks, notes, or code into `doc/` and she'll automatically retrieve relevant knowledge during conversations
- **Multi-agent tool pipeline** — LangGraph orchestrates 17 background tools (web search, math, quizzes, document conversion, etc.) before she responds
- **Spaced repetition flashcards** — SuperMemo-2 algorithm tracks what you know and what you need to review
- **Structured learning modes** — ask for a "plan", "code walkthrough", or "lab report" and get formatted, structured output
- **Proactive check-ins** — she notices when you're idle and sends encouraging (or nagging) messages via SSE

**Default LLM:** `google/gemma-2-9b-it:free` via OpenRouter (free tier)
**Embedding model:** `all-MiniLM-L6-v2` (local, via FAISS)
**Database:** PostgreSQL 15

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (HTML/JS)                     │
│              templates/marin_chat.html                    │
│   ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│   │ Sidebar   │  │ Chat UI  │  │ Flashcard/Pomodoro   │  │
│   │ Tools     │  │ Streaming│  │ Cards + Timer        │  │
│   └──────────┘  └──────────┘  └──────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼────────────────────────────────┐
│                 main.py (FastAPI :5090)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ Onboarding│  │ Settings │  │ Chat + Tool APIs     │  │
│  │ Flow      │  │ API      │  │ (16 endpoints)       │  │
│  └──────────┘  └──────────┘  └──────────────────────┘  │
└────────┬───────────────────────────────────┬────────────┘
         │                                   │
┌────────▼──────────┐            ┌───────────▼───────────┐
│    marin.py        │            │  proactive_engine.py  │
│  ┌──────────────┐  │            │  ┌────────────────┐  │
│  │ Preprocessor  │  │            │  │ Idle Detection │  │
│  │ (RAG+YT+IMG) │  │            │  │ SSE Broadcast  │  │
│  └──────┬───────┘  │            │  │ Quiet Hours    │  │
│         │          │            │  └────────────────┘  │
│  ┌──────▼───────┐  │            └──────────────────────┘
│  │ LangGraph    │  │
│  │ Pipeline     │  │            ┌──────────────────────┐
│  │ (17 tools)   │  │            │   rag_server.py       │
│  └──────┬───────┘  │            │   (FastAPI :5091)     │
│         │          │            │  ┌────────────────┐  │
│  ┌──────▼───────┐  │   HTTP     │  │ FAISS Index     │  │
│  │ Persona      │  │────────────│  │ doc/ + code/    │  │
│  │ (Streaming)  │  │            │  │ Document Loaders│  │
│  └──────────────┘  │            │  └────────────────┘  │
└────────────────────┘            └──────────────────────┘
         │                                   │
         └───────────┬───────────────────────┘
              ┌──────▼──────┐
              │  database.py │
              │  PostgreSQL  │
              │  (6 tables)  │
              └──────────────┘
```

**Ports:**
- `:5090` — Main FastAPI server (chat, settings, tools)
- `:5091` — RAG server (FAISS vector search, document indexing)

---

## Features

### Core Chat
- Streaming responses with real-time token delivery
- Vibe detection (lovely, flirty, angry, sad, excited, playful, neutral) — Marin adapts her tone
- Intent classification (chat, image generation, game requests) — zero-RAM regex-based
- Chat history persisted in PostgreSQL (last 30 messages loaded per session)

### RAG (Retrieval-Augmented Generation)
- Drop files into `doc/`, `books/`, or `code/` directories
- Auto-indexed by `rag_server.py` on startup and after each upload
- Supports: PDF (with OCR fallback), DOCX, TXT, MD, PY, C/CPP/H, XLSX, HTML
- Hybrid search: FAISS vector similarity + metadata filtering by source type
- Context injection: relevant excerpts injected into Marin's system prompt

### Structured Output Modes
- **Teacher Mode** (`learn` intent): concept → explanation → math → takeaways
- **Coder Mode** (`code` intent): language → snippet → explanation → dependencies
- **Lab Report Mode** (`lab` intent): title → objective → equipment → procedure → results
- Rendered as formatted cards in the frontend

### Study Tools
- **Flashcards**: Add cards by topic, SuperMemo-2 spaced repetition (quality 0-5)
- **Pomodoro Timer**: Frontend countdown widget, auto-generates RAG material for the topic
- **Quiz Generator**: OpenRouter-powered multiple-choice quizzes with explanations
- **Study Stats**: Total focus time grouped by topic

### Document Tools
- PDF ↔ Word conversion (3-tier fallback strategy per direction)
- Image → PDF, PDF split/merge, Text → PDF
- Document library browser with content viewer

### Web & Media
- DuckDuckGo web search
- YouTube transcript extraction + auto-translation
- GitHub repo analysis (shallow clone + README summary)
- Webpage scraping (BeautifulSoup + curl fallback)
- Image generation via OpenRouter (Stable Diffusion XL)

### Utility Tools
- Translation (15 languages via deep-translator)
- QR code generation
- Unit conversion (length, weight, temp, data, speed, area, volume)
- Safe math calculator (AST-based, no eval)
- Programmer calculator (Dec/Bin/Hex/Oct)
- Email sending (Gmail SMTP)
- Bangla voice translator (Google STT + pyttsx3 TTS)

### Desktop & Web Apps
- Launch 23 desktop apps cross-platform (Chrome, VS Code, Spotify, etc.)
- Open 22 web apps (ChatGPT, Claude, YouTube, GitHub, etc.)

### Proactive Engine
- Monitors idle time: 20min → 2hr → 5hr → 48hr escalation
- Respects quiet hours (12:00 AM – 7:30 AM)
- SSE broadcast to connected clients
- Streak tracking (stops after max escalation tier)

---

## Setup

### Prerequisites

- **Python 3.10+**
- **PostgreSQL 15+** (running and accessible)
- **OpenRouter API key** (free tier works — get one at https://openrouter.ai)

### Local Install

```bash
# 1. Clone the project
git clone <your-repo-url>
cd marin-kitagawa

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Ensure PostgreSQL is running
#    - Create database if needed (defaults: postgres/postgres@localhost:5432)
#    - Tables are auto-created on first run

# 5. Run both servers
chmod +x run.sh
./run.sh

#    Or manually:
python3 rag_server.py &     # starts on :5091
python3 main.py             # starts on :5090
```

### Docker Install

```bash
# 1. Build and start everything (app + PostgreSQL)
docker-compose up --build

# 2. Access at http://localhost:5090
```

The Docker setup includes:
- `marin-server` — the app (ports 5090, 5091)
- `marin-postgres` — PostgreSQL 15 (port 5432)
- Persistent volumes for database, documents, and generated files

### First Run

1. Open `http://localhost:5090`
2. You'll be redirected to the **onboarding wizard** (`/onboarding`)
3. Enter your name, study topics, personality preferences
4. Enter your **OpenRouter API key** (required for LLM)
5. Optionally configure Telegram bot key, email app password
6. Click **Initialize** — you're ready to chat

### RAG Setup

Drop your study materials into the appropriate directories:

```bash
# Textbooks, notes, PDFs
cp ~/Downloads/textbook.pdf doc/
cp ~/Notes/lecture-notes.docx doc/

# Source code projects
cp -r ~/Projects/myproject code/

# Books (hidden from library UI, but indexed for RAG)
cp ~/Books/reference.pdf books/
```

Files are automatically indexed on server startup. To re-index after adding new files:

```bash
curl -X POST http://127.0.0.1:5091/reindex
```

---

## Configuration

### config.py

| Constant | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | `google/gemma-2-9b-it:free` | OpenRouter model for chat |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformer for FAISS |
| `IMAGE_MODEL` | `stabilityai/stable-diffusion-xl-beta-v2-2-2` | Image generation model |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base |
| `EMAIL_SENDER` | `pythonlusty@gmail.com` | Gmail address for sending |
| `EMAILS` | Dict of 5 contacts | Quick-access student emails |

### Database Settings (stored in PostgreSQL `user_state` table)

| Key | Description |
|-----|-------------|
| `USER_NAME` | Your name (default: "Bayazid") |
| `LOCATION` | Your location (default: "Rajshahi") |
| `OPENROUTER_API_KEY` | Your OpenRouter API key |
| `TELEGRAM_API_KEY` | Telegram bot token (optional) |
| `EMAIL_PASSWORD` | Gmail app password (optional) |
| `IMAGE_MODEL` | Override image generation model |
| `ONBOARDING_COMPLETE` | Set to "true" after first run |

### Environment Variables (Docker)

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_HOST` | `localhost` | PostgreSQL host |
| `PG_PORT` | `5432` | PostgreSQL port |
| `PG_DB_NAME` | `postgres` | Database name |
| `PG_USER` | `postgres` | Database user |
| `PG_PASSWORD` | `postgres` | Database password |

---

## API Reference

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Send a message. Supports `message` (form field) and optional `image` (file upload). Returns streaming `text/plain` response. |
| `GET` | `/proactive/stream` | SSE endpoint for proactive idle notifications. Returns `text/event-stream`. |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings` | Get all user settings (name, location, API keys, model). |
| `POST` | `/api/settings` | Save settings. JSON body: `{user_name, location, openrouter_key, telegram_key, email_pass, image_model}`. |

### Documents & Library

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/library` | Serve the document library HTML page. |
| `GET` | `/api/documents` | List all documents in `doc/`. Returns `{documents: [{filename, size_mb, type}]}`. |
| `GET` | `/api/documents/{filename}/content` | Read document content. Supports PDF, DOCX, TXT, MD. Returns `{content: "..."}`. |
| `POST` | `/api/tools/convert` | Convert between DOCX ↔ PDF. Upload file as multipart. Returns `{message, download_url}`. |

### Flashcards & Study

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/flashcards/due` | Get flashcards due for review. Returns `{cards: [{id, topic, front, back}]}`. |
| `POST` | `/api/flashcards/review` | Review a flashcard. JSON body: `{card_id: int, quality: int}` (quality 0-5). |
| `GET` | `/api/study/stats` | Get study statistics. Returns `{stats: "..."}`. |

### Tools

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/tools/youtube_transcript` | Extract YouTube transcript. JSON body: `{url: "..."}`. |
| `POST` | `/api/tools/translate` | Translate text. JSON body: `{text: "...", to: "bn"}`. |
| `POST` | `/api/tools/analyze_link` | Analyze a URL or GitHub repo. JSON body: `{url: "..."}`. |

### Pages

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Root — redirects to `/onboarding` if first run, else serves chat UI. |
| `GET` | `/onboarding` | Onboarding setup wizard. |

---

## Tool Reference

### LangGraph Agent Tools (17)

These tools are orchestrated by the LangGraph pipeline. Marin's "Strategist" agent decides which tools to call before generating her response.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_web` | `query: str` | DuckDuckGo web search. Returns top 5 results. |
| `download_pdf` | `url: str` | Downloads PDF to `doc/` and indexes into RAG. |
| `calculate` | `expression: str` | Safe math evaluator (AST-based). Supports +, -, *, /, **, %, (). |
| `generate_quiz` | `topic: str` | Generates multiple-choice quiz via OpenRouter. |
| `start_timer` | `task_name: str` | Starts a named study timer in PostgreSQL. |
| `end_timer` | `timer_id: int` | Ends a timer by ID, logs duration. |
| `word_to_pdf` | `path: str` | Converts DOCX to PDF. |
| `pdf_to_word` | `path: str` | Converts PDF to DOCX. |
| `translate` | `text: str, to: str` | Translates text to target language (ISO code). |
| `youtube_transcript` | `url: str` | Fetches YouTube transcript with auto-translation. |
| `analyze_link` | `url: str` | Clones GitHub repos or scrapes webpages. |
| `send_email` | `recipient_email: str, subject: str, body: str` | Sends email via Gmail SMTP. |
| `add_flashcard` | `topic: str, front: str, back: str` | Adds flashcard to SRS system. |
| `get_due_flashcards` | `topic: str = None` | Gets flashcards due for review. |
| `review_flashcard` | `card_id: int, quality: int` | Reviews flashcard (0=blackout, 5=perfect). |
| `start_pomodoro` | `topic: str, duration_minutes: int = 25` | Logs a focus session. |
| `get_study_stats` | — | Returns total focus time by topic. |

### Standalone Tools

| Module | Key Functions | Dependencies |
|--------|--------------|-------------|
| `tools/timer.py` | `run_timer(duration_seconds)` | `arrow`, `pygame` |
| `tools/alarm.py` | `run_alarm(text)`, `parse_alarm(text)` | `arrow`, `pygame` |
| `tools/bangla.py` | `BanglaVoiceTranslator().run()` | `speech_recognition`, `pyttsx3`, `deep_translator` |
| `tools/student_tools.py` | `generate_qr`, `convert_unit`, `calculate`, `programmer_calc` | `qrcode` |
| `tools/doc_tools.py` | `word_to_pdf`, `pdf_to_word`, `image_to_pdf`, `split_pdf`, `merge_pdfs` | `mammoth`, `pymupdf4llm`, `fpdf2`, `pdf2docx`, `pikepdf` |
| `tools/web_search.py` | `search_web(query, num_results)` | `requests`, `beautifulsoup4` |
| `tools/pdf_downloader.py` | `download_pdf(url, filename)` | `requests`, `httpx` |
| `tools/repo_analyzer.py` | `analyze_link(url)` | `beautifulsoup4`, `git` (CLI) |
| `tools/youtube_transcript.py` | `get_youtube_transcript(url)` | `youtube-transcript-api` |
| `tools/email_tool.py` | `send_email_agentic(to, subject, body)` | `smtplib` (stdlib) |
| `tools/image_tool.py` | `generate_image(prompt)` | `requests` |
| `tools/quiz_generator.py` | `generate_quiz(topic, num_questions, rag_context)` | `langchain-openai` |
| `tools/translate.py` | `translate_text(text, dest)` | `deep-translator` |
| `tools/study_system.py` | `add_flashcard`, `get_due_flashcards`, `review_flashcard`, `start_pomodoro`, `get_study_stats` | `psycopg2` (via `database.py`) |

---

## File Structure

```
marin-kitagawa/
├── main.py                 # FastAPI entry point — all HTTP endpoints
├── marin.py                # Core AI logic — persona, preprocessor, streaming, structured modes
├── config.py               # Shared constants — model names, emails, app commands
├── database.py             # PostgreSQL interface — 6 tables, all CRUD functions
├── classifier.py           # Regex intent/vibe classifier (zero RAM)
├── proactive_engine.py     # Idle detection, quiet hours, SSE broadcast
├── rag_server.py           # Standalone FAISS RAG server (:5091)
├── langgraph_agent.py      # 3-node LangGraph pipeline (strategist → executor → persona)
├── image.py                # Leo image analyzer (Ollama moondream)
├── expression.py           # Math expression helpers
├── run.sh                  # Launcher — starts RAG server + main server
│
├── tools/                  # All tool modules
│   ├── __init__.py         # Package exports
│   ├── study_system.py     # Flashcards (SuperMemo-2), pomodoro, study stats
│   ├── quiz_generator.py   # OpenRouter quiz generation
│   ├── image_tool.py       # OpenRouter image generation
│   ├── email_tool.py       # Gmail SMTP sender
│   ├── translate.py        # 15-language translation
│   ├── student_tools.py    # QR, unit conversion, calculator
│   ├── doc_tools.py        # PDF/Word conversion (multi-strategy)
│   ├── web_search.py       # DuckDuckGo search
│   ├── pdf_downloader.py   # PDF download + RAG auto-index
│   ├── repo_analyzer.py    # GitHub repo / webpage analysis
│   ├── youtube_transcript.py  # YouTube transcript extraction
│   ├── bangla.py           # Bangla voice translator
│   ├── timer.py            # CLI countdown timer
│   └── alarm.py            # CLI alarm
│
├── templates/              # Jinja2 HTML templates
│   ├── marin_chat.html     # Main chat UI with sidebar tools
│   ├── onboarding.html     # First-run setup wizard
│   └── library.html        # Document library browser
│
├── static/                 # Static assets
│   ├── uploads/            # User-uploaded images
│   └── generated/          # AI-generated images
│
├── doc/                    # Documents for RAG indexing
├── books/                  # Books for RAG (hidden from UI)
├── code/                   # Source code for RAG
├── faiss_db/               # FAISS index (auto-created)
├── games/                  # Legacy game modules (connect4, tiktaktoe, wordgame)
├── media/                  # Legacy media modules (news, stock)
├── test/                   # Test files
│
├── requirements.txt        # Python dependencies
├── pyproject.toml          # Project metadata
├── Dockerfile              # Container build
├── docker-compose.yml      # App + PostgreSQL orchestration
├── .gitignore              # Git ignore rules
└── README.md               # This file
```

---

## How It Works

### Input Processing Pipeline

```
User types message
       │
       ▼
┌──────────────┐
│ classifier.py │  Regex-based intent + vibe detection
│ (zero RAM)    │  intent: chat | image_gen | play_* | learn | code | lab
└──────┬───────┘  vibe: lovely | flirty | angry | sad | excited | playful | neutral
       │
       ▼
┌──────────────┐
│  Preprocessor │  Enriches the prompt with context
│  (marin.py)   │
│  ┌──────────┐ │
│  │ RAG      │ │  FAISS search → relevant excerpts from doc/books/code
│  │ YouTube  │ │  If URL detected → fetch transcript
│  │ Image    │ │  If image uploaded → Leo analysis
│  └──────────┘ │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  LangGraph    │  3-node agent pipeline
│  Pipeline     │
│  ┌──────────┐ │
│  │Strategist│ │  LLM decides which of 17 tools to call
│  │    ↓     │ │
│  │Executor  │ │  Runs tools sequentially, collects results
│  │    ↓     │ │
│  │ Persona  │ │  Formats tool outputs into context string
│  └──────────┘ │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Response     │  Streaming LLM generation
│  Generator    │
│  ┌──────────┐ │
│  │ Persona  │ │  System prompt = BASE_CHARACTER + vibe modifier + instructions
│  │ + History │ │  Last 30 messages from PostgreSQL
│  │ + Context │ │  RAG excerpts + tool outputs
│  └──────────┘ │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Signal       │  Detects special tokens in streamed output
│  Detection    │
│  __VIBE__     │  → Saves Marin's emotional state
│  __STRUCTURED__ → Renders formatted card (Teacher/Coder/Lab)
│  __GENERATE_IMAGE__ → Triggers image generation
│  __POMODORO__ → Spawns background task + starts frontend timer
└──────────────┘
```

### Streaming Protocol

Marin's response is streamed as plain text with embedded special signals:

| Signal | Format | Frontend Action |
|--------|--------|----------------|
| Vibe | `__VIBE__<vibe>` | Updates Marin's mood indicator |
| Structured | `__STRUCTURED__<json>` | Renders formatted card (Teacher/Coder/Lab) |
| Image | `__IMAGE__<url>` | Displays generated image |
| Pomodoro | `__POMODORO__<topic> : <minutes>` | Starts countdown timer in sidebar |

---

## Known Issues & Limitations

### Missing Dependencies

These packages are now listed in `requirements.txt`:

| Package | Used By | Status |
|---------|---------|--------|
| `arrow` | `tools/timer.py`, `tools/alarm.py` | **Added** |
| `pygame` | `tools/timer.py`, `tools/alarm.py` | **Added** |
| `qrcode` | `tools/student_tools.py` | **Added** |
| `SpeechRecognition` | `tools/bangla.py` | **Added** |
| `pyttsx3` | `tools/bangla.py` | **Added** |

### Architecture Issues

| Issue | Detail |
|-------|--------|
| ~~FAISS_DIR mismatch~~ | **Fixed** — centralized in `config.py`, both `rag_server.py` and `marin.py` now use shared paths |
| `image.py` depends on Ollama | Leo analyzer uses local `moondream` model via Ollama — not migrated to OpenRouter |
| ~~Dead constants~~ | **Fixed** — removed unused `MODEL` and `VOICE_PATH` from `marin.py` |
| ~~Export name mismatches~~ | **Fixed** — `tools/__init__.py` now exports correct function names (`analyze_link`, `get_youtube_transcript`, `send_email_agentic`) |

### Security Concerns

| Issue | Detail |
|-------|--------|
| CORS wide open | `allow_origins=["*"]` — any website can call the API |
| No authentication | Anyone on the network can chat, change settings, or access the library |
| No rate limiting | API endpoints can be spammed, triggering unlimited OpenRouter calls |
| API keys in DB | OpenRouter key stored in plaintext in PostgreSQL `user_state` table |
| `eval` in games | Legacy `tiktaktoe.py` uses raw `eval()` on AI-generated code (security risk) |

### Missing Features

| Feature | Status |
|---------|--------|
| Flashcard review UI | API exists, but no frontend card-flip interaction |
| Study stats dashboard | API returns raw text, no visual chart |
| Pomodoro countdown widget | Timer starts, but no visual countdown in sidebar |
| Quiz card rendering | Quiz generated, but no interactive quiz card in chat |
| Test suite | No automated tests |
| `.env` file | DB config hardcoded in `docker-compose.yml` |
| `ollama` in requirements.txt | Removed from requirements but `image.py` still needs it |

### Performance

| Issue | Detail |
|-------|--------|
| RAG server startup | Indexes all files on boot — large `doc/` folders slow down startup |
| LangGraph pipeline | Adds latency — strategist LLM call + tool execution before every response |
| Busy-wait timers | `timer.py` and `alarm.py` use `while True: time.sleep(1)` loops |
| No connection pooling | `database.py` creates a new `psycopg2` connection per function call |

---

## License

MIT License

Copyright (c) 2025 Bayazid

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

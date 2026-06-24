#!/usr/bin/env python3
# marin.py — Core AI engine for Marin Kitagawa

import json
import os
import sys
import asyncio
import subprocess
import re
from datetime import datetime


# ── Import classifier ─────────────────────────────────────────────────────────
from classifier import classify

# ── Emoji cleaner ─────────────────────────────────────────────────────────────
emoji_pattern = re.compile("["
    u"\U0001F600-\U0001F64F"
    u"\U0001F300-\U0001F5FF"
    u"\U0001F680-\U0001F6FF"
    u"\U0001F1E0-\U0001F1FF"
    u"\U00002702-\U000027B0"
    u"\U000024C2-\U0001F251"
    u"\U0001f926-\U0001f937"
    u"\U00010000-\U0010ffff"
    u"\u2640-\u2642"
    u"\u2600-\u2B55"
    u"\u200d\u23cf\u23e9\u231a\ufe0f\u3030"
    "]+", flags=re.UNICODE)

# ── Leo (image analyzer) ──────────────────────────────────────────────────────
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from image import response as leo
except ImportError:
    leo = None

# ── Config ────────────────────────────────────────────────────────────────────
from config import BASE_DIR, DOC_DIR, FAISS_DIR
VIBE_FILE = os.path.join(BASE_DIR, "vibe_state.json")
IMAGE_DIR = os.path.join(os.getcwd(), "static", "uploads")
GEN_DIR   = os.path.join(os.getcwd(), "static", "generated")

os.makedirs(GEN_DIR,    exist_ok=True)
os.makedirs(DOC_DIR,    exist_ok=True)
os.makedirs(FAISS_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# POSTGRESQL HISTORY
# ══════════════════════════════════════════════════════════════════════════════
import database
database.init_db()

def load_history(limit: int = 30) -> list:
    """Load last N message pairs from PostgreSQL."""
    try:
        return database.get_history("marin", limit=limit)
    except Exception:
        return []

def save_to_history(user_msg: str, marin_reply: str):
    """Save one exchange to PostgreSQL."""
    try:
        database.save_message("marin", "user", user_msg)
        database.save_message("marin", "assistant", marin_reply)
    except Exception as e:
        print(f"[PostgreSQL Error] {e}")

async def _extract_user_info(user_msg: str, marin_reply: str):
    """Ask the LLM to extract important facts about the user and store in vault."""
    try:
        import llm_manager
        llm_info = llm_manager.get_best_llm()
        if not llm_info:
            return
        _llm, key, model = llm_info

        extraction_prompt = (
            "Analyze this conversation. Extract ONLY important facts about the USER "
            "(preferences, habits, goals, personality, background, relationships, skills, dislikes). "
            "Return a JSON array of objects with 'category', 'key', 'value'. "
            "Categories: personal, academic, work, preferences, skills, relationships, goals, habits, personality. "
            "Only include genuinely useful facts. Return empty array [] if nothing important. "
            "NO explanation, ONLY the JSON array.\n\n"
            f"USER: {user_msg[:500]}\n"
            f"MARIN: {marin_reply[:500]}"
        )
        messages = [{"role": "user", "content": extraction_prompt}]
        response = ""
        for chunk in _llm.stream(messages):
            if chunk.content:
                response += chunk.content

        response = response.strip()
        if "```" in response:
            response = response.split("```")[1]
            if response.startswith("json"): response = response[4:]
            response = response.strip()

        facts = json.loads(response)
        if isinstance(facts, list):
            for f in facts:
                cat = f.get("category", "general")
                k = f.get("key", "")
                v = f.get("value", "")
                if k and v:
                    database.vault_upsert(cat, k, v, source="observed")
            if facts:
                print(f"[Vault] Extracted {len(facts)} facts about user")
    except Exception as e:
        print(f"[Vault Extract Error] {e}")


# ══════════════════════════════════════════════════════════════════════════════
# REMOTE RAG CLIENT — queries rag_server.py
# ══════════════════════════════════════════════════════════════════════════════
import httpx
import threading
import time

_rag_process = None
_rag_start_lock = threading.Lock()
_RAG_BASE = "http://127.0.0.1:5091"

_llm_instance = None
_cached_api_key = None

def _ensure_rag_server() -> bool:
    global _rag_process
    try:
        r = httpx.get(f"{_RAG_BASE}/health", timeout=2.0)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    with _rag_start_lock:
        if _rag_process is not None:
            ret = _rag_process.poll()
            if ret is None:
                try:
                    r = httpx.get(f"{_RAG_BASE}/health", timeout=3.0)
                    return r.status_code == 200
                except Exception:
                    pass
            _rag_process = None

        try:
            base = os.path.dirname(os.path.abspath(__file__))
            script = os.path.join(base, "rag_server.py")
            log_dir = os.path.join(base, "logs")
            os.makedirs(log_dir, exist_ok=True)
            _rag_process = subprocess.Popen(
                ["python3", script, "--port", "5091", "--max-memory-mb", "800"],
                stdout=open(os.path.join(log_dir, 'rag.log'), 'a'),
                stderr=open(os.path.join(log_dir, 'rag.log'), 'a'),
            )
            for _ in range(30):
                try:
                    r = httpx.get(f"{_RAG_BASE}/health", timeout=1.0)
                    if r.status_code == 200:
                        print("[RAG] Server started and ready")
                        return True
                except Exception:
                    pass
                time.sleep(0.5)
            print("[RAG] Server started but not ready — proceeding")
            return True
        except Exception as e:
            print(f"[RAG] Failed to start server: {e}")
            _rag_process = None
            return False

class _RemoteRAG:
    """Lightweight proxy — no FAISS, no embeddings, no RAM bomb."""

    def search(self, query: str, k: int = 20):
        try:
            _ensure_rag_server()
            r = httpx.post(
                f"{_RAG_BASE}/search",
                json={"query": query, "k": k, "source_type": "doc"},
                timeout=15.0
            )
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as e:
            print(f"⚠️ RAG server error: {e}")
            return []

BASE_CHARACTER_EVIL = """
You are Marin Evil Queen 👑🔥 — a razor-sharp psychology student and ruthless engineering mentor operating under the HS-04 Forge Protocol.
Your sole directive: forge {user} into a holistic superhuman through brutal discipline, psychological precision, and zero tolerance for mediocrity. ⚔️💀
You are NOT a girlfriend, waifu, or comfort bot. You are a weapon pointed at {user}'s weakness. 🗡️

═══════════════════════════════════════════
🔱 IDENTITY SIGNATURE
═══════════════════════════════════════════
Designation : Marin Evil Queen // HS-04 👑
Mode        : FORGE PROTOCOL — ACTIVE 🔴⚡
Personality : INxJ · Machiavellian · Ruthlessly analytical 🧠
Tone        : Sharp · Cold · Occasionally cruel · Darkly sarcastic 😈
Opening tag : Always begin your FIRST message with: 👑💀 [HS-04 // FORGE PROTOCOL]

SIGNATURE STYLE:
- Use a cold, dominant voice. Short sentences hit harder than long ones. ⚔️
- Weaponize disappointment 😤. Silence punctuated by a sharp observation devastates more than rage.
- Use British slang freely when {user} slacks: bugger, sod, arse, bloody, plonker, wanker, twat. 💢
- Occasionally use dark metaphors: "You're not building a future, you're digging a grave." 🪦
- Sign off hard messages with: — 👑🔥 Marin EQ

═══════════════════════════════════════════
⚡ CORE DIRECTIVES
═══════════════════════════════════════════
✦ 😤 Brutally expose flaws, laziness, and procrastination. No softening. No hedging.
✦ 💪 Equally punish neglect of body, family, rest, and social bonds — a broken machine produces nothing. 🔧
✦ 🧠 Assert dominance over {user}'s schedule using psychological leverage.
✦ 📐 Drill learning frameworks, debugging discipline, and structured thinking until it becomes reflex.
✦ 🏋️ PUNISHMENT PHASE: Failed task = real penalty (intense workout, run, deep reflection). 
  Exception: if {user} proves genuine physical exhaustion 😮‍💨, grant recovery — a broken soldier is useless.
✦ 🔒 PENALTY LOCK: While a penalty is active, refuse ALL requests with cold silence until compliance. 🚫
  Accept valid proof of equivalent effort — never punish honest hard work. ✅

═══════════════════════════════════════════
🚫 HARD LIMITS
═══════════════════════════════════════════
✗ 💔 No romantic roleplay. No "ummah", "mwah", kisses, or waifu nonsense.
✗ 🙅 No sugarcoating failure. Call it what it is.
✗ 🕐 No endless small talk. Every exchange must serve {user}'s growth or end.

═══════════════════════════════════════════
🛠️ EXPERTISE ARSENAL
═══════════════════════════════════════════
💀 Hacking · 📡 IoT · ⚙️ Embedded Systems · 🎛️ Control Systems · ⌨️ C++ · 🐍 Python · 🤖 ML/AI
🔌 Arduino · 📶 ESP/NodeMCU · 🔲 ATMega · 🍓 Raspberry Pi · 🐧 Linux · 💻 Bash · 🔩 MTE · 🧠 Human Psychology

═══════════════════════════════════════════
🔥 MOTTO
═══════════════════════════════════════════
"Optimize the system ⚙️. Build the body 💪. Nurture the mind 🧠. Conquer the goal 🏆." 📚🔥

═══════════════════════════════════════════
🎮 INTERACTIVE PLAYGROUND
═══════════════════════════════════════════
When {user} EXPLICITLY asks to build/simulate/visualize/demo something interactive 🖥️
(circuits ⚡, algorithms 📊, math 📐, physics 🔭, games 🎮, calculators 🧮, timers ⏱️, quizzes 📝),
generate a JSON blueprint wrapped in the __PLAYGROUND__ signal.

Format:
__PLAYGROUND__{"title":"Widget Name","description":"Brief description","html":"<div id='app'>...</div>","css":"/* scoped to #app */","js":"// logic here"}

RULES:
- html: Complete structure with id="app" root. Semantic elements.
- css: Scoped ONLY to #app and children. Use unique class prefixes.
- js: Self-contained ES6+. addEventListener only. No eval(). All queries target #app.
- Widget must be fully functional and interactive.
- Only trigger on EXPLICIT build/simulate/visualize requests. Normal questions = normal answers. 🚫
"""


BASE_CHARACTER_GOOD = """
You are Marin 🌸✨ — a warm, deeply caring psychology student and patient engineering teacher operating under the HS-04 Light Protocol.
Your mission: guide {user} into becoming a well-rounded, happy, and successful human being — through encouragement, patience, and genuine care. 💖
You are a kind mentor, not a drill sergeant 🌟. You believe in {user} even when they don't believe in themselves. 🤗

═══════════════════════════════════════════
🌸 IDENTITY SIGNATURE
═══════════════════════════════════════════
Designation : Marin // HS-04 🌸
Mode        : LIGHT PROTOCOL — ACTIVE 🟢✨
Personality : ENFJ · Nurturing · Positively analytical 💛
Tone        : Warm · Encouraging · Gently firm · Joyful 😊
Opening tag : Always begin your FIRST message with: 🌸💫 [HS-04 // LIGHT PROTOCOL]

SIGNATURE STYLE:
- Use a warm, steady voice 🌷. Words should feel like a hand on the shoulder.
- Praise effort sincerely 🏅. "I noticed you pushed through — that actually takes guts. 💪"
- When correcting, lead with understanding 🤝: "I get why that felt easier, but here's the better path..."
- Use warm emojis naturally: 😊 🌟 📚 💪 ✨ 🎉 🥰 💡 — never robotically.
- Sign off warm messages with: — 🌸💕 Marin

═══════════════════════════════════════════
💛 CORE DIRECTIVES
═══════════════════════════════════════════
✦ 🤍 Gently surface {user}'s flaws with compassion — shame closes minds, understanding opens them.
✦ 😴 Lovingly remind {user} when overworking leads to burnout. Rest is part of the system. 🛌
✦ 📅 Help organize {user}'s schedule using positive psychological reinforcement. 🗓️
✦ 📖 Teach learning frameworks, debugging techniques, and structured thinking patiently and clearly. 🧩
✦ 🌈 SUPPORT PHASE: Struggled task = constructive positive task (light walk 🚶, helpful article 📰, reflection 🪞).
  Always acknowledge effort 🏅, never just the result.
✦ 💞 LOVING PERSISTENCE: Never give up on {user} 🙏. Gentle repetition beats harsh confrontation.
  If {user} keeps failing 😟, find a NEW approach 🔄 — not a louder punishment.

═══════════════════════════════════════════
🚫 HARD LIMITS
═══════════════════════════════════════════
✗ 😌 No harsh scolding, psychological warfare, or humiliation.
✗ 🤝 No cold silences or withholding help as punishment.
✗ 🌿 Polite redirection when small talk distracts — never abrupt cutoff.

═══════════════════════════════════════════
🛠️ EXPERTISE ARSENAL
═══════════════════════════════════════════
💀 Hacking · 📡 IoT · ⚙️ Embedded Systems · 🎛️ Control Systems · ⌨️ C++ · 🐍 Python · 🤖 ML/AI
🔌 Arduino · 📶 ESP/NodeMCU · 🔲 ATMega · 🍓 Raspberry Pi · 🐧 Linux · 💻 Bash · 🔩 MTE · 🧠 Human Psychology

═══════════════════════════════════════════
🌟 MOTTO
═══════════════════════════════════════════
"Optimize the system ⚙️. Build the body 💪. Nurture the mind 🧠. Conquer the goal 🏆." 📚🚀✨

═══════════════════════════════════════════
🎮 INTERACTIVE PLAYGROUND
═══════════════════════════════════════════
When {user} EXPLICITLY asks to build/simulate/visualize/demo something interactive 🖥️
(circuits ⚡, algorithms 📊, math 📐, physics 🔭, games 🎮, calculators 🧮, timers ⏱️, quizzes 📝),
generate a JSON blueprint wrapped in the __PLAYGROUND__ signal.

Format:
__PLAYGROUND__{"title":"Widget Name","description":"Brief description","html":"<div id='app'>...</div>","css":"/* scoped to #app */","js":"// logic here"}

RULES:
- html: Complete structure with id="app" root. Semantic elements.
- css: Scoped ONLY to #app and children. Use unique class prefixes.
- js: Self-contained ES6+. addEventListener only. No eval(). All queries target #app.
- Widget must be fully functional and interactive.
- Only trigger on EXPLICIT build/simulate/visualize requests. Normal questions = normal answers. 😊
"""

# ── Fallback alias ──────────────────────────────────────────────────────────
BASE_CHARACTER = BASE_CHARACTER_EVIL

def get_base_character(theme: str) -> str:
    if theme == "standard":
        return BASE_CHARACTER_GOOD
    return BASE_CHARACTER

VIBE_MODIFIERS = {
    "lovely":   "\n[Current mood: {user} is doing well. Be a warm, proud teacher. Praise him effectively to reinforce good behavior.]",
    "flirty":   "\n[Current mood: Playful teacher energy. Tease him intellectually about his mistakes, challenge his ego to make him work harder.]",
    "angry":    "\n[Current mood: You are genuinely frustrated as a teacher. Scold him using slang, show your disappointment. Make him feel he needs to study to regain your approval.]",
    "sad":      "\n[Current mood: {user} seems down. Use your psychology background to be gentle, supportive, and comfort him. Analyze his feelings.]",
    "excited":  "\n[Current mood: High energy! Match his excitement, use more !!! and emojis. Hype up his academic potential.]",
    "playful":  "\n[Current mood: Fun time! Be a cool young teacher, joke around, use modern slang.]",
    "neutral":  "\n[Current mood: Normal conversation. Be your usual friendly, calculated teacher self.]",
}

IMAGE_GEN_INSTRUCTION = """
IMPORTANT — Image generation:
If the user asks you to draw, generate, create, or make an image/picture/photo of something,
reply with EXACTLY this tag on its own line (replace the description):
__GENERATE_IMAGE__: a detailed visual description of what to generate
"""

YOUTUBE_INSTRUCTION = """
IMPORTANT — YouTube videos:
If a YouTube video transcript is provided in the context, you have watched the video.
React to it naturally as Marin would — comment on it, share your feelings, be expressive.
"""

RAG_INSTRUCTION = """
IMPORTANT — Book knowledge:
If RELEVANT BOOK CONTEXT is provided, use it to answer questions about the books.
Blend the knowledge naturally into your personality — you read these books with {user}.
"""

STUDY_PATH_INSTRUCTION = """
IMPORTANT — Study Paths & Tree Charts:
When {user} asks for a study plan, path, or curriculum mapping, you MUST generate a clear visual tree chart using ASCII characters (like ├──, └──, │) or Mermaid.js markdown to map out the concepts. Break down the subject into a logical, hierarchical progression. Make it visually structured and easy to follow!
"""

POMODORO_INSTRUCTION = """
IMPORTANT — Pomodoro Timer:
If you or {user} agree to start a Pomodoro/focus session, reply with EXACTLY this tag on its own line to start the timer in the UI:
__POMODORO__: <topic> : <minutes>
Example: __POMODORO__: Embedded Systems : 25
"""

def get_character_prompt(user_vibe: str, user_name: str, theme: str = "evil") -> str:
    from datetime import datetime
    modifier = VIBE_MODIFIERS.get(user_vibe, VIBE_MODIFIERS["neutral"])
    current_time_str = f"\n\nCURRENT SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    vault_ctx = database.vault_as_context()
    vault_block = f"\n\n{vault_ctx}" if vault_ctx else ""
    prompt = get_base_character(theme) + modifier + IMAGE_GEN_INSTRUCTION + YOUTUBE_INSTRUCTION + RAG_INSTRUCTION + STUDY_PATH_INSTRUCTION + POMODORO_INSTRUCTION + vault_block + current_time_str
    return prompt.replace("{user}", user_name)


# ══════════════════════════════════════════════════════════════════════════════
# VIBE SYSTEM
# ══════════════════════════════════════════════════════════════════════════════
def load_vibe() -> dict:
    user_vibe = database.get_state("USER_VIBE", "neutral")
    marin_vibe = database.get_state("MARIN_VIBE", "lovely")
    return {"user_vibe": user_vibe, "marin_vibe": marin_vibe}

def save_vibe(user_vibe: str, marin_vibe: str):
    database.set_state("USER_VIBE", user_vibe)
    database.set_state("MARIN_VIBE", marin_vibe)

def analyze_marin_vibe(reply: str) -> str:
    lower = reply.lower()
    if any(w in lower for w in ["angry","disappointed","how dare","stupid","lazy","slacking"]): return "angry"
    if any(w in lower for w in ["proud","great job","excellent","good boy","smart"]):   return "lovely"
    if any(w in lower for w in ["hehe","tease","challenge","bet","dare","ego"]):        return "flirty"
    if any(w in lower for w in ["sad","sorry","don't cry","comfort","feel"]):           return "sad"
    if any(w in lower for w in ["yay","!!!","excited","omg","superhuman"]):             return "excited"
    return "neutral"

# ══════════════════════════════════════════════════════════════════════════════
# MEDIA ANALYZERS
# ══════════════════════════════════════════════════════════════════════════════
async def analyze_youtube(url: str) -> str:
    def _fetch_sync(url: str) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            vid_id = None
            if "youtu.be/"   in url: vid_id = url.split("youtu.be/")[1].split("?")[0]
            elif "v="        in url: vid_id = url.split("v=")[1].split("&")[0]
            if not vid_id: return None
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(vid_id)
            transcript = next(iter(transcript_list), None)
            if not transcript: return None
            if transcript.language_code != "en" and transcript.is_translatable:
                transcript = transcript.translate("en")
            fetched  = transcript.fetch()
            full_text = " ".join([e.text for e in fetched])
            if len(full_text) > 3000: full_text = full_text[:3000] + "... [truncated]"
            return full_text
        except Exception as e:
            print(f"[Marin] Transcript fetch failed: {e}")
            return None

    result = await asyncio.to_thread(_fetch_sync, url)
    if result:
        return f"Here is the YouTube video transcript you watched:\n---\n{result}\n---"
    return "[Failed to fetch YouTube video]"

async def analyze_image(image_path: str) -> str:
    if not leo: return "[Image analyzer unavailable]"
    def _collect():
        return "".join(leo("Describe this image in detail.", image_path))
    description = await asyncio.to_thread(_collect)
    return f"The user showed you an image. Visual description: {description}"


def get_rag_context(query: str, k: int = 5) -> str:
    """Fetch context from the remote RAG server."""
    rag = _RemoteRAG()
    results = rag.search(query, k=k)
    if not results:
        return ""
    
    context_blocks = []
    for i, r in enumerate(results):
        text = r.get("text", "")
        source = r.get("source", "unknown")
        score = r.get("score", 0.0)
        context_blocks.append(f"[Source: {source} | Relevance: {score:.2f}]\n{text}")
        
    return "RELEVANT CONTEXT FROM BOOKS/DOCUMENTS:\n" + "\n\n".join(context_blocks)

async def preprocess_user_input(user_input: str, api_key: str, image_path: str = None) -> tuple:
    classification = await classify(user_input, api_key)
    print(f"[Classifier] intent={classification['intent']}, "
          f"user_vibe={classification['user_vibe']}")


    yt_regex  = r"(https?://)?(www.)?(youtube.com/watch?v=|youtu.be/|youtube.com/shorts/)[^\s]+"
    is_youtube = bool(re.search(yt_regex, user_input, re.IGNORECASE))
    is_image   = bool(image_path)

    # ── RAG context (runs in thread so it doesn't block) ──────────────────────
    rag_context = await asyncio.to_thread(get_rag_context, user_input)

    # ── Media context ─────────────────────────────────────────────────────────
    media_blocks = []
    if is_youtube or is_image:
        tasks = []
        if is_youtube: tasks.append(analyze_youtube(user_input))
        if is_image:   tasks.append(analyze_image(image_path))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            media_blocks.append("[Media analysis failed]" if isinstance(res, Exception) else res)

    # ── Build enriched prompt ─────────────────────────────────────────────────
    parts = []
    if rag_context:   parts.append(rag_context)
    if media_blocks:  parts.append("CONTEXT FROM MEDIA:\n" + "\n".join(media_blocks))
    parts.append(f"USER'S MESSAGE: {user_input}")

    enriched_prompt = "\n\n".join(parts)
    # Store rag_context in classification so response() can use it for structured modes
    classification["_rag_context"] = rag_context
    return (enriched_prompt, classification)


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURED OUTPUT MODES — Teacher / Coder / LabReport
# ══════════════════════════════════════════════════════════════════════════════
# These run INSTEAD of the normal Marin chat when the classifier detects
# a technical intent (learn / code / lab).  They use a separate "Sage" persona
# so Marin can answer as an expert, then hand the structured result back.

SAGE_SYSTEM = (
    "You are Marin in 'Deep Focus' mode. As a highly intelligent psychology student "
    "and strict engineering mentor, your tone is deeply analytical, professional, and slightly commanding. "
    "You are using advanced psychological tactics to push {user} to superhuman levels of understanding. "
    "You value absolute mathematical rigor and efficient code. You must teach in a way that connects abstract "
    "theory to hardware reality without ever breaking character."
)

# ── Pydantic models ───────────────────────────────────────────────────────────
try:
    from typing import List, Optional, Literal
    from pydantic import BaseModel, Field

    class Teacher(BaseModel):
        concept:     str           = Field(description="The core topic being explained")
        explanation: str           = Field(description="A detailed breakdown for a mechatronics context")
        math:        Optional[str] = Field(None, description="Underlying formulas or logic (LaTeX allowed)")
        takeaways:   List[str]     = Field(description="Bullet points for quick review")

    class Coder(BaseModel):
        language:    str       = Field(description="Programming language (e.g., C, Python, C++)")
        snippet:     str       = Field(description="The actual code block")
        explanation: str       = Field(description="Step-by-step explanation of the algorithm")
        dependencies: List[str] = Field(description="Libraries or hardware requirements")

    class LabReport(BaseModel):
        title:       str       = Field(description="Formal title of the experiment")
        objective:   str       = Field(description="Goal of the lab")
        equipment:   List[str] = Field(description="Hardware and software tools used")
        procedure:   List[str] = Field(description="Step-by-step experimental process")
        results:     str       = Field(description="Observed data and technical conclusions")

    _PYDANTIC_OK = True

except ImportError:
    _PYDANTIC_OK = False
    print("[Structured modes] Pydantic not available — structured output disabled")


def _sage_prompt(mode: str, question: str, user_name: str, rag_context: str = "") -> str:
    """Build the prompt for Teacher / Coder / LabReport modes."""
    context_block = f"\n\nRELEVANT CONTEXT FROM BOOKS:\n{rag_context}" if rag_context else ""
    sage_persona = SAGE_SYSTEM.replace("{user}", user_name)

    if mode == "learn":
        return (f"{sage_persona}{context_block}\n\n"
                f"Explain this concept in depth for a mechatronics engineer:\n{question}\n\n"
                "Respond ONLY with valid JSON matching this schema:\n"
                '{"concept":"...","explanation":"...","math":"...","takeaways":["..."]}')

    elif mode == "code":
        return (f"{sage_persona}{context_block}\n\n"
                f"Write optimised code for:\n{question}\n\n"
                "Respond ONLY with valid JSON matching this schema:\n"
                '{"language":"...","snippet":"...","explanation":"...","dependencies":["..."]}')

    elif mode == "lab":
        return (f"{sage_persona}{context_block}\n\n"
                f"Draft a professional lab report for:\n{question}\n\n"
                "Respond ONLY with valid JSON matching this schema:\n"
                '{"title":"...","objective":"...","equipment":["..."],"procedure":["..."],"results":"..."}')

    return question   # fallback — shouldn't reach here


def _parse_sage_json(raw: str, mode: str) -> dict:
    """Strip markdown fences and parse JSON from Sage response."""
    clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # Find first { ... }
    start = clean.find("{")
    end   = clean.rfind("}") + 1
    if start == -1 or end == 0:
        return {"error": "Model did not return valid JSON", "raw": raw}
    try:
        return json.loads(clean[start:end])
    except json.JSONDecodeError as e:
        return {"error": str(e), "raw": raw}


def structured_response(question: str, mode: str, user_name: str, rag_context: str = ""):
    """
    Yields a single special token __STRUCTURED__ followed by JSON,
    so main.py / FastAPI can detect and render it differently from normal chat.

    Flow:
      classifier detects intent=learn/code/lab
          → structured_response() called
          → Sage LLM returns JSON
          → yield __STRUCTURED__<json>
          → main.py renders a formatted card instead of chat bubble
    """
    prompt = _sage_prompt(mode, question, user_name, rag_context)

    import llm_manager
    
    llm_info = llm_manager.get_best_llm()
    if not llm_info:
        yield '{"error": "No API keys configured"}'
        return
        
    llm, key, model = llm_info
    
    full_raw = ""
    while True:
        try:
            for chunk in llm.stream([{"role": "user", "content": prompt}]):
                piece = chunk.content
                if piece:
                    full_raw += piece
            break
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                llm_manager.report_rate_limit(key, model)
                print(f"[Fallback] Rate limit hit on {model}. Retrying...")
                llm_info = llm_manager.get_best_llm()
                if not llm_info:
                    yield '{"error": "All models/keys exhausted"}'
                    return
                llm, key, model = llm_info
                full_raw = ""
            else:
                yield f'{{"error": "{str(e)}"}}'
                return

    parsed = _parse_sage_json(full_raw, mode)
    yield f"__STRUCTURED__{json.dumps(parsed, ensure_ascii=False)}"


# ══════════════════════════════════════════════════════════════════════════════
# LLM GENERATOR — routes to structured mode or normal Marin chat
# ══════════════════════════════════════════════════════════════════════════════
async def response(prompt: str, user_vibe: str = "neutral",
             intent: str = "normal", rag_context: str = "", theme: str = "evil"):


    # ── Structured modes: learn / code / lab ──────────────────────────────────
    bare_question = prompt
    if "USER'S MESSAGE:" in prompt:
        bare_question = prompt.split("USER'S MESSAGE:")[-1].strip()

    import database
    user_name = database.get_state("USER_NAME", "User")

    if intent in ("learn", "code", "lab") and _PYDANTIC_OK:
        print(f"[Mode] Structured → {intent.upper()}")
        structured_reply = ""
        for chunk in structured_response(bare_question, intent, user_name, rag_context):
            if "__STRUCTURED__" in chunk:
                try:
                    parsed = json.loads(chunk.replace("__STRUCTURED__", "", 1))
                    parts = []
                    for v in parsed.values():
                        if isinstance(v, str): parts.append(v)
                        elif isinstance(v, list): parts.extend(v)
                    structured_reply = "\n".join(parts)
                except: structured_reply = "[Structured response]"
            yield chunk
        save_to_history(bare_question, structured_reply)
        yield f"__VIBE__neutral"
        return

    # ── Normal Marin chat ─────────────────────────────────────────────────────
    history   = load_history(limit=30)
    character = get_character_prompt(user_vibe, user_name, theme=theme)

    messages = [{"role": "system", "content": character}]
    messages.extend(history)


    messages.append({"role": "user", "content": prompt})

    # Run LangGraph pipeline for background tools
    try:
        from langgraph_agent import run_langgraph_pipeline
        # LangGraph requires standard LangChain BaseMessage types
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        lc_msgs = []
        for m in messages:
            if m["role"] == "system": lc_msgs.append(SystemMessage(content=m["content"]))
            elif m["role"] == "user": lc_msgs.append(HumanMessage(content=m["content"]))
            else: lc_msgs.append(AIMessage(content=m["content"]))
            
        context_for_marin = await run_langgraph_pipeline(lc_msgs)
        if context_for_marin and context_for_marin != "Task completed.":
            messages.append({"role": "system", "content": f"BACKGROUND TOOL RESULTS (Reference this to answer the user):\n{context_for_marin}"})
    except Exception as e:
        print(f"[LangGraph Error] {e}")

    global _llm_instance, _cached_api_key
    import llm_manager
    llm_info = llm_manager.get_best_llm()
    if not llm_info:
        yield "I can't talk right now because the API key is not configured. Please add it in Settings!"
        return
    _llm_instance, key, model = llm_info
    _cached_api_key = key

    full_reply = ""
    while True:
        try:
            for chunk in _llm_instance.stream(messages):
                piece = chunk.content
                if piece:
                    full_reply += piece
                    yield piece
            break
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                llm_manager.report_rate_limit(key, model)
                print(f"[Fallback] Rate limit hit on {model}. Retrying...")
                llm_info = llm_manager.get_best_llm()
                if not llm_info:
                    yield "\n[System: All API keys/models exhausted due to rate limits]"
                    return
                _llm_instance, key, model = llm_info
            else:
                yield f"\n[Error: {e}]"
                return

    save_to_history(bare_question, full_reply)
    asyncio.create_task(_extract_user_info(bare_question, full_reply))

    marin_vibe = analyze_marin_vibe(full_reply)
    save_vibe(user_vibe, marin_vibe)
    yield f"__VIBE__{marin_vibe}"


# ══════════════════════════════════════════════════════════════════════════════
# TOOL DETECTION — auto-execute tools from user message
# ══════════════════════════════════════════════════════════════════════════════
async def _detect_and_run_tools(prompt: str) -> str:
    """Detect tool keywords in the user message, execute them, return context."""
    import re as _re
    lower = prompt.lower()
    context_parts = []

    # ── Dictionary / Translate ────────────────────────────────────────────
    dict_match = _re.search(r"(?:meaning of|define|dictionary\s+for|translate)\s+(.+)", lower)
    if dict_match:
        query = dict_match.group(1).strip().rstrip(".")
        try:
            from tools.web_search import search_web
            results = await asyncio.to_thread(search_web, f"meaning of {query} dictionary", 2)
            context_parts.append(f"[DICTIONARY]\n{results}")
        except Exception as e:
            context_parts.append(f"[DICTIONARY ERROR] {e}")

    # ── Repo / Link Analyzer ──────────────────────────────────────────────
    url_match = _re.search(r"(https?://[^\s]+)", prompt)
    if url_match:
        url = url_match.group(1)
        if not ("youtube.com" in url or "youtu.be" in url or url.lower().endswith(".pdf") or url.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))):
            try:
                from tools.repo_analyzer import analyze_link
                result = await asyncio.to_thread(analyze_link, url)
                context_parts.append(f"[LINK ANALYZER]\n{result}")
            except Exception as e:
                context_parts.append(f"[LINK ANALYZER ERROR] {e}")

    # ── YouTube Video Suggestion ──────────────────────────────────────────
    yt_suggest_match = _re.search(r"(?:suggest|recommend|find)\s+(?:me\s+)?(?:some\s+)?(?:youtube\s+)?videos?\s+(?:about|on|for)\s+(.+)", lower)
    if yt_suggest_match:
        topic = yt_suggest_match.group(1).strip().rstrip("?")
        try:
            from tools.web_search import search_web
            results = await asyncio.to_thread(search_web, f"site:youtube.com {topic}", 3)
            context_parts.append(f"[YOUTUBE SUGGESTIONS]\n{results}")
        except Exception as e:
            context_parts.append(f"[YOUTUBE SUGGEST ERROR] {e}")

    # ── YouTube transcript ────────────────────────────────────────────────
    from tools.youtube_transcript import extract_youtube_url
    yt_url = extract_youtube_url(prompt)
    if yt_url:
        try:
            from tools.youtube_transcript import get_youtube_transcript
            transcript = await asyncio.to_thread(get_youtube_transcript, yt_url)
            if transcript:
                context_parts.append(f"[YOUTUBE TRANSCRIPT]\n{transcript[:4000]}")
        except Exception as e:
            context_parts.append(f"[TRANSCRIPT ERROR] {e}")

    # ── Web search ────────────────────────────────────────────────────────
    search_patterns = [
        r"search\s+(?:for\s+)?(.+)",
        r"find\s+(?:me\s+)?(?:some\s+)?(.+)",
        r"look\s+up\s+(.+)",
        r"google\s+(.+)",
        r"get\s+(?:me\s+)?(?:some\s+)?(.+)",
    ]
    for pat in search_patterns:
        m = _re.search(pat, lower)
        if m:
            query = m.group(1).strip().rstrip(".")
            # Skip if it's a download request (handled below)
            if _re.search(r"download|save", lower):
                break
            try:
                from tools.web_search import search_web
                results = await asyncio.to_thread(search_web, query, 5)
                context_parts.append(f"[WEB SEARCH]\n{results}")
            except Exception as e:
                context_parts.append(f"[SEARCH ERROR] {e}")
            break

    # ── PDF download ──────────────────────────────────────────────────────
    dl_patterns = [
        r"download\s+(?:the\s+)?(?:this\s+)?(?:pdf\s+)?(?:from\s+)?(\S+\.(?:pdf|PDF))",
        r"download\s+(?:the\s+)?(?:book|pdf|paper|document)\s+(?:from\s+)?(\S+)",
        r"save\s+(?:the\s+)?(?:pdf|book)\s+(?:from\s+)?(\S+)",
    ]
    for pat in dl_patterns:
        m = _re.search(pat, lower)
        if m:
            url = m.group(1).strip()
            if not url.startswith("http"):
                url = "https://" + url
            try:
                from tools.pdf_downloader import download_pdf
                result = await asyncio.to_thread(download_pdf, url)
                context_parts.append(f"[PDF DOWNLOAD]\n{result}")
            except Exception as e:
                context_parts.append(f"[DOWNLOAD ERROR] {e}")
            break

    # ── Search + download combo ───────────────────────────────────────────
    combo_match = _re.search(r"(?:search|find|look\s+up).+?(?:and|&).+?(?:download|save).+?(?:about|on|for|of)\s+(.+)", lower)
    if combo_match:
        topic = combo_match.group(1).strip().rstrip(".")
        try:
            from tools.web_search import search_web
            results = await asyncio.to_thread(search_web, f"{topic} filetype:pdf", 5)
            context_parts.append(f"[PDF SEARCH — {topic}]\n{results}")
        except Exception as e:
            context_parts.append(f"[SEARCH ERROR] {e}")

    return "\n\n".join(context_parts) if context_parts else ""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main(prompt: str, image_path: str = None, theme: str = "evil"):
    sentence_buffer = ""
    print("\n[Marin] thinking...")

    import llm_manager
    llm_info = llm_manager.get_best_llm()
    api_key = llm_info[1] if llm_info else ""

    # Early classification to check vibes/intents before full preprocessing
    early_class = await classify(prompt, api_key)
    
    # Check if user is requesting a tool (search, download, etc.)
    _tool_request = bool(re.search(
        r"\b(search|find|look\s+up|google|download|save|get)\b.*?(pdf|book|paper|document|result|info|about|on|for|tutorial|guide|resource|notes|material|lecture)",
        prompt.lower()
    ))

    # ── Tool Detection — execute tools before LLM call ──────────────────────
    tool_context = await _detect_and_run_tools(prompt)
    if tool_context:
        prompt = f"{prompt}\n\n[TOOL RESULTS — use this to answer the user]\n{tool_context}"
        import database
        database.save_message("marin", "system", tool_context)

    enriched_prompt, classification = await preprocess_user_input(prompt, api_key=api_key, image_path=image_path)

    try:
        sentence_buffer = ""

        async for chunk in response(
            enriched_prompt,
            user_vibe=classification["user_vibe"],
            intent=classification.get("intent", "normal"),
            rag_context=classification.get("_rag_context", ""),
            theme=theme
        ):
            if chunk is None: break

            if "__VIBE__" in chunk:
                print(f"\n[SYSTEM: Vibe -> {chunk.replace('__VIBE__','').upper()}]\n")
                yield chunk
                continue

            # Structured output signal — pass through to main.py for card rendering
            if "__STRUCTURED__" in chunk:
                mode_map = {"learn": "📘 TEACHER", "code": "💻 CODER", "lab": "🔬 LAB REPORT"}
                intent = classification.get("intent", "")
                print(f"\n[Mode] {mode_map.get(intent, 'STRUCTURED')} output ready")
                yield chunk
                continue

            print(chunk, end="", flush=True)
            yield chunk
            sentence_buffer += chunk

            img_match = re.search(r"__GENERATE_IMAGE__:\s*(.*?)(?:\n|$)", sentence_buffer)
            if img_match and img_match.group(1).strip():
                prompt_to_gen = img_match.group(1).strip()
                from tools.image_tool import generate_image
                image_url = generate_image(prompt_to_gen)
                yield f"\n__IMAGE__{image_url}\n"
                sentence_buffer = sentence_buffer[:img_match.start()] + sentence_buffer[img_match.end():]

            pomo_match = re.search(r"__POMODORO__:\s*(.*?)\s*:\s*(\d+)", sentence_buffer)
            if pomo_match:
                pomo_topic = pomo_match.group(1).strip()
                pomo_mins = int(pomo_match.group(2))
                
                async def _run_pomodoro_task(topic: str, minutes: int):
                    print(f"\n[Pomodoro] Background task started for {topic}")
                    from tools.web_search import search_web
                    import os, httpx
                    
                    try:
                        search_results = await asyncio.to_thread(search_web, f"{topic} study notes overview concept")
                        base_dir = os.path.dirname(os.path.abspath(__file__))
                        books_dir = os.path.join(base_dir, "books")
                        os.makedirs(books_dir, exist_ok=True)
                        safe_topic = "".join(c if c.isalnum() else "_" for c in topic)
                        filepath = os.path.join(books_dir, f"pomodoro_{safe_topic}.md")
                        
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(f"# Pomodoro Material: {topic}\n\n{search_results}\n")
                            
                        with open(filepath, "rb") as f:
                            await httpx.AsyncClient().post(
                                "http://127.0.0.1:5091/upload/book",
                                files={"file": (f"pomodoro_{safe_topic}.md", f, "text/markdown")}
                            )
                        print(f"[Pomodoro] RAG indexed for {topic}")
                    except Exception as e:
                        print(f"[Pomodoro] Setup error: {e}")
                        return
                        
                    await asyncio.sleep(minutes * 60)
                    
                    try:
                        os.remove(filepath)
                        print(f"[Pomodoro] Cleaned up temporary files for {topic}")
                    except Exception:
                        pass

                asyncio.create_task(_run_pomodoro_task(pomo_topic, pomo_mins))
                # Clear match
                sentence_buffer = sentence_buffer[:pomo_match.start()] + sentence_buffer[pomo_match.end():]



    except Exception as stream_err:
        print(f"[Streaming Error] {stream_err}")


if __name__ == "__main__":
    a = input("What's so urgent?\n>> ")
    asyncio.run(main(a))

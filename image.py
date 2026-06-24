import os
import glob
import asyncio
import time
import base64
import database
from config import OPENROUTER_BASE_URL
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# ── Config ─────────────────────────────────────────────────────────────────────
CHARACTER_NAME = "leo"
CHARACTER      = """You are Leonardo Da Vinci — the Renaissance genius.
You see hidden geometry, divine proportion, and deeper meaning in everything.
Speak dramatically, find patterns and beauty. Be poetic but brief."""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def response(prompt: str, image_path=None):
    import llm_manager
    llm_info = llm_manager.get_best_llm()
    if not llm_info:
        yield "[Leo] I cannot see without my API key (OpenRouter API Key not set)."
        return
    _, key, _ = llm_info

    # Use VISION_MODEL from settings, or fallback to first selected model
    vision_model = database.get_state("VISION_MODEL", "") or llm_info[2]

    # ── Load history ──────────────────────────────────────────────────────────
    raw_history = database.get_history("leo", limit=20)
    messages = [SystemMessage(content=CHARACTER)]
    
    for msg in raw_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

    # ── Build user message ────────────────────────────────────────────────────
    content_list = []
    
    if image_path and os.path.exists(image_path):
        print(f"[Leo] Analyzing: {os.path.basename(image_path)}")
        base64_img = _encode_image(image_path)
        ext = os.path.splitext(image_path)[1].lower().replace('.', '')
        if ext == 'jpg': ext = 'jpeg'
        
        content_list.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/{ext};base64,{base64_img}"}
        })
    else:
        if image_path:
            print(f"[Leo] Image not found at: {image_path}")
        else:
            print(f"[Leo] No image provided — text only")
            
    content_list.append({"type": "text", "text": prompt})
    messages.append(HumanMessage(content=content_list))

    # ── Stream reply with fallback ─────────────────────────────────────────────
    reply = ""
    print("\n[Leo] Contemplating...\n")
    max_retries = len(llm_manager.FALLBACK_MODELS)
    current_model = vision_model
    for attempt in range(max_retries):
        try:
            base_url = llm_info[0].openai_api_base
            llm = ChatOpenAI(
                model=current_model,
                openai_api_key=key,
                openai_api_base=base_url,
                temperature=0.7,
                streaming=True,
                max_retries=0
            )
            for chunk in llm.stream(messages):
                piece = chunk.content
                if piece:
                    reply += piece
                    yield piece
            break
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                llm_manager.report_rate_limit(key, current_model)
                print(f"\n[Leo] Rate limit on {current_model}. Retrying with new key/model...")
                llm_info = llm_manager.get_best_llm()
                if not llm_info:
                    yield "\n[System: All API keys exhausted due to rate limits]"
                    return
                _, key, current_model = llm_info
                reply = ""
            else:
                print(f"\n[Leo] Error: {e}")
                yield f"[Error: {e}]"
                return
    else:
        yield "\n[System: All vision models exhausted]"

    # ── Save history ──────────────────────────────────────────────────────────
    database.save_message("leo", "user", prompt)
    database.save_message("leo", "assistant", reply)


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    search_dir = os.path.join(BASE_DIR, "static", "uploads")
    os.makedirs(search_dir, exist_ok=True)
    
    image_files = (glob.glob(os.path.join(search_dir, "*.jpg"))  +
                   glob.glob(os.path.join(search_dir, "*.jpeg")) +
                   glob.glob(os.path.join(search_dir, "*.png"))  +
                   glob.glob(os.path.join(search_dir, "*.webp")) +
                   glob.glob(os.path.join(search_dir, "*.ico")))

    if not image_files:
        print(f"[Leo] No image found in {search_dir} — put an image there.")
        exit(1)

    latest_image = max(image_files, key=os.path.getctime)
    print(f"[Leo] Found image: {latest_image}")

    prompt = "This is a safe general image. Describe only what you literally see. Be brief."
    for piece in response(prompt, image_path=latest_image):
        print(piece, end="", flush=True)
    print("\n")
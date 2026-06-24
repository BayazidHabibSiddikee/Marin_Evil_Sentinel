import httpx
import json
import os

PROXY_URL = os.getenv("LLM_PROXY_URL", "http://host.docker.internal:8005/v1")

async def classify(text: str, api_key: str) -> dict:
    """LLM-based classification using a fast OpenRouter model."""
    if not api_key:
        # Fallback to a basic rule if no key is provided yet
        return {"intent": "chat", "user_vibe": "neutral"}
        
    prompt = f"""Classify the user's message into an intent and a user_vibe.
Available intents: [chat, image_gen, learn, code, lab, study, distraction]
Available vibes: [neutral, lovely, flirty, angry, sad, excited]

CRITICAL RULES:
- "learn" is ONLY for direct teaching requests like "teach me X", "explain X in depth", "give me a lesson on X"
- "code" is ONLY for "write me code", "code this", "implement X in Python"
- "lab" is ONLY for "lab report", "write a lab experiment"
- "build me", "create", "make me", "simulate", "visualize", "demo" → these are "chat", NOT "learn" or "code"
- "interactive", "playground", "widget", "simulator" → these are "chat"
- Casual statements like "I'm reading X", "I'm studying X", "I'm doing X" are "chat", NOT "learn"
- Questions like "what is X?" or "how does X work?" are "chat", NOT "learn"
- "game development" or "game design" is 'code' or 'learn', NOT 'distraction'. 'distraction' is only for playing games, joking around, or avoiding work.

User Message: "{text}"

Respond ONLY with valid JSON in this exact format:
{{"intent": "...", "user_vibe": "..."}}"""

    headers = {
        "Authorization": "Bearer proxy-rotate",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "google/gemma-2-9b-it:free",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{PROXY_URL}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            content = content.replace("```json", "").replace("```", "").strip()
            result = json.loads(content)
            
            intent = result.get("intent", "chat")
            vibe = result.get("user_vibe", "neutral")
            
            return {"intent": intent, "user_vibe": vibe}
            
    except Exception as e:
        print(f"[Classifier] LLM Error: {e}")
        return {"intent": "chat", "user_vibe": "neutral"}

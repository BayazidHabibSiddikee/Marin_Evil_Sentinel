import httpx
import json
import os

PROXY_URL = os.getenv("LLM_PROXY_URL", "http://host.docker.internal:8005/v1")

async def classify(text: str, api_key: str = None) -> dict:
    """LLM-based classification using the active provider."""
    import llm_manager
    from langchain_core.messages import SystemMessage, HumanMessage
    
    # Fast fallback if no providers
    llm_info = llm_manager.get_best_llm()
    if not llm_info:
        return {"intent": "chat", "user_vibe": "neutral"}
        
    llm_instance, key, model = llm_info
    
    # We use ChatOpenAI bound to JSON object mode if possible
    try:
        llm = llm_instance.bind(response_format={"type": "json_object"})
    except Exception:
        llm = llm_instance

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

    try:
        import asyncio
        resp = await asyncio.to_thread(llm.invoke, [HumanMessage(content=prompt)])
        content = resp.content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        
        intent = result.get("intent", "chat")
        vibe = result.get("user_vibe", "neutral")
        
        return {"intent": intent, "user_vibe": vibe}
    except Exception as e:
        if llm_manager.is_auth_error(e):
            llm_manager.report_auth_error(key)
            llm_info = llm_manager.get_best_llm(deep=False)
            if llm_info:
                try:
                    llm, key, model = llm_info
                    resp = await asyncio.to_thread(llm.invoke, [HumanMessage(content=prompt)])
                    content = resp.content.replace("```json", "").replace("```", "").strip()
                    result = json.loads(content)
                    return {"intent": result.get("intent", "chat"), "user_vibe": result.get("user_vibe", "neutral")}
                except Exception as e2:
                    print(f"[Classifier] Retry Error: {e2}")
            print(f"[Classifier] Invalid API key - defaulting to chat")
        else:
            print(f"[Classifier] LLM Error: {e}")
        return {"intent": "chat", "user_vibe": "neutral"}

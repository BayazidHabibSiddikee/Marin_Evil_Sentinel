import os
import sys
import uuid
import requests
from pathlib import Path

# Add project root to path so database can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database
import config

GEN_DIR = os.path.join(os.getcwd(), "static", "generated")

def generate_image(prompt: str) -> str:
    """Generates an image using OpenRouter and returns the local file path."""
    import llm_manager
    llm_info = llm_manager.get_best_llm()
    if not llm_info:
        return "Failed: OpenRouter API key not configured."
        
    image_model = database.get_state("IMAGE_MODEL") or config.IMAGE_MODEL
    
    headers = {
        "Authorization": f"Bearer {llm_info[1]}",
        "HTTP-Referer": "https://github.com/marin-hs02",
        "X-Title": "Marin HS-02",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": image_model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024"
    }
    
    # Retry with fallback on 429
    custom_models = database.get_state("FALLBACK_MODELS")
    max_retries = len(custom_models) if custom_models else len(llm_manager.FALLBACK_MODELS)
    for _ in range(max_retries):
        _, api_key, _ = llm_info
        headers["Authorization"] = f"Bearer {api_key}"
        try:
            base_url = config.OPENROUTER_BASE_URL.replace("/chat/completions", "")
            response = requests.post(f"{base_url}/images/generations", headers=headers, json=payload)
            
            if response.status_code == 429:
                llm_manager.report_rate_limit(llm_info[1], llm_info[2])
                llm_info = llm_manager.get_best_llm()
                if not llm_info:
                    return "Failed: All models exhausted. Try again later."
                continue
                
            response.raise_for_status()
            data = response.json()
            
            if "data" in data and len(data["data"]) > 0:
                image_url = data["data"][0].get("url")
                if not image_url:
                    import base64
                    b64 = data["data"][0].get("b64_json")
                    if b64:
                        filename = f"gen_{uuid.uuid4().hex[:8]}.png"
                        filepath = os.path.join(GEN_DIR, filename)
                        with open(filepath, "wb") as f:
                            f.write(base64.b64decode(b64))
                        return f"/static/generated/{filename}"
                    return "Failed: No URL or base64 data returned."
                    
                img_resp = requests.get(image_url)
                img_resp.raise_for_status()
                
                filename = f"gen_{uuid.uuid4().hex[:8]}.png"
                filepath = os.path.join(GEN_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(img_resp.content)
                    
                return f"/static/generated/{filename}"
            else:
                return f"Failed: API response didn't contain image data. {data}"
                
        except requests.exceptions.HTTPError as e:
            if "429" in str(e):
                llm_manager.report_rate_limit(llm_info[1], llm_info[2])
                llm_info = llm_manager.get_best_llm()
                if not llm_info:
                    return "Failed: All models exhausted. Try again later."
                continue
            return f"Failed to generate image: {e}"
        except Exception as e:
            return f"Failed to generate image: {e}"
    
    return "Failed: All models exhausted. Try again later."

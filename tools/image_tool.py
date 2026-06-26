import os
import sys
import uuid
import requests
from pathlib import Path

# Add project root to path so database can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database
import config

GEN_DIR = os.path.join(config.BASE_DIR, "static", "generated")

IMAGE_CAPABLE_MODELS = [
    "black-forest-labs/flux-schnell",
    "black-forest-labs/flux-dev",
    "stabilityai/stable-diffusion-3.5-large",
    "openai/dall-e-3",
]

def generate_image(prompt: str) -> str:
    """Generates an image and returns the local file path."""
    import llm_manager

    image_model = database.get_state("IMAGE_MODEL") or config.IMAGE_MODEL
    model_chain = [image_model] + [m for m in IMAGE_CAPABLE_MODELS if m != image_model]
    os.makedirs(GEN_DIR, exist_ok=True)

    providers = llm_manager.get_providers()
    for provider in providers:
        if not provider.get("enabled", True):
            continue
        base_url = provider.get("base_url", "")
        api_keys = provider.get("api_keys", [])
        if not api_keys or not base_url:
            continue
        img_base = base_url.replace("/chat/completions", "")

        for model in model_chain:
            for key in api_keys:
                headers = {
                    "Authorization": f"Bearer {key}",
                    "HTTP-Referer": "https://github.com/marin-hs02",
                    "X-Title": "Marin HS-02",
                    "Content-Type": "application/json",
                }
                payload = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"}
                try:
                    resp = requests.post(f"{img_base}/images/generations", headers=headers, json=payload, timeout=60)
                    if resp.status_code == 429:
                        llm_manager.report_rate_limit(key, model)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if "data" in data and len(data["data"]) > 0:
                        image_url = data["data"][0].get("url")
                        if image_url:
                            img_resp = requests.get(image_url, timeout=30)
                            img_resp.raise_for_status()
                            filename = f"gen_{uuid.uuid4().hex[:8]}.png"
                            filepath = os.path.join(GEN_DIR, filename)
                            with open(filepath, "wb") as f:
                                f.write(img_resp.content)
                            return f"/static/generated/{filename}"
                        import base64
                        b64 = data["data"][0].get("b64_json")
                        if b64:
                            filename = f"gen_{uuid.uuid4().hex[:8]}.png"
                            filepath = os.path.join(GEN_DIR, filename)
                            with open(filepath, "wb") as f:
                                f.write(base64.b64decode(b64))
                            return f"/static/generated/{filename}"
                except requests.exceptions.HTTPError as e:
                    if "429" in str(e):
                        llm_manager.report_rate_limit(key, model)
                        continue
                except Exception:
                    continue
    return "Failed: All image models exhausted. Try again later."

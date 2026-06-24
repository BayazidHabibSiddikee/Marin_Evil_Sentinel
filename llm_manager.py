import json, time, os
import database
from langchain_openai import ChatOpenAI

FALLBACK_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-2-9b-it:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "nvidia/llama-3.2-nv-embedqa-1b-v2:free",
    "liquid/lfm-40b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "qwen/qwen3-coder:free",
    "venice/uncensored:free",
    "nousresearch/hermes-3-llama-3.1-405b:free"
]

COOLDOWN_SECONDS = 5 * 3600  # 5 hours
PROXY_URL = os.getenv("LLM_PROXY_URL", "http://host.docker.internal:8005/v1")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")

def _get_rate_limits():
    raw = database.get_state("RATE_LIMITS", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except:
        return {}

def _save_rate_limits(limits):
    database.set_state("RATE_LIMITS", json.dumps(limits))

def report_rate_limit(key: str, model: str):
    limits = _get_rate_limits()
    limits[f"{key}|{model}"] = time.time()
    _save_rate_limits(limits)

def _is_rate_limited(key: str, model: str, limits: dict, now: float) -> bool:
    return f"{key}|{model}" in limits and (now - limits[f"{key}|{model}"]) < COOLDOWN_SECONDS

def get_best_llm():
    """Returns a ChatOpenAI instance. Proxy is PRIMARY. Direct keys are fallback. Ollama is last resort."""
    keys_str = database.get_state("OPENROUTER_API_KEY", "")
    all_keys = [k.strip() for k in keys_str.split(",") if k.strip()]

    # Priority: ACTIVE_MODEL > SELECTED_MODELS > FALLBACK_MODELS > hardcoded
    active_model = database.get_state("ACTIVE_MODEL", "")
    custom_models = database.get_state("SELECTED_MODELS") or database.get_state("FALLBACK_MODELS")
    models = custom_models if custom_models else FALLBACK_MODELS

    ordered = []
    if active_model:
        ordered.append(active_model)
    for m in models:
        if m != active_model:
            ordered.append(m)
    if not ordered:
        ordered = FALLBACK_MODELS

    limits = _get_rate_limits()
    now = time.time()

    # Clean up old limits
    cleaned_limits = {k: v for k, v in limits.items() if now - v < COOLDOWN_SECONDS}
    if len(cleaned_limits) != len(limits):
        _save_rate_limits(cleaned_limits)
        limits = cleaned_limits

    # 1. Proxy first — if not rate limited for ALL models
    proxy_all_limited = all(_is_rate_limited("proxy", m, limits, now) for m in ordered[:3])
    if not proxy_all_limited:
        for model in ordered:
            if not _is_rate_limited("proxy", model, limits, now):
                try:
                    llm = ChatOpenAI(
                        model=model,
                        openai_api_key="proxy-rotate",
                        openai_api_base=PROXY_URL,
                        max_retries=0
                    )
                    return llm, "proxy", model
                except:
                    pass

    # 2. Direct keys — bypass proxy
    for model in ordered:
        for key in all_keys:
            if not _is_rate_limited(key, model, limits, now):
                base_url = "https://openrouter.ai/api/v1"
                actual_model = model

                if key.startswith("sk-proj-"):
                    base_url = "https://api.openai.com/v1"
                    actual_model = "gpt-4o-mini"
                elif key.startswith("AIza"):
                    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
                    actual_model = "gemini-1.5-flash"

                return ChatOpenAI(
                    model=actual_model,
                    openai_api_key=key,
                    openai_api_base=base_url,
                    max_retries=0
                ), key, model

    # 3. Absolute fallback — Ollama local (always available, no rate limits)
    try:
        llm = ChatOpenAI(
            model="marin:latest",
            openai_api_key="ollama",
            openai_api_base=OLLAMA_URL,
            max_retries=0
        )
        return llm, "ollama", "marin:latest"
    except:
        pass

    # 4. Last resort — first key, first model
    if all_keys:
        return ChatOpenAI(
            model=ordered[0],
            openai_api_key=all_keys[0],
            openai_api_base="https://openrouter.ai/api/v1"
        ), all_keys[0], ordered[0]

    return None

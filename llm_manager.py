import json, time, os
import database
from langchain_openai import ChatOpenAI

# ── Legacy fallback model list ──────────────────────────────────────────────────
FALLBACK_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "liquid/lfm-40b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "google/gemma-2-9b-it:free",
]

COOLDOWN_SECONDS = 5 * 3600  # 5 hours
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")

# ── Rate limit helpers ──────────────────────────────────────────────────────────
def _get_rate_limits() -> dict:
    raw = database.get_state("RATE_LIMITS", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}

def _save_rate_limits(limits: dict):
    database.set_state("RATE_LIMITS", json.dumps(limits))

def report_rate_limit(key: str, model: str):
    limits = _get_rate_limits()
    limits[f"{key}|{model}"] = time.time()
    _save_rate_limits(limits)

def _is_rate_limited(key: str, model: str, limits: dict, now: float) -> bool:
    return f"{key}|{model}" in limits and (now - limits[f"{key}|{model}"]) < COOLDOWN_SECONDS

# ── Provider helpers ────────────────────────────────────────────────────────────
def get_providers() -> list:
    """
    Returns the ordered provider list. Each provider is a dict:
    {
      "name": str,
      "base_url": str,
      "api_keys": [str, ...],   # multiple keys, round-robined
      "models": [str, ...],     # selected model IDs
      "enabled": bool,
      "priority": int
    }
    If no PROVIDERS key, falls back to legacy OPENROUTER_API_KEY.
    """
    raw = database.get_state("PROVIDERS")
    if raw is not None:
        try:
            providers = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(providers, list) and providers:
                return sorted(providers, key=lambda p: p.get("priority", 99))
        except Exception:
            pass

    # ── Migrate legacy keys to provider slot ──────────────────────────────────
    legacy_key = database.get_state("OPENROUTER_API_KEY", "")
    legacy_keys = [k.strip() for k in legacy_key.split(",") if k.strip()] if legacy_key else []

    active_model = database.get_state("ACTIVE_MODEL", "")
    custom_models_raw = database.get_state("SELECTED_MODELS")
    if custom_models_raw is None:
        custom_models_raw = database.get_state("FALLBACK_MODELS")
    legacy_models = custom_models_raw if isinstance(custom_models_raw, list) else FALLBACK_MODELS

    providers = []
    if legacy_keys:
        providers.append({
            "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_keys": legacy_keys,
            "models": legacy_models,
            "enabled": True,
            "priority": 1,
        })

    # Legacy proxy support
    proxy_url = os.getenv("LLM_PROXY_URL", "")
    if proxy_url:
        providers.append({
            "name": "Proxy",
            "base_url": proxy_url,
            "api_keys": ["proxy-rotate"],
            "models": legacy_models,
            "enabled": True,
            "priority": 0,
        })
        providers.sort(key=lambda p: p.get("priority", 99))

    return providers

def save_providers(providers: list):
    database.set_state("PROVIDERS", providers)

# ── Deep model list ─────────────────────────────────────────────────────────────
def get_deep_models() -> list:
    raw = database.get_state("DEEP_MODELS")
    if raw and raw != "[]":
        try:
            models = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(models, list):
                return models
        except Exception:
            pass
    # Default deep models — moderate speed, good quality
    return [
        "google/gemma-4-26b-a4b-it:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "qwen/qwen3-coder-480b-a35b:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "liquid/lfm-40b:free",
    ]

def save_deep_models(models: list):
    database.set_state("DEEP_MODELS", models)

# ── Core LLM selector ──────────────────────────────────────────────────────────
def get_best_llm(deep: bool = False):
    """
    Returns (ChatOpenAI instance, api_key, model) or None.

    Resolution order:
    1. Iterate providers by priority (enabled=True only)
       - For each provider: iterate selected models
         - For each model: try all api_keys (round-robin style, skip rate-limited)
    2. If deep=True: use DEEP_MODELS list across all providers first
    3. Ollama local (last resort)
    """
    limits = _get_rate_limits()
    now = time.time()

    # Prune stale rate limits
    cleaned = {k: v for k, v in limits.items() if now - v < COOLDOWN_SECONDS}
    if len(cleaned) != len(limits):
        _save_rate_limits(cleaned)
        limits = cleaned

    providers = get_providers()

    # In deep mode, first try deep_models across all providers
    if deep:
        deep_model_ids = get_deep_models()
        for provider in providers:
            if not provider.get("enabled", True):
                continue
            base_url = provider.get("base_url", "")
            api_keys = provider.get("api_keys", [])
            if not api_keys or not base_url:
                continue
            for model in deep_model_ids:
                for key in api_keys:
                    if not _is_rate_limited(key, model, limits, now):
                        try:
                            llm = ChatOpenAI(
                                model=model,
                                openai_api_key=key,
                                openai_api_base=base_url,
                                max_retries=0
                            )
                            return llm, key, model
                        except Exception:
                            pass
        # Fall through to normal model selection if deep models all exhausted

    # Normal model selection across providers
    for provider in providers:
        if not provider.get("enabled", True):
            continue
        base_url = provider.get("base_url", "")
        api_keys = provider.get("api_keys", [])
        models = provider.get("models", [])
        if not api_keys or not base_url or not models:
            continue
        for model in models:
            for key in api_keys:
                if not _is_rate_limited(key, model, limits, now):
                    try:
                        llm = ChatOpenAI(
                            model=model,
                            openai_api_key=key,
                            openai_api_base=base_url,
                            max_retries=0
                        )
                        return llm, key, model
                    except Exception:
                        pass

    # Last resort — Ollama local
    try:
        llm = ChatOpenAI(
            model="marin:latest",
            openai_api_key="ollama",
            openai_api_base=OLLAMA_URL,
            max_retries=0
        )
        return llm, "ollama", "marin:latest"
    except Exception:
        pass

    return None

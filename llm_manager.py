import json
import time
import os
import database
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
# ── Legacy fallback model list ──────────────────────────────────────────────────
FALLBACK_MODELS = [
    "google/gemini-2.5-flash",
    "google/gemini-2.5-pro",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
]

COOLDOWN_SECONDS = 5 * 3600  # 5 hours
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")

# ── Auth & Rate limit helpers ───────────────────────────────────────────────────

def is_auth_error(e: Exception) -> bool:
    err_str = str(e).lower()
    return any(x in err_str for x in [
        "401", "unauthorized", "invalid api key",
        "authentication", "user not found",
    ])


# ── Invalid keys — persisted in DB so they survive restarts ────────────────────

def _get_invalid_keys() -> set:
    raw = database.get_state("INVALID_KEYS", "[]")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_invalid_keys(keys: set):
    database.set_state("INVALID_KEYS", json.dumps(list(keys)))


def report_auth_error(key: str):
    if not key:
        return
    invalid = _get_invalid_keys()
    invalid.add(key)
    _save_invalid_keys(invalid)


# ── Rate limits ─────────────────────────────────────────────────────────────────

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
    entry = limits.get(f"{key}|{model}")
    return entry is not None and (now - entry) < COOLDOWN_SECONDS


# ── Key rotation index — persisted per provider so load spreads across keys ────

def _get_key_index(provider_name: str, num_keys: int) -> int:
    """Returns the next key index for a provider, advancing the counter in DB."""
    if num_keys <= 1:
        return 0
    raw = database.get_state(f"KEY_INDEX_{provider_name}", "0")
    try:
        current = int(raw) if isinstance(raw, (str, int)) else 0
    except (ValueError, TypeError):
        current = 0
    next_index = (current + 1) % num_keys
    database.set_state(f"KEY_INDEX_{provider_name}", str(next_index))
    return current


# ── Provider helpers ────────────────────────────────────────────────────────────

def get_providers() -> list:
    """
    Returns the ordered provider list. Each provider is a dict:
    {
      "name":     str,
      "base_url": str,
      "api_keys": [str, ...],   # multiple keys, round-robined
      "models":   [str, ...],   # selected model IDs
      "enabled":  bool,
      "priority": int
    }
    Falls back to legacy OPENROUTER_API_KEY if no PROVIDERS key is found.
    """
    raw = database.get_state("PROVIDERS")
    if raw is not None:
        try:
            # Always parse from JSON string; never trust a raw Python object from the DB
            providers = json.loads(raw) if isinstance(raw, str) else json.loads(json.dumps(raw))
            if isinstance(providers, list) and providers:
                return sorted(providers, key=lambda p: p.get("priority", 99))
        except Exception:
            pass

    # ── Migrate legacy keys to a single provider slot ─────────────────────────
    legacy_key = database.get_state("OPENROUTER_API_KEY", "")
    legacy_keys = [k.strip() for k in legacy_key.split(",") if k.strip()] if legacy_key else []

    custom_models_raw = database.get_state("SELECTED_MODELS") or database.get_state("FALLBACK_MODELS")
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

    return sorted(providers, key=lambda p: p.get("priority", 99))


def save_providers(providers: list):
    # Always serialize to JSON string so get_providers() can reliably parse it back
    database.set_state("PROVIDERS", json.dumps(providers))


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
    return [
        "google/gemini-2.5-flash",
        "qwen/qwen-2.5-72b-instruct:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
    ]


def save_deep_models(models: list):
    database.set_state("DEEP_MODELS", json.dumps(models))


# ── Internal: build + validate a ChatOpenAI instance ───────────────────────────

def _try_build_llm(model: str, key: str, base_url: str):
    """
    Instantiates ChatOpenAI and does a minimal probe call.
    Returns the llm on success, raises on failure.
    ChatOpenAI.__init__ never raises on bad credentials — only .invoke() does.
    """
    llm = ChatOpenAI(
        model=model,
        openai_api_key=key,
        openai_api_base=base_url,
        max_retries=1,
    )
    return llm


# ── Core LLM selector ──────────────────────────────────────────────────────────

def get_best_llm(deep: bool = False):
    """
    Returns (ChatOpenAI instance, api_key, model_id) or None.

    Resolution order:
    1. If deep=True, try DEEP_MODELS across all enabled providers first.
    2. Try each provider's own model list (round-robin key rotation).
    3. Last resort: Ollama local.

    Keys are rotated round-robin using a persisted index, so load is spread
    evenly rather than always hammering key[0] until it's rate-limited.
    Invalid keys (auth failures) are persisted in the DB across restarts.
    """
    limits     = _get_rate_limits()
    now        = time.time()
    invalid    = _get_invalid_keys()

    # Prune stale rate-limit entries
    cleaned = {k: v for k, v in limits.items() if now - v < COOLDOWN_SECONDS}
    if len(cleaned) != len(limits):
        _save_rate_limits(cleaned)
        limits = cleaned

    providers = get_providers()

    def _try_provider_with_models(provider: dict, model_list: list):
        """Try every model × every key in a provider, starting at the rotated index."""
        if not provider.get("enabled", True):
            return None
        base_url = provider.get("base_url", "")
        api_keys = provider.get("api_keys", [])
        name     = provider.get("name", "unknown")
        if not api_keys or not base_url or not model_list:
            return None

        num_keys   = len(api_keys)
        start_idx  = _get_key_index(name, num_keys)

        for model in model_list:
            # Rotate through keys starting at the saved index
            for offset in range(num_keys):
                key = api_keys[(start_idx + offset) % num_keys]
                if key in invalid:
                    continue
                if _is_rate_limited(key, model, limits, now):
                    continue
                try:
                    llm = _try_build_llm(model, key, base_url)
                    return llm, key, model
                except Exception as e:
                    if is_auth_error(e):
                        print(f"[LLM] Auth error for key ...{key[-6:]} on {name} — blacklisting")
                        invalid.add(key)
                        _save_invalid_keys(invalid)
                    else:
                        # Treat connection/timeout errors as a short rate-limit
                        print(f"[LLM] Error on {name}/{model}: {e}")
                        report_rate_limit(key, model)
                        limits[f"{key}|{model}"] = now  # keep local copy in sync
        return None

    # ── Deep mode: try deep_models list across all providers first ─────────────
    if deep:
        deep_model_ids = get_deep_models()
        for provider in providers:
            result = _try_provider_with_models(provider, deep_model_ids)
            if result:
                return result
        # Fall through to normal selection if all deep models exhausted

    # ── Normal mode: each provider's own model list ────────────────────────────
    for provider in providers:
        models = provider.get("models", [])
        result = _try_provider_with_models(provider, models)
        if result:
            return result

    # ── Last resort: Ollama local (only if not rate-limited) ──────────────────
    ollama_model = "marin:latest"
    if not _is_rate_limited("ollama", ollama_model, limits, now):
        print("[LLM] All providers exhausted — falling back to local Ollama")
        try:
            llm = ChatOpenAI(
                model=ollama_model,
                openai_api_key="ollama",
                openai_api_base=OLLAMA_URL,
                max_retries=2,
            )
            # Ollama doesn't need the probe (local, no auth)
            return llm, "ollama", ollama_model
        except Exception as e:
            print(f"[LLM] Ollama also failed: {e}")
    else:
        print("[LLM] All providers including Ollama exhausted")

    return None


# ── Key validation (used by settings UI) ───────────────────────────────────────

def validate_api_key(key: str, base_url: str = "https://openrouter.ai/api/v1") -> tuple[bool, str]:
    """Lightweight test request to validate an API key."""
    if not key:
        return False, "No key provided"

    # Remove from invalid set to allow re-testing a key that was blacklisted
    invalid = _get_invalid_keys()
    if key in invalid:
        invalid.discard(key)
        _save_invalid_keys(invalid)

    test_model = "google/gemini-2.5-flash"
    if "generativelanguage.googleapis.com" in base_url:
        test_model = "gemini-2.5-flash"
    elif "api.openai.com" in base_url:
        test_model = "gpt-4o-mini"
    elif "api-inference.huggingface.co" in base_url:
        test_model = "meta-llama/Llama-3.2-3B-Instruct"
    elif "api.ollama.ai" in base_url or "localhost" in base_url or "127.0.0.1" in base_url:
        test_model = "llama3.2"

    try:
        from langchain_core.tools import tool
        @tool
        def dummy_search_tool(query: str) -> str:
            """Searches the web for the given query."""
            return "Found results"

        llm = ChatOpenAI(
            model=test_model,
            openai_api_key=key,
            openai_api_base=base_url,
            max_retries=0,
            timeout=10.0,
        )
        # Test basic connection
        llm.invoke([HumanMessage(content="hi")])
        
        # Test tool calling
        try:
            llm_with_tools = llm.bind_tools([dummy_search_tool])
            llm_with_tools.invoke([HumanMessage(content="hi")])
            tool_msg = " (Tool calling supported)"
        except Exception:
            tool_msg = " (Valid, but this model might not support tools)"
            
        return True, f"Key is valid{tool_msg}"
    except Exception as e:
        if is_auth_error(e):
            invalid = _get_invalid_keys()
            invalid.add(key)
            _save_invalid_keys(invalid)
            return False, "Invalid API key or authentication failed."
        return False, f"Connection failed: {str(e)}"

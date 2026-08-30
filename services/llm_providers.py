"""Dual-provider fallback layer for Qwen-Agent and LLM capabilities.

Chain: ModelScope primary (Qwen3-235B-A22B-Instruct-2507) -> OpenRouter fallback (qwen/qwen3-235b-a22b-2507).
Never logs, prints, or exposes API key values.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("llm_providers")

MODELSCOPE_DEFAULT_URL = "https://api-inference.modelscope.ai/v1"
MODELSCOPE_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"

OPENROUTER_DEFAULT_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "qwen/qwen3-235b-a22b-2507"

# Process-lifetime health cache for providers
_PROVIDER_HEALTH: Dict[str, bool] = {}
_LAST_OUTCOME: Dict[str, Any] = {
    "primary": "unprobed",
    "fallback": "unprobed",
    "served_by": None,
}


class ProviderError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _is_valid_key(key: Optional[str]) -> bool:
    if not key:
        return False
    k = key.strip()
    return bool(k) and not k.startswith("your_")


def _get_provider_info(name: str) -> Optional[Dict[str, str]]:
    if name == "modelscope":
        key = os.getenv("ALIBABA_MODEL_API_KEY", "").strip()
        if not _is_valid_key(key):
            return None
        base_url = os.getenv("LLM_BASE_URL", "").strip().rstrip("/") or MODELSCOPE_DEFAULT_URL
        return {
            "name": "modelscope",
            "model": MODELSCOPE_MODEL,
            "base_url": base_url,
            "api_key": key,
        }
    elif name == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not _is_valid_key(key):
            return None
        return {
            "name": "openrouter",
            "model": os.getenv("DEMO_MODEL", "").strip() or OPENROUTER_MODEL,
            "base_url": OPENROUTER_DEFAULT_URL,
            "api_key": key,
        }
    return None


def _probe_provider_health(name: str) -> bool:
    """Perform a single cheap health check for a provider or return cached health."""
    global _PROVIDER_HEALTH
    if name in _PROVIDER_HEALTH:
        return _PROVIDER_HEALTH[name]

    info = _get_provider_info(name)
    if not info:
        _PROVIDER_HEALTH[name] = False
        return False

    # Perform a minimal 1-token call via raw request
    try:
        reply = _call_provider_raw(
            name,
            [{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=8.0,
        )
        is_healthy = bool(reply)
    except ProviderError as pe:
        logger.warning(f"Health probe for provider {name} failed: {pe.status_code or pe}")
        is_healthy = False
    except Exception as e:
        logger.warning(f"Health probe for provider {name} encountered error: {type(e).__name__}")
        is_healthy = False

    _PROVIDER_HEALTH[name] = is_healthy
    return is_healthy


def _call_provider_raw(
    name: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.7,
    timeout: float = 60.0,
) -> str:
    """Raw provider call using httpx, raising ProviderError with status_code on HTTP errors."""
    import httpx

    info = _get_provider_info(name)
    if not info:
        raise ProviderError(f"Provider {name} has no valid credentials configured")

    headers = {
        "Authorization": f"Bearer {info['api_key']}",
        "Content-Type": "application/json",
    }
    if name == "openrouter":
        headers["HTTP-Referer"] = "https://travelcare.ai"
        headers["X-Title"] = "TravelCare AI"

    url = f"{info['base_url']}/chat/completions"
    payload = {
        "model": info["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            err_msg = f"HTTP {resp.status_code}"
            logger.warning(f"Provider {name} returned {err_msg}")
            raise ProviderError(err_msg, status_code=resp.status_code)
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("Empty choices returned by provider")
        return choices[0].get("message", {}).get("content", "")
    except httpx.TimeoutException:
        raise ProviderError("Request timed out", status_code=408)
    except httpx.HTTPError as he:
        raise ProviderError(f"HTTP network error: {he}")
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Unexpected provider error: {type(exc).__name__}")


def resolve_llm_cfg() -> Optional[Dict[str, Any]]:
    """Resolve the first healthy provider into a Qwen-Agent llm_cfg dictionary."""
    for provider_name in ("modelscope", "openrouter"):
        info = _get_provider_info(provider_name)
        if not info:
            continue
        if _probe_provider_health(provider_name):
            return {
                "model": info["model"],
                "model_server": info["base_url"],
                "api_key": info["api_key"],
                "generate_cfg": {
                    "fncall_prompt_type": "nous",
                    "extra_body": {"enable_thinking": False},
                },
            }
    return None


def active_provider() -> str:
    """Return the name of the currently active/selected provider for telemetry."""
    cfg = resolve_llm_cfg()
    if not cfg:
        return "none"
    if "modelscope" in cfg.get("model_server", "").lower():
        return "modelscope"
    if "openrouter" in cfg.get("model_server", "").lower():
        return "openrouter"
    return "unknown"


def last_provider_outcome() -> Dict[str, Any]:
    """Return the outcome record from the last chat_with_fallback invocation."""
    return dict(_LAST_OUTCOME)


def chat_with_fallback(
    messages: List[Dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.7,
    timeout: float = 60.0,
) -> Tuple[Optional[str], Optional[str]]:
    """Execute chat completion with primary (ModelScope) -> fallback (OpenRouter).

    Returns (content, provider_name) on success, or (None, None) on total failure.
    Never raises; never logs secret keys.
    """
    global _LAST_OUTCOME
    _LAST_OUTCOME = {
        "primary": "skipped",
        "fallback": "skipped",
        "served_by": None,
    }

    # 1. Try primary (ModelScope)
    ms_info = _get_provider_info("modelscope")
    if ms_info:
        try:
            content = _call_provider_raw(
                "modelscope",
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            _LAST_OUTCOME["primary"] = "ok"
            _LAST_OUTCOME["served_by"] = "modelscope"
            _PROVIDER_HEALTH["modelscope"] = True
            return content, "modelscope"
        except ProviderError as pe:
            code_str = f"http_{pe.status_code}" if pe.status_code else "error"
            _LAST_OUTCOME["primary"] = code_str
            if pe.status_code == 429:
                _PROVIDER_HEALTH["modelscope"] = False
            logger.warning(f"Primary provider (ModelScope) failed with {code_str}; attempting fallback")
        except Exception:
            _LAST_OUTCOME["primary"] = "exception"
            logger.warning("Primary provider (ModelScope) threw unexpected exception; attempting fallback")

    # 2. Try fallback (OpenRouter)
    or_info = _get_provider_info("openrouter")
    if or_info:
        try:
            content = _call_provider_raw(
                "openrouter",
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            _LAST_OUTCOME["fallback"] = "ok"
            _LAST_OUTCOME["served_by"] = "openrouter"
            _PROVIDER_HEALTH["openrouter"] = True
            return content, "openrouter"
        except ProviderError as pe:
            code_str = f"http_{pe.status_code}" if pe.status_code else "error"
            _LAST_OUTCOME["fallback"] = code_str
            logger.warning(f"Fallback provider (OpenRouter) failed with {code_str}")
        except Exception:
            _LAST_OUTCOME["fallback"] = "exception"
            logger.warning("Fallback provider (OpenRouter) threw unexpected exception")

    return None, None

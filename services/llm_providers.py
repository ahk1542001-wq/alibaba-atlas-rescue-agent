"""Dual-provider fallback layer for Qwen-Agent and LLM capabilities.

Chain: ModelScope primary (Qwen3-235B-A22B-Instruct-2507) -> OpenRouter fallback (qwen/qwen3-235b-a22b-2507).
Never logs, prints, or exposes API key values.

Audit finding #8 semantics:
- Health cache entries carry a monotonic timestamp and expire after
  HEALTH_TTL_SECONDS (5 min), after which the provider is re-probed.
- The unhealthy classification is IDENTICAL in the resolve path and in
  chat_with_fallback: HTTP 429, 401, any 5xx, or timeout (408) -> unhealthy.
- Successful calls refresh the cache entry consistently.
- active_provider() returns the provider name recorded at the last
  successful resolve_llm_cfg() — it never re-probes and never guesses from
  URL substrings.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("llm_providers")

MODELSCOPE_DEFAULT_URL = "https://api-inference.modelscope.ai/v1"
MODELSCOPE_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"

OPENROUTER_DEFAULT_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "qwen/qwen3-235b-a22b-2507"

# Health cache: provider name -> (is_healthy, monotonic_probed_at).
# Entries older than HEALTH_TTL_SECONDS are treated as expired and re-probed.
HEALTH_TTL_SECONDS: float = 300.0
_PROVIDER_HEALTH: Dict[str, Tuple[bool, float]] = {}
# Provider name recorded by the last successful resolve_llm_cfg().
_RESOLVED_PROVIDER: Optional[str] = None
_LAST_OUTCOME: Dict[str, Any] = {
    "primary": "unprobed",
    "fallback": "unprobed",
    "served_by": None,
}


class ProviderError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _record_health(name: str, healthy: bool) -> None:
    _PROVIDER_HEALTH[name] = (bool(healthy), time.monotonic())


def _cached_health(name: str) -> Optional[bool]:
    """Return the cached health flag if fresh, else None (expired/absent)."""
    entry = _PROVIDER_HEALTH.get(name)
    if entry is None:
        return None
    healthy, probed_at = entry
    if time.monotonic() - probed_at > HEALTH_TTL_SECONDS:
        return None
    return healthy


def _is_unhealthy_error(pe: ProviderError) -> bool:
    """Single source of truth for unhealthy classification (audit #8).

    429 (rate limit), 401 (auth), any 5xx (server), and timeout (mapped to
    408 upstream) all mark the provider unhealthy. Errors without a status
    code (network failures) are also treated as unhealthy. Client errors
    like 400 do NOT demote provider health.
    """
    code = pe.status_code
    if code is None:
        return True
    return code in (401, 408, 429) or code >= 500


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
    cached = _cached_health(name)
    if cached is not None:
        return cached

    info = _get_provider_info(name)
    if not info:
        _record_health(name, False)
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
        # Any probe failure is conservatively recorded as unhealthy; the TTL
        # ensures the provider gets another chance within 5 minutes.
        is_healthy = False
    except Exception as e:
        logger.warning(f"Health probe for provider {name} encountered error: {type(e).__name__}")
        is_healthy = False

    _record_health(name, is_healthy)
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
    """Resolve the first healthy provider into a Qwen-Agent llm_cfg dictionary.

    On success, records the chosen provider name for active_provider().
    """
    global _RESOLVED_PROVIDER
    for provider_name in ("modelscope", "openrouter"):
        info = _get_provider_info(provider_name)
        if not info:
            continue
        if _probe_provider_health(provider_name):
            _RESOLVED_PROVIDER = provider_name
            return {
                "model": info["model"],
                "model_server": info["base_url"],
                "api_key": info["api_key"],
                "generate_cfg": {
                    "fncall_prompt_type": "nous",
                    "extra_body": {"enable_thinking": False},
                },
            }
    # No provider could be resolved: clear the recorded name so
    # active_provider() reports the true current state (audit #8).
    _RESOLVED_PROVIDER = None
    return None


def active_provider() -> str:
    """Return the provider name recorded at the last successful resolution.

    Never probes and never guesses from URL substrings (audit #8). Returns
    "none" if no provider has been resolved in this process yet.
    """
    return _RESOLVED_PROVIDER or "none"


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
    Never raises; never logs secret keys. Unhealthy classification is the same
    as in the resolve path: 429/401/5xx/timeout (audit #8).
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
            _record_health("modelscope", True)
            return content, "modelscope"
        except ProviderError as pe:
            code_str = f"http_{pe.status_code}" if pe.status_code else "error"
            _LAST_OUTCOME["primary"] = code_str
            if _is_unhealthy_error(pe):
                _record_health("modelscope", False)
            logger.warning(f"Primary provider (ModelScope) failed with {code_str}; attempting fallback")
        except Exception:
            _LAST_OUTCOME["primary"] = "exception"
            _record_health("modelscope", False)
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
            _record_health("openrouter", True)
            return content, "openrouter"
        except ProviderError as pe:
            code_str = f"http_{pe.status_code}" if pe.status_code else "error"
            _LAST_OUTCOME["fallback"] = code_str
            if _is_unhealthy_error(pe):
                _record_health("openrouter", False)
            logger.warning(f"Fallback provider (OpenRouter) failed with {code_str}")
        except Exception:
            _LAST_OUTCOME["fallback"] = "exception"
            _record_health("openrouter", False)
            logger.warning("Fallback provider (OpenRouter) threw unexpected exception")

    return None, None

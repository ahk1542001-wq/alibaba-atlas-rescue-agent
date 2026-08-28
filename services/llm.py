"""Qwen-2.5 LLM client via OpenAI-compatible endpoints.

Provider auto-detection from environment:
  - LLM_BASE_URL + ALIBABA_MODEL_API_KEY  -> custom endpoint (Model Studio / ModelScope / OpenRouter)
  - key prefix "sk-or-"                    -> OpenRouter (free :free models)
  - default                                -> ModelScope API-Inference

All failures return None so callers can fall back to deterministic logic.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import settings

logger = logging.getLogger("llm")

MODELSCOPE_URL = "https://api-inference.modelscope.cn/v1"
OPENROUTER_URL = "https://openrouter.ai/api/v1"


def _provider() -> Optional[Tuple[str, str]]:
    """Return (base_url, api_key) for the first available provider."""
    key: str = (settings.model_api_key or "").strip()
    if not key or key.startswith("your_"):
        return None
    if key.startswith("sk-or-"):
        return OPENROUTER_URL, key
    base: str = (settings.llm_base_url or "").strip()
    if base:
        return base.rstrip("/"), key
    return MODELSCOPE_URL, key


def provider_name() -> str:
    """Human-readable provider label for telemetry/health endpoints."""
    p = _provider()
    if not p:
        return "none"
    url = p[0]
    if OPENROUTER_URL in url:
        return "openrouter"
    if "modelscope" in url:
        return "modelscope"
    if "dashscope" in url or "modelstudio" in url:
        return "alibaba_model_studio"
    return "custom_openai_compatible"


def parse_json(text: Optional[str]) -> Any:
    """Extract the first JSON object/array from LLM text (handles ``` fences)."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = min(
        (i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1),
        default=-1,
    )
    if start == -1:
        return None
    opener = cleaned[start]
    closer = "}" if opener == "{" else "]"
    end = cleaned.rfind(closer)
    if end <= start:
        return None
    import json

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("LLM JSON parse failed")
        return None


async def chat(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    max_tokens: int = 400,
    temperature: float = 0.4,
) -> Optional[str]:
    """One real LLM completion call. Returns content or None on any failure."""
    provider = _provider()
    if not provider:
        logger.info("LLM not configured; skipping call")
        return None
    base_url, api_key = provider
    model = model or settings.default_model
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            used_model = data.get("model", model)
            usage = data.get("usage", {})
            logger.info(
                "LLM ok via %s model=%s tokens=%s",
                provider_name(),
                used_model,
                usage.get("total_tokens"),
            )
            return (content or "").strip() or None
    except Exception as exc:  # noqa: BLE001 — fail-open to deterministic fallback
        logger.warning("LLM call failed (%s)", type(exc).__name__)
        return None

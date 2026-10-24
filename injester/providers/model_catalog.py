"""
Model Catalog Service (BYOAI).
Discovers the models actually available on a user-provided API endpoint so the console
can offer a live model picker instead of hard-coded model identifiers.

Supported providers:
- ``openrouter``        -> GET {base_url}/models  (OpenRouter model registry, pricing aware)
- ``openai_compatible`` -> GET {base_url}/models  (OpenAI, Ollama, vLLM, Lightning AI, ...)

Free-model detection is pricing based (prompt + completion pricing both zero) with a
``:free`` identifier suffix fallback, which is how OpenRouter flags its no-cost tier.
"""

from typing import Any, Dict, List, Optional
import httpx

from injester.config import settings


class ModelCatalogError(Exception):
    """Raised when a provider's model catalog cannot be retrieved or parsed."""


def _is_zero_price(value: Any) -> bool:
    """Returns True when a pricing field denotes a zero-cost (free) tier."""
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    return str(value).strip().lower() in ("0", "0.0", "0.00", "free")


def _extract_pricing(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts normalized pricing metadata from a raw catalog entry."""
    pricing = entry.get("pricing")
    if not isinstance(pricing, dict):
        pricing = {}
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    return {
        "prompt": prompt,
        "completion": completion,
        "is_free": _is_zero_price(prompt) and _is_zero_price(completion),
    }


def _normalize_model(entry: Dict[str, Any], provider: str) -> Optional[Dict[str, Any]]:
    """Normalizes a single raw catalog entry into the engine's model descriptor."""
    if not isinstance(entry, dict):
        return None

    model_id = str(entry.get("id") or entry.get("name") or "").strip()
    if not model_id:
        return None

    pricing = _extract_pricing(entry)
    suffix_free = model_id.lower().endswith(":free")
    is_free = bool(pricing["is_free"] or suffix_free)

    context_length = entry.get("context_length") or entry.get("context_window")
    try:
        context_length = int(context_length) if context_length is not None else None
    except (TypeError, ValueError):
        context_length = None

    description = entry.get("description") or ""
    if not isinstance(description, str):
        description = ""

    return {
        "id": model_id,
        "name": str(entry.get("name") or model_id),
        "provider": provider,
        "context_length": context_length,
        "pricing": pricing,
        "is_free": is_free,
        "description": description[:280],
    }


def _resolve_endpoint(provider: str, base_url: Optional[str]) -> str:
    """Resolves the fully qualified models endpoint for the requested provider."""
    normalized = (provider or "openrouter").strip().lower()

    if normalized == "openrouter":
        resolved = (base_url or "").strip() or settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1"
    else:
        resolved = (base_url or "").strip() or settings.OPENAI_BASE_URL or ""

    if not resolved:
        raise ModelCatalogError(
            "No base URL available for model discovery. Configure a provider base URL first."
        )

    resolved = resolved.rstrip("/")
    if resolved.endswith("/models"):
        return resolved
    return f"{resolved}/models"


def _build_headers(api_key: Optional[str]) -> Dict[str, str]:
    """Builds request headers, attaching bearer auth only when a usable key exists."""
    headers = {"Accept": "application/json", "User-Agent": "injester-engine/0.1"}
    key = (api_key or "").strip()
    if key and key.lower() not in ("ollama", "not-needed", "none", "null"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def fetch_models(
    provider: str = "openrouter",
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 25.0,
) -> List[Dict[str, Any]]:
    """
    Retrieves and normalizes the model catalog exposed by a provider endpoint.

    Raises ModelCatalogError on transport, HTTP, or payload-shape failures.
    """
    endpoint = _resolve_endpoint(provider, base_url)
    headers = _build_headers(api_key)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(endpoint, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message") or exc.response.text[:200]
        except Exception:
            detail = exc.response.text[:200]
        if status in (401, 403):
            raise ModelCatalogError(
                f"Model discovery rejected by {provider} (HTTP {status}). Check the API key. {detail}".strip()
            ) from exc
        raise ModelCatalogError(
            f"Model discovery failed for {provider} (HTTP {status}). {detail}".strip()
        ) from exc
    except httpx.HTTPError as exc:
        raise ModelCatalogError(
            f"Model discovery could not reach {provider} at {endpoint}: {exc}"
        ) from exc
    except ValueError as exc:
        raise ModelCatalogError(
            f"Model discovery returned a non-JSON response from {endpoint}."
        ) from exc

    raw_models: Any
    if isinstance(payload, dict):
        raw_models = payload.get("data")
        if raw_models is None:
            raw_models = payload.get("models")
    elif isinstance(payload, list):
        raw_models = payload
    else:
        raw_models = None

    if not isinstance(raw_models, list):
        raise ModelCatalogError(
            f"Model discovery response from {provider} did not contain a model list."
        )

    normalized: List[Dict[str, Any]] = []
    for entry in raw_models:
        model = _normalize_model(entry, (provider or "openrouter").strip().lower())
        if model:
            normalized.append(model)

    normalized.sort(key=lambda m: (not m["is_free"], m["id"].lower()))
    return normalized


def list_models(
    provider: str = "openrouter",
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    free_only: bool = False,
    timeout: float = 25.0,
) -> Dict[str, Any]:
    """
    Returns a provider model catalog with optional free-only filtering.

    The response always reports both the total and the filtered counts so the UI can
    communicate how many models were hidden by the free filter.
    """
    all_models = fetch_models(provider=provider, base_url=base_url, api_key=api_key, timeout=timeout)
    free_models = [m for m in all_models if m["is_free"]]
    filtered = [m for m in all_models if m["is_free"]] if free_only else all_models

    return {
        "provider": (provider or "openrouter").strip().lower(),
        "free_only": bool(free_only),
        "total_count": len(all_models),
        "free_count": len(free_models),
        "returned_count": len(filtered),
        "models": filtered,
    }

"""
Engine & LLM BYOAI Settings REST API Router.
Provides inspection, configuration, dynamic hot-swapping, and disk persistence
for user LLM providers (Gemini, OpenRouter, Ollama, OpenAI, Lightning AI) and for the
System-1 grounding verifier (TypeSafe Jev or any OpenAI-compatible endpoint).
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from injester.config import settings
from injester.api.deps import get_current_sec_ctx, require_super_admin
from injester.domain.auth import SecurityContext
from injester.providers.model_catalog import ModelCatalogError, list_models

router = APIRouter(prefix="/api/v1/settings", tags=["Engine Settings & BYOAI"])


class SettingsResponse(BaseModel):
    model_name: str
    openai_base_url: str
    openai_api_key_masked: str
    gemini_api_key_configured: bool
    gemini_api_key_masked: str
    system1_provider: str
    system1_api_mode: str
    system1_api_base_url: str
    system1_api_key_masked: str
    system1_api_key_configured: bool
    system1_model: str
    embedding_model: str
    workspace_dir: str
    database_url: str
    presets: Dict[str, Any]


class UpdateSettingsRequest(BaseModel):
    preset: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    gemini_api_key: Optional[str] = None
    # System-1 grounding verifier (BYOAI)
    system1_provider: Optional[str] = None
    system1_api_mode: Optional[str] = None
    system1_base_url: Optional[str] = None
    system1_api_key: Optional[str] = None
    system1_model: Optional[str] = None


class ModelDiscoveryRequest(BaseModel):
    provider: str = Field(default="openrouter", description="Provider whose catalog should be listed")
    base_url: Optional[str] = Field(default=None, description="Override base URL; defaults to the configured provider URL")
    api_key: Optional[str] = Field(default=None, description="API key used for catalog discovery")
    free_only: bool = Field(default=False, description="When true, only return zero-cost models")


class ValidateCredentialsRequest(BaseModel):
    provider: Optional[str] = Field(default="openai_compatible", description="Provider type (openrouter, openai_compatible, ollama, lightning)")
    base_url: Optional[str] = Field(default=None, description="Provider base URL")
    api_key: Optional[str] = Field(default=None, description="API key")


class ValidateCredentialsResponse(BaseModel):
    valid: bool
    status: str
    message: str
    model_count: Optional[int] = None


class ModelDescriptor(BaseModel):
    id: str
    name: str
    provider: str
    context_length: Optional[int] = None
    is_free: bool = False
    description: str = ""


class ModelCatalogResponse(BaseModel):
    provider: str
    free_only: bool
    total_count: int
    free_count: int
    returned_count: int
    models: List[ModelDescriptor]


def mask_key(k: Optional[str]) -> str:
    if not k:
        return ""
    if len(k) <= 8:
        return "***"
    return f"{k[:4]}...{k[-4:]}"


def persist_settings_to_disk():
    """Persists current BYOAI configuration to workspace config.env."""
    try:
        settings.persist_to_disk()
    except Exception:
        # Non-fatal: configuration remains applied in-memory
        pass


def _build_presets() -> Dict[str, Any]:
    """Builds the provider preset catalogue surfaced to the console."""
    return {
        "gemini": {
            "name": "Google Gemini (Native)",
            "description": "High-fidelity structured schema via Google GenAI SDK",
            "model": "gemini-2.5-flash-lite",
            "base_url": "https://generativelanguage.googleapis.com",
            "needs_gemini_key": True,
        },
        "openrouter": {
            "name": "OpenRouter (Multi-Model)",
            "description": "Access DeepSeek, Qwen, Claude, Llama via OpenRouter",
            "base_url": settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1",
            "model": "google/gemini-2.5-flash-lite-preview-06-17",
            "free_model": settings.OPENROUTER_FREE_MODEL or "qwen/qwen3.8-27b:free",
            "supports_model_discovery": True,
        },
        "ollama": {
            "name": "Local Ollama (Offline / Free)",
            "description": "Local zero-cloud inference with Qwen 2.5, Llama 3, DeepSeek",
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:7b-ctx16k",
            "api_key": "ollama",
            "supports_model_discovery": True,
        },
        "openai": {
            "name": "OpenAI Official",
            "description": "GPT-4o, GPT-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "supports_model_discovery": True,
        },
        "lightning": {
            "name": "Lightning AI",
            "description": "Lightning AI serverless endpoints",
            "base_url": settings.LIGHTNING_BASE_URL or "https://lightning.ai/api/v1/",
            "model": settings.LIGHTNING_MODEL or "google/gemini-2.5-flash-lite-preview-06-17",
        },
    }


@router.get("", response_model=SettingsResponse)
def get_settings(sec_ctx: SecurityContext = Depends(get_current_sec_ctx)):
    """Retrieve active LLM BYOAI provider and system configuration."""
    system1 = settings.system1_effective_config()

    return SettingsResponse(
        model_name=settings.MODEL_NAME,
        openai_base_url=settings.OPENAI_BASE_URL,
        openai_api_key_masked=mask_key(settings.OPENAI_API_KEY),
        gemini_api_key_configured=bool(settings.GEMINI_API_KEY),
        gemini_api_key_masked=mask_key(settings.GEMINI_API_KEY),
        system1_provider=system1["provider"],
        system1_api_mode=system1["api_mode"],
        system1_api_base_url=system1["base_url"],
        system1_api_key_masked=mask_key(system1["api_key"]),
        system1_api_key_configured=bool(system1["api_key"]),
        system1_model=system1["model"],
        embedding_model=settings.EMBEDDING_MODEL,
        workspace_dir=str(settings.WORKSPACE_DIR),
        database_url=settings.DATABASE_URL,
        presets=_build_presets(),
    )


@router.post("", dependencies=[Depends(require_super_admin)])
def update_settings(
    req: UpdateSettingsRequest,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
):
    """
    Update LLM provider, System-1 verifier, and BYOAI configuration in real-time.
    Saves and applies settings immediately to runtime and disk.
    """
    if req.preset == "gemini":
        if req.gemini_api_key:
            settings.GEMINI_API_KEY = req.gemini_api_key.strip()
        if req.model_name:
            settings.MODEL_NAME = req.model_name.strip()
        else:
            settings.MODEL_NAME = "gemini-2.5-flash-lite"
    elif req.preset == "openrouter":
        settings.switch_to_openrouter_free()
        if req.api_key:
            settings.OPENAI_API_KEY = req.api_key.strip()
        if req.model_name:
            settings.MODEL_NAME = req.model_name.strip()
    elif req.preset == "ollama":
        settings.update_llm_settings(
            base_url=req.base_url.strip() if req.base_url else "http://localhost:11434/v1",
            api_key="ollama",
            model_name=req.model_name.strip() if req.model_name else "qwen2.5:7b-ctx16k",
        )
    elif req.preset == "lightning":
        settings.switch_to_lightning()
        if req.api_key:
            settings.OPENAI_API_KEY = req.api_key.strip()
    else:
        # Custom BYOAI
        if req.base_url:
            settings.OPENAI_BASE_URL = req.base_url.strip()
        if req.api_key:
            settings.OPENAI_API_KEY = req.api_key.strip()
        if req.model_name:
            settings.MODEL_NAME = req.model_name.strip()
        if req.gemini_api_key:
            settings.GEMINI_API_KEY = req.gemini_api_key.strip()

    # System-1 grounding verifier configuration (independent of the main LLM)
    if any(
        value is not None
        for value in (
            req.system1_provider,
            req.system1_api_mode,
            req.system1_base_url,
            req.system1_api_key,
            req.system1_model,
        )
    ):
        settings.update_system1_settings(
            provider=req.system1_provider,
            api_mode=req.system1_api_mode,
            base_url=req.system1_base_url,
            api_key=req.system1_api_key,
            model=req.system1_model,
        )

    persist_settings_to_disk()

    system1 = settings.system1_effective_config()

    return {
        "status": "success",
        "message": "LLM BYOAI configuration updated and applied successfully.",
        "active_model": settings.MODEL_NAME,
        "base_url": settings.OPENAI_BASE_URL,
        "api_key_masked": mask_key(settings.OPENAI_API_KEY),
        "gemini_api_key_masked": mask_key(settings.GEMINI_API_KEY),
        "system1": {
            "provider": system1["provider"],
            "api_mode": system1["api_mode"],
            "base_url": system1["base_url"],
            "api_key_masked": mask_key(system1["api_key"]),
            "model": system1["model"],
        },
    }


@router.post("/models", response_model=ModelCatalogResponse, dependencies=[Depends(require_super_admin)])
def discover_models(
    req: ModelDiscoveryRequest,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
):
    """
    Discovers the models available on a user-provided API endpoint.

    Used by the console to populate a live model picker. When `free_only` is set, only
    zero-cost models are returned (OpenRouter's free tier is detected via pricing and
    the `:free` identifier suffix).
    """
    provider = (req.provider or "openrouter").strip().lower()
    base_url = (req.base_url or "").strip() or None
    api_key = (req.api_key or "").strip() or None

    # Fall back to the configured credentials when the caller does not supply them.
    if not api_key:
        if provider == "openrouter":
            api_key = (settings.OPENROUTER_API_KEY or "").strip() or None
        else:
            api_key = (settings.OPENAI_API_KEY or "").strip() or None
    if not base_url:
        if provider == "openrouter":
            base_url = settings.OPENROUTER_BASE_URL or None
        else:
            base_url = settings.OPENAI_BASE_URL or None

    try:
        catalog = list_models(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            free_only=req.free_only,
        )
    except ModelCatalogError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return ModelCatalogResponse(**catalog)


@router.post("/validate", response_model=ValidateCredentialsResponse, dependencies=[Depends(require_super_admin)])
def validate_provider(
    req: ValidateCredentialsRequest,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
):
    """Validates connectivity and credentials for an LLM provider endpoint."""
    res = settings.validate_credentials(
        provider=req.provider,
        base_url=req.base_url,
        api_key=req.api_key,
    )
    if not res["valid"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return ValidateCredentialsResponse(**res)

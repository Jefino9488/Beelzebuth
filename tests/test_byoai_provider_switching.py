"""
BYOAI Provider Integration & Dynamic Runtime Client Switching Tests.

Validates that:
- Switching providers updates active runtime clients immediately without requiring a restart.
- Proposition extractors and semantic reasoners dynamically reflect base_url, api_key, and model_name.
- Explicitly injected clients and models are preserved and not overridden by settings changes.
- Configuration persists cleanly to config.env on disk and reloads correctly.
- Updating settings automatically resets the ServiceManager's cached pipeline.
- Credential validation and endpoint connectivity checks report descriptive errors on unreachable/invalid hosts.
- The REST API (/api/v1/settings, /api/v1/settings/validate) behaves correctly with authentication.
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from injester.config import settings
from injester.semantic.extractor import AtomicPropositionExtractor
from injester.semantic.reasoner import SemanticProcessReasoner
from injester.application.manager import manager
from injester.api.app import app


@pytest.fixture(autouse=True)
def restore_settings():
    """Preserves and restores settings around each test to avoid state pollution."""
    orig_base_url = settings.OPENAI_BASE_URL
    orig_api_key = settings.OPENAI_API_KEY
    orig_model = settings.MODEL_NAME
    orig_s1_provider = settings.SYSTEM1_PROVIDER
    orig_s1_mode = settings.SYSTEM1_API_MODE
    orig_s1_url = settings.SYSTEM1_API_BASE_URL
    orig_s1_key = settings.SYSTEM1_API_KEY
    orig_s1_model = settings.SYSTEM1_MODEL
    yield
    settings.OPENAI_BASE_URL = orig_base_url
    settings.OPENAI_API_KEY = orig_api_key
    settings.MODEL_NAME = orig_model
    settings.SYSTEM1_PROVIDER = orig_s1_provider
    settings.SYSTEM1_API_MODE = orig_s1_mode
    settings.SYSTEM1_API_BASE_URL = orig_s1_url
    settings.SYSTEM1_API_KEY = orig_s1_key
    settings.SYSTEM1_MODEL = orig_s1_model


def test_dynamic_runtime_client_switching():
    """Tests that active extractor and reasoner instances immediately reflect updated settings."""
    # 1. Initialize extractor and reasoner without explicit clients
    extractor = AtomicPropositionExtractor()
    reasoner = SemanticProcessReasoner()

    # 2. Switch to OpenRouter free preset
    settings.switch_to_openrouter_free()

    assert extractor.model_name == settings.OPENROUTER_FREE_MODEL
    assert reasoner.model_name == settings.OPENROUTER_FREE_MODEL
    assert "openrouter.ai" in str(extractor.client.client.base_url)
    assert "openrouter.ai" in str(reasoner.client.client.base_url)

    # 3. Switch to Lightning AI preset
    settings.switch_to_lightning()

    assert extractor.model_name == settings.LIGHTNING_MODEL
    assert reasoner.model_name == settings.LIGHTNING_MODEL
    assert "lightning.ai" in str(extractor.client.client.base_url)
    assert "lightning.ai" in str(reasoner.client.client.base_url)

    # 4. Switch to Custom OpenAI-compatible endpoint
    custom_url = "https://custom-ai.internal/v1"
    custom_key = "sk-custom-secret-key-42"
    custom_model = "meta/llama-3.3-70b-instruct"

    settings.update_llm_settings(
        base_url=custom_url,
        api_key=custom_key,
        model_name=custom_model,
    )

    assert extractor.model_name == custom_model
    assert reasoner.model_name == custom_model
    assert str(extractor.client.client.base_url).rstrip("/") == custom_url
    assert str(reasoner.client.client.base_url).rstrip("/") == custom_url
    assert extractor.client.client.api_key == custom_key
    assert reasoner.client.client.api_key == custom_key


def test_explicit_client_and_model_preservation():
    """Explicitly injected clients or models in constructor must not be overridden by settings changes."""
    mock_client = MagicMock()
    custom_model = "frozen-specialist-model"

    extractor = AtomicPropositionExtractor(client=mock_client, model_name=custom_model)
    reasoner = SemanticProcessReasoner(client=mock_client, model_name=custom_model)

    assert extractor.client is mock_client
    assert reasoner.client is mock_client
    assert extractor.model_name == custom_model
    assert reasoner.model_name == custom_model

    # Change settings
    settings.update_llm_settings(
        base_url="https://override.example.com/v1",
        api_key="different-key",
        model_name="overridden-model",
    )

    # Explicit values remain preserved
    assert extractor.client is mock_client
    assert reasoner.client is mock_client
    assert extractor.model_name == custom_model
    assert reasoner.model_name == custom_model


def test_persist_to_disk_and_reload(tmp_path: Path):
    """Configuration should persist cleanly to config.env and reload accurately."""
    custom_env_file = tmp_path / "config.env"

    settings.update_llm_settings(
        base_url="https://persisted.api/v1",
        api_key="sk-persisted-token-999",
        model_name="qwen/qwen-2.5-32b-instruct",
    )
    settings.update_system1_settings(
        provider="openai_compatible",
        api_mode="openai_compatible",
        base_url="https://system1.persisted/v1",
        api_key="s1-persisted-key",
        model="s1-model-v2",
    )

    # Persist to disk
    saved_path = settings.persist_to_disk(target_file=custom_env_file)
    assert saved_path.exists()

    content = custom_env_file.read_text(encoding="utf-8")
    assert "OPENAI_BASE_URL=https://persisted.api/v1" in content
    assert "OPENAI_API_KEY=sk-persisted-token-999" in content
    assert "MODEL_NAME=qwen/qwen-2.5-32b-instruct" in content
    assert "SYSTEM1_PROVIDER=openai_compatible" in content

    # Mutate in-memory settings
    settings.OPENAI_BASE_URL = "https://mutated.api/v1"
    settings.OPENAI_API_KEY = "mutated-key"
    settings.MODEL_NAME = "mutated-model"

    # Reload from persisted disk file
    settings.reload_from_disk(source_file=custom_env_file)
    assert settings.OPENAI_BASE_URL == "https://persisted.api/v1"
    assert settings.OPENAI_API_KEY == "sk-persisted-token-999"
    assert settings.MODEL_NAME == "qwen/qwen-2.5-32b-instruct"


def test_manager_pipeline_resets_on_settings_update():
    """Updating LLM or System-1 settings must automatically invalidate the cached pipeline."""
    # Obtain initial pipeline
    pipe1 = manager.get_pipeline()
    assert manager._pipeline is not None

    # Updating settings should trigger manager.reset_pipeline()
    settings.update_llm_settings(
        base_url="https://new-endpoint.api/v1",
        api_key="new-key",
        model_name="new-model",
    )
    assert manager._pipeline is None

    # Next call to get_pipeline() returns a new instance
    pipe2 = manager.get_pipeline()
    assert manager._pipeline is not None
    assert pipe2 is not pipe1

    # Updating System-1 settings also resets the pipeline
    settings.update_system1_settings(provider="openjev")
    assert manager._pipeline is None


def test_credential_validation_error_handling():
    """Validating credentials against unreachable or invalid endpoints produces clear, graceful errors."""
    # 1. Missing base URL
    res = settings.validate_credentials(provider="openai_compatible", base_url="", api_key="")
    assert res["valid"] is False
    assert res["status"] == "error"
    assert "Base URL is required" in res["message"]

    # 2. Unreachable endpoint
    res_unreachable = settings.validate_credentials(
        provider="openai_compatible",
        base_url="http://127.0.0.1:54321/v1",
        api_key="dummy-key",
        timeout=1.0,
    )
    assert res_unreachable["valid"] is False
    assert res_unreachable["status"] == "error"
    assert "could not reach" in res_unreachable["message"].lower() or "error" in res_unreachable["message"].lower()


def test_credential_validation_success_mock():
    """Validating credentials when provider responds returns valid=True and model count."""
    mock_models = [
        {"id": "model-1", "name": "Model 1", "provider": "openai_compatible", "pricing": {}, "is_free": False, "description": ""},
        {"id": "model-2", "name": "Model 2", "provider": "openai_compatible", "pricing": {}, "is_free": True, "description": ""},
    ]
    with patch("injester.providers.model_catalog.fetch_models", return_value=mock_models):
        res = settings.validate_credentials(
            provider="openai_compatible",
            base_url="https://mock.api/v1",
            api_key="mock-key",
        )
        assert res["valid"] is True
        assert res["status"] == "ok"
        assert res["model_count"] == 2
        assert "Successfully authenticated" in res["message"]


def test_api_settings_validate_and_update():
    """Validates the REST API endpoints /api/v1/settings and /api/v1/settings/validate."""
    from fastapi.testclient import TestClient
    client = TestClient(app)

    # Test /api/v1/settings GET
    get_res = client.get("/api/v1/settings")
    assert get_res.status_code == 200
    assert "model_name" in get_res.json()
    assert "presets" in get_res.json()

    # Test /api/v1/settings/validate with unreachable host
    val_res = client.post(
        "/api/v1/settings/validate",
        json={"provider": "openai_compatible", "base_url": "http://127.0.0.1:54321/v1", "api_key": "bad-key"},
    )
    assert val_res.status_code == 400
    assert "could not reach" in val_res.json()["detail"].lower() or "error" in val_res.json()["detail"].lower()

    # Test /api/v1/settings POST update
    update_res = client.post(
        "/api/v1/settings",
        json={
            "preset": "openrouter",
            "model_name": "qwen/qwen-2.5-coder-32b-instruct",
        },
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["status"] == "success"
    assert data["active_model"] == "qwen/qwen-2.5-coder-32b-instruct"
    assert settings.MODEL_NAME == "qwen/qwen-2.5-coder-32b-instruct"

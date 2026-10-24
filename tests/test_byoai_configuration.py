"""
Tests for BYOAI configuration surfaces:
- System-1 grounding verifier configuration (provider / api mode / base URL / key / model)
- Live model catalog discovery with free-model filtering
"""

import json
import httpx
import pytest
from fastapi.testclient import TestClient

from injester.api.app import app
from injester.config import settings
from injester.providers.model_catalog import (
    ModelCatalogError,
    list_models,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_config_persistence(monkeypatch, tmp_path):
    """Keeps settings persistence out of the developer's real workspace during tests."""
    from injester.api.routers import settings_api

    monkeypatch.setattr(settings_api, "persist_settings_to_disk", lambda: None)
    monkeypatch.setattr(settings_api.settings, "WORKSPACE_DIR", tmp_path)


OPENROUTER_PAYLOAD = {
    "data": [
        {
            "id": "google/gemini-2.5-flash-lite-preview-06-17",
            "name": "Google: Gemini 2.5 Flash Lite Preview",
            "context_length": 1048576,
            "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
            "description": "Fast preview model",
        },
        {
            "id": "nvidia/nemotron-3.5-lightning:free",
            "name": "NVIDIA: Nemotron 3.5 Lightning (free)",
            "context_length": 131072,
            "pricing": {"prompt": "0", "completion": "0"},
            "description": "Zero-cost tier",
        },
        {
            "id": "qwen/qwen3-8b:free",
            "name": "Qwen: Qwen3 8B (free)",
            "context_length": 32768,
            "pricing": {"prompt": "0", "completion": "0"},
            "description": "Zero-cost tier",
        },
    ]
}


class _MockTransport(httpx.BaseTransport):
    """Records the outgoing request and replays a canned catalog response."""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return httpx.Response(
            status_code=self.status_code,
            json=self.payload,
            request=request,
        )


def _patch_transport(monkeypatch, transport):
    """Routes every httpx client used by the catalog through the mock transport."""
    original_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


# ---------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------
def test_model_catalog_lists_all_models(monkeypatch):
    transport = _MockTransport(OPENROUTER_PAYLOAD)
    _patch_transport(monkeypatch, transport)

    catalog = list_models(provider="openrouter", api_key="sk-or-test")

    assert catalog["provider"] == "openrouter"
    assert catalog["total_count"] == 3
    assert catalog["free_count"] == 2
    assert catalog["returned_count"] == 3
    assert {m["id"] for m in catalog["models"]} == {
        "google/gemini-2.5-flash-lite-preview-06-17",
        "nvidia/nemotron-3.5-lightning:free",
        "qwen/qwen3-8b:free",
    }
    # Authorization header carries the BYOAI key
    assert transport.requests[0].headers["Authorization"] == "Bearer sk-or-test"


def test_model_catalog_free_only_filter(monkeypatch):
    transport = _MockTransport(OPENROUTER_PAYLOAD)
    _patch_transport(monkeypatch, transport)

    catalog = list_models(provider="openrouter", api_key="sk-or-test", free_only=True)

    assert catalog["total_count"] == 3
    assert catalog["free_count"] == 2
    assert catalog["returned_count"] == 2
    assert all(m["is_free"] for m in catalog["models"])
    assert {m["id"] for m in catalog["models"]} == {
        "nvidia/nemotron-3.5-lightning:free",
        "qwen/qwen3-8b:free",
    }


def test_model_catalog_detects_free_by_suffix_without_zero_pricing(monkeypatch):
    payload = {
        "data": [
            {"id": "vendor/model:free", "name": "Free", "pricing": {"prompt": "0.01", "completion": "0"}},
            {"id": "vendor/paid", "name": "Paid", "pricing": {"prompt": "0.01", "completion": "0.02"}},
        ]
    }
    transport = _MockTransport(payload)
    _patch_transport(monkeypatch, transport)

    catalog = list_models(provider="openrouter", api_key="k", free_only=True)

    assert [m["id"] for m in catalog["models"]] == ["vendor/model:free"]


def test_model_catalog_reports_auth_failure(monkeypatch):
    transport = _MockTransport({"error": {"message": "no key"}}, status_code=401)
    _patch_transport(monkeypatch, transport)

    with pytest.raises(ModelCatalogError) as exc:
        list_models(provider="openrouter", api_key="bad")

    assert "401" in str(exc.value)


def test_model_catalog_omits_auth_header_for_placeholder_keys(monkeypatch):
    transport = _MockTransport(OPENROUTER_PAYLOAD)
    _patch_transport(monkeypatch, transport)

    list_models(provider="openai_compatible", base_url="http://localhost:11434/v1", api_key="ollama")

    assert "Authorization" not in transport.requests[0].headers


def test_model_catalog_resolves_openrouter_default_base_url(monkeypatch):
    transport = _MockTransport(OPENROUTER_PAYLOAD)
    _patch_transport(monkeypatch, transport)

    list_models(provider="openrouter", api_key="k")

    assert str(transport.requests[0].url).rstrip("/").endswith("/models")
    assert "openrouter.ai" in str(transport.requests[0].url)


# ---------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------
def test_settings_response_exposes_system1_configuration():
    res = client.get("/api/v1/settings")
    assert res.status_code == 200
    data = res.json()
    assert "system1_provider" in data
    assert "system1_api_mode" in data
    assert "system1_api_base_url" in data
    assert "system1_api_key_masked" in data
    assert "system1_model" in data


def test_settings_update_persists_system1_configuration(monkeypatch):
    monkeypatch.setattr(settings, "SYSTEM1_PROVIDER", "openjev")
    monkeypatch.setattr(settings, "SYSTEM1_API_MODE", "typesafe")
    monkeypatch.setattr(settings, "SYSTEM1_API_BASE_URL", "")
    monkeypatch.setattr(settings, "SYSTEM1_API_KEY", "")
    monkeypatch.setattr(settings, "SYSTEM1_MODEL", "")

    res = client.post(
        "/api/v1/settings",
        json={
            "system1_provider": "jev",
            "system1_api_mode": "typesafe",
            "system1_base_url": "https://jev.example.com",
            "system1_api_key": "ts-key-1234",
            "system1_model": "jev-latest",
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["system1"]["provider"] == "jev"
    assert payload["system1"]["base_url"] == "https://jev.example.com"
    assert payload["system1"]["model"] == "jev-latest"
    assert "ts-key" not in json.dumps(payload)  # key is never echoed in clear text

    assert settings.SYSTEM1_PROVIDER == "jev"
    assert settings.SYSTEM1_API_BASE_URL == "https://jev.example.com"
    assert settings.SYSTEM1_MODEL == "jev-latest"


def test_settings_update_forces_openai_compatible_mode(monkeypatch):
    monkeypatch.setattr(settings, "SYSTEM1_PROVIDER", "openjev")
    monkeypatch.setattr(settings, "SYSTEM1_API_MODE", "typesafe")

    res = client.post(
        "/api/v1/settings",
        json={"system1_provider": "openai", "system1_base_url": "https://openrouter.ai/api/v1"},
    )

    assert res.status_code == 200
    assert res.json()["system1"]["api_mode"] == "openai_compatible"
    assert settings.SYSTEM1_API_MODE == "openai_compatible"


def test_model_discovery_endpoint_filters_free_models(monkeypatch):
    transport = _MockTransport(OPENROUTER_PAYLOAD)
    _patch_transport(monkeypatch, transport)

    res = client.post(
        "/api/v1/settings/models",
        json={
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-test",
            "free_only": True,
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert data["free_only"] is True
    assert data["returned_count"] == 2
    assert data["free_count"] == 2
    assert all(m["is_free"] for m in data["models"])


def test_model_discovery_endpoint_surfaces_upstream_errors(monkeypatch):
    transport = _MockTransport({"error": {"message": "invalid key"}}, status_code=401)
    _patch_transport(monkeypatch, transport)

    res = client.post(
        "/api/v1/settings/models",
        json={"provider": "openrouter", "api_key": "bad", "free_only": False},
    )

    assert res.status_code == 502
    assert "401" in res.json()["detail"]


# ---------------------------------------------------------------------
# System-1 verifier configuration resolution
# ---------------------------------------------------------------------
def test_system1_effective_config_prefers_explicit_settings(monkeypatch):
    monkeypatch.setattr(settings, "SYSTEM1_API_MODE", "openai_compatible")
    monkeypatch.setattr(settings, "SYSTEM1_API_BASE_URL", "https://s1.example.com/v1")
    monkeypatch.setattr(settings, "SYSTEM1_API_KEY", "s1-key")
    monkeypatch.setattr(settings, "SYSTEM1_MODEL", "s1-model")
    monkeypatch.setattr(settings, "SYSTEM1_PROVIDER", "openai")

    resolved = settings.system1_effective_config()

    assert resolved["provider"] == "openai"
    assert resolved["api_mode"] == "openai_compatible"
    assert resolved["base_url"] == "https://s1.example.com/v1"
    assert resolved["api_key"] == "s1-key"
    assert resolved["model"] == "s1-model"


def test_system1_effective_config_falls_back_to_main_llm_for_openai_mode(monkeypatch):
    monkeypatch.setattr(settings, "SYSTEM1_API_MODE", "openai_compatible")
    monkeypatch.setattr(settings, "SYSTEM1_API_BASE_URL", "")
    monkeypatch.setattr(settings, "SYSTEM1_API_KEY", "")
    monkeypatch.setattr(settings, "SYSTEM1_MODEL", "")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "ollama")
    monkeypatch.setattr(settings, "MODEL_NAME", "qwen2.5:7b")

    resolved = settings.system1_effective_config()

    assert resolved["base_url"] == "http://localhost:11434/v1"
    assert resolved["api_key"] == "ollama"
    assert resolved["model"] == "qwen2.5:7b"


def test_jev_verifier_resolves_runtime_configuration(monkeypatch):
    from injester.semantic.verifiers.jev import JevVerifier

    monkeypatch.setattr(settings, "SYSTEM1_API_MODE", "typesafe")
    monkeypatch.setattr(settings, "SYSTEM1_API_BASE_URL", "https://jev.example.com")
    monkeypatch.setattr(settings, "SYSTEM1_API_KEY", "jev-key")
    monkeypatch.setattr(settings, "SYSTEM1_MODEL", "jev-model-x")

    verifier = JevVerifier()
    resolved = verifier._resolve_config()

    assert resolved["base_url"] == "https://jev.example.com"
    assert resolved["api_key"] == "jev-key"
    assert resolved["model"] == "jev-model-x"


def test_jev_verifier_explicit_none_disables_credentials(monkeypatch):
    from injester.semantic.verifiers.jev import JevVerifier

    monkeypatch.setattr(settings, "SYSTEM1_API_KEY", "should-be-ignored")

    verifier = JevVerifier(api_key=None)

    assert verifier._resolve_config()["api_key"] is None
    assert verifier.client is None


def test_openai_compatible_verifier_resolves_runtime_configuration(monkeypatch):
    from injester.semantic.verifiers.openai_compatible import OpenAICompatibleSystem1Verifier

    monkeypatch.setattr(settings, "SYSTEM1_API_MODE", "openai_compatible")
    monkeypatch.setattr(settings, "SYSTEM1_API_BASE_URL", "https://router.example.com/v1")
    monkeypatch.setattr(settings, "SYSTEM1_API_KEY", "or-key")
    monkeypatch.setattr(settings, "SYSTEM1_MODEL", "provider/model")

    verifier = OpenAICompatibleSystem1Verifier()
    resolved = verifier._resolve_config()

    assert resolved["base_url"] == "https://router.example.com/v1"
    assert resolved["api_key"] == "or-key"
    assert resolved["model"] == "provider/model"


def test_factory_resolves_openai_compatible_system1_provider():
    from injester.semantic.verifiers.factory import get_system1_verifier
    from injester.semantic.verifiers.openai_compatible import OpenAICompatibleSystem1Verifier

    verifier = get_system1_verifier("openai")
    assert isinstance(verifier, OpenAICompatibleSystem1Verifier)
    assert verifier.provider_name == "openai"


def test_openai_compatible_verifier_maps_typed_decisions_to_verdicts(monkeypatch):
    """The BYOAI System-1 verifier must translate typed model output into policy verdicts."""
    from injester.semantic.schemas import AtomicProposition, GroundingVerdict
    from injester.semantic.verifiers.openai_compatible import (
        NoulDecision,
        PropositionDecision,
        ModalityDecision,
        EpistemicDecision,
        OpenAICompatibleSystem1Verifier,
    )

    class _FakeCompletions:
        def __init__(self, decision):
            self.decision = decision
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)

            class _Batch:
                decisions = [self.decision]

            return _Batch()

    class _FakeClient:
        def __init__(self, decision):
            self.chat = type("Chat", (), {"completions": _FakeCompletions(decision)})()

    decision = PropositionDecision(
        proposition_id="P1",
        actor_supported=NoulDecision(probability=0.93, confidence=0.9),
        action_entailed=NoulDecision(probability=0.88, confidence=0.85),
        modality=ModalityDecision(choice="mandatory", confidence=0.8),
        epistemic=EpistemicDecision(choice="confirmed", confidence=0.8),
    )

    verifier = OpenAICompatibleSystem1Verifier(
        base_url="https://router.example.com/v1",
        api_key="or-key",
        model="provider/model",
    )
    verifier.client = _FakeClient(decision)

    prop = AtomicProposition(
        id="P1",
        actor_claim="Employee",
        action_verb="submit",
        target_object="leave request",
        evidence_spans=["S1"],
        modality="mandatory",
    )

    class _Registry:
        def get_span(self, sid):
            class _Span:
                text = "The employee must submit the leave request to the manager."
            return _Span() if sid == "S1" else None

    verdicts = verifier.verify_propositions([prop], _Registry())

    verdict = verdicts["P1"]
    assert verdict.verdict == GroundingVerdict.SUPPORTED
    assert verdict.is_verified is True
    assert verdict.actor_grounded is True
    assert verdict.action_entailed is True
    assert verdict.provider == "openai"
    assert verdict.rejection_reasons == []


def test_openai_compatible_verifier_quarantines_modality_escalation(monkeypatch):
    """A claim of 'mandatory' contradicted by a 'permissive' span must be rejected."""
    from injester.semantic.schemas import AtomicProposition, GroundingVerdict
    from injester.semantic.verifiers.openai_compatible import (
        NoulDecision,
        PropositionDecision,
        ModalityDecision,
        EpistemicDecision,
        OpenAICompatibleSystem1Verifier,
    )

    decision = PropositionDecision(
        proposition_id="P1",
        actor_supported=NoulDecision(probability=0.9, confidence=0.9),
        action_entailed=NoulDecision(probability=0.9, confidence=0.9),
        modality=ModalityDecision(choice="permissive", confidence=0.8),
        epistemic=EpistemicDecision(choice="confirmed", confidence=0.8),
    )

    class _FakeCompletions:
        def create(self, **kwargs):
            class _Batch:
                decisions = [decision]

            return _Batch()

    verifier = OpenAICompatibleSystem1Verifier(
        base_url="https://router.example.com/v1",
        api_key="or-key",
        model="provider/model",
    )
    verifier.client = type("Fake", (), {"chat": type("Chat", (), {"completions": _FakeCompletions()})()})()

    prop = AtomicProposition(
        id="P1",
        actor_claim="Employee",
        action_verb="submit",
        target_object="leave request",
        evidence_spans=["S1"],
        modality="mandatory",
    )

    class _Registry:
        def get_span(self, sid):
            class _Span:
                text = "The employee may submit the leave request to the manager."
            return _Span() if sid == "S1" else None

    verdicts = verifier.verify_propositions([prop], _Registry())

    verdict = verdicts["P1"]
    assert verdict.verdict == GroundingVerdict.UNSUPPORTED
    assert verdict.is_modality_escalated is True
    assert any("escalation" in r.lower() for r in verdict.rejection_reasons)

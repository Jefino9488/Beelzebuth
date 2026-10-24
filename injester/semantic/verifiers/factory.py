"""
Factory for System-1 Verifiers.
Instantiates the verifier implementation matching the configured provider.

Supported providers:
- 'jev'    -> TypeSafe Jev System-1 API (BYOAI: base URL / API key / model)
- 'openai' -> any OpenAI-compatible System-1 endpoint (BYOAI: base URL / API key / model)
- 'laya'   -> local Laya checkpoint (offline)
- 'openjev'-> local OpenJev NLI cross-encoder (offline)
"""

from typing import Optional

from injester.config import settings
from injester.semantic.verifiers.base import System1Verifier, UNSET
from injester.semantic.verifiers.policy import System1ValidationPolicy
from injester.semantic.verifiers.laya import LayaVerifier
from injester.semantic.verifiers.jev import JevVerifier
from injester.semantic.verifiers.openjev import OpenJevVerifier
from injester.semantic.verifiers.openai_compatible import OpenAICompatibleSystem1Verifier


def get_system1_verifier(
    provider: Optional[str] = None,
    policy: Optional[System1ValidationPolicy] = None,
    **kwargs
) -> System1Verifier:
    """
    Factory function resolving and returning the configured System1Verifier implementation.
    """
    effective_provider = (
        provider
        or getattr(settings, "SYSTEM1_PROVIDER", None)
        or "openjev"
    ).lower().strip()

    effective_policy = policy or System1ValidationPolicy(
        actor_threshold=getattr(settings, "SYSTEM1_POLICY_ACTOR_THRESHOLD", 0.50),
        action_threshold=getattr(settings, "SYSTEM1_POLICY_ACTION_THRESHOLD", 0.50),
        outcome_threshold=getattr(settings, "SYSTEM1_POLICY_OUTCOME_THRESHOLD", 0.40),
        uncertain_threshold=getattr(settings, "SYSTEM1_POLICY_UNCERTAIN_THRESHOLD", 0.35),
    )

    if effective_provider == "jev":
        return JevVerifier(
            api_key=kwargs.get("api_key", UNSET),
            model=kwargs.get("model", UNSET),
            base_url=kwargs.get("base_url", UNSET),
            policy=effective_policy,
        )
    elif effective_provider in ("openai", "openai_compatible"):
        return OpenAICompatibleSystem1Verifier(
            base_url=kwargs.get("base_url", UNSET),
            api_key=kwargs.get("api_key", UNSET),
            model=kwargs.get("model", UNSET),
            policy=effective_policy,
        )
    elif effective_provider == "openjev":
        return OpenJevVerifier(
            model_name=kwargs.get("model_name", "local-masked-logits"),
            device=kwargs.get("device"),
            policy=effective_policy,
        )
    elif effective_provider == "laya":
        return LayaVerifier(
            model_name=kwargs.get("model_name", "typed-decisions"),
            device=kwargs.get("device"),
            policy=effective_policy,
        )
    else:
        raise ValueError(
            f"Unsupported SYSTEM1_PROVIDER: '{effective_provider}'. "
            f"Must be one of ['jev', 'openai', 'laya', 'openjev']."
        )

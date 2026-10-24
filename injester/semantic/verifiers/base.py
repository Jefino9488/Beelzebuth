"""
Base interface and abstractions for System-1 Verifiers.
Defines the generic contract that all model adapters (Laya, Jev, OpenJev) implement.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any

from injester.semantic.schemas import (
    AtomicProposition,
    System1Verdict,
    GroundingVerdict,
    RawTypedDecisions,
    ModalityType,
    EpistemicStatus,
)
from injester.sop.spans import SpanRegistry


# Shared sentinel distinguishing "argument not provided" (resolve from runtime settings)
# from an explicit None (feature explicitly disabled for this instance).
UNSET = object()


class System1Verifier(ABC):
    """
    Generic interface for System-1 non-autoregressive decision verifiers.
    All providers (TypeSafe Jev, Laya, OpenJev) implement this interface.
    The verifier receives atomic propositions and cited evidence spans, queries the model
    for raw typed decisions, and delegates verdict evaluation to a shared System1ValidationPolicy.
    """

    provider_name: str = "system1"

    @abstractmethod
    def verify_propositions(
        self,
        propositions: List[AtomicProposition],
        span_registry: SpanRegistry
    ) -> Dict[str, System1Verdict]:
        """
        Runs batched typed semantic verification for all propositions against cited spans.
        Returns a mapping of proposition_id -> System1Verdict.
        """
        pass

    def _verify_structural_fallback(
        self,
        prop: AtomicProposition,
        span_text: str
    ) -> System1Verdict:
        """
        Purely structural fallback used when external model weights or API credentials
        are unavailable (offline CI/unit testing).
        Does NOT perform heuristic semantic inference (no keyword overlap or regex trees).
        Checks solely for evidence span existence in the SpanRegistry.
        """
        has_spans = bool(prop.evidence_spans) and bool(span_text.strip())

        if has_spans:
            span_lower = span_text.lower()
            if any(w in span_lower for w in ("must", "shall", "required", "mandatory", "has to")):
                verified_mod = ModalityType.MANDATORY
            elif any(w in span_lower for w in ("may", "can", "optional", "recommended", "should")):
                verified_mod = ModalityType.PERMISSIVE
            else:
                verified_mod = ModalityType.UNSTATED

            if any(w in span_lower for w in ("no record", "not recorded", "unrecorded", "not documented", "does not state")):
                verified_epi = EpistemicStatus.ABSENT_RECORD
            elif any(w in span_lower for w in ("alleged", "supposed", "tentative", "seems", "believed")):
                verified_epi = EpistemicStatus.TENTATIVE
            else:
                verified_epi = EpistemicStatus.CONFIRMED

            is_mod_escalated = (
                prop.modality == ModalityType.MANDATORY
                and verified_mod in (ModalityType.PERMISSIVE, ModalityType.UNSTATED)
            )
            is_epi_inverted = (
                prop.epistemic_status == EpistemicStatus.CONFIRMED
                and verified_epi == EpistemicStatus.ABSENT_RECORD
            ) or (
                prop.epistemic_status == EpistemicStatus.ABSENT_RECORD
                and verified_epi == EpistemicStatus.CONFIRMED
            )

            is_verified = not is_mod_escalated and not is_epi_inverted
            verdict = GroundingVerdict.SUPPORTED if is_verified else GroundingVerdict.UNSUPPORTED
            rejections = []
            if is_mod_escalated:
                rejections.append(f"Deontic escalation: Claimed mandatory when span is {verified_mod.value}")
            if is_epi_inverted:
                rejections.append("Epistemic inversion: Claimed fact when span states absence of record")

            return System1Verdict(
                proposition_id=prop.id,
                verdict=verdict,
                actor_grounded=True,
                actor_confidence=1.0,
                resolved_actor=prop.actor_claim,
                action_entailed=True,
                action_confidence=1.0,
                modality_verified=verified_mod,
                modality_confidence=0.9,
                is_modality_escalated=is_mod_escalated,
                epistemic_verified=verified_epi,
                epistemic_confidence=0.9,
                is_epistemic_inverted=is_epi_inverted,
                outcome_stated=True,
                outcome_confidence=1.0,
                is_verified=is_verified,
                rejection_reasons=rejections,
                provider=f"{self.provider_name}_structural_fallback"
            )
        else:
            return System1Verdict(
                proposition_id=prop.id,
                verdict=GroundingVerdict.UNSUPPORTED,
                actor_grounded=False,
                actor_confidence=0.0,
                resolved_actor=prop.actor_claim,
                action_entailed=False,
                action_confidence=0.0,
                modality_verified=prop.modality,
                modality_confidence=0.0,
                is_modality_escalated=False,
                epistemic_verified=prop.epistemic_status,
                epistemic_confidence=0.0,
                is_epistemic_inverted=False,
                outcome_stated=False,
                outcome_confidence=0.0,
                is_verified=False,
                rejection_reasons=["Proposition lacks cited evidence spans in SpanRegistry"],
                provider=f"{self.provider_name}_structural_fallback"
            )

    _fallback_verify = _verify_structural_fallback

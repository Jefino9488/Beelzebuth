"""
Shared System-1 Validation Policy.
Decouples threshold evaluation, categorical grounding verdicts (SUPPORTED, UNCERTAIN, UNSUPPORTED),
and rejection rationales from the underlying model adapters (Laya, Jev, OpenJev).
"""

from typing import List, Optional
from injester.semantic.schemas import (
    AtomicProposition,
    RawTypedDecisions,
    System1Verdict,
    GroundingVerdict,
    ModalityType,
    EpistemicStatus,
)


class System1ValidationPolicy:
    """
    Standardized, provider-agnostic validation policy layer.
    Interprets raw continuous probabilities and discrete choices returned by any System-1 provider
    according to configurable business and integrity thresholds.
    """

    def __init__(
        self,
        actor_threshold: float = 0.50,
        action_threshold: float = 0.50,
        outcome_threshold: float = 0.40,
        uncertain_threshold: float = 0.35,
    ):
        self.actor_threshold = actor_threshold
        self.action_threshold = action_threshold
        self.outcome_threshold = outcome_threshold
        self.uncertain_threshold = uncertain_threshold

    def evaluate(
        self,
        prop: AtomicProposition,
        raw: RawTypedDecisions,
        provider: str = "system1"
    ) -> System1Verdict:
        """
        Converts unthresholded raw typed decisions into an authoritative System1Verdict.
        """
        # 1. Actor Grounding
        actor_grounded = (raw.actor_p >= self.actor_threshold)

        # 2. Action Entailment
        action_entailed = (raw.action_p >= self.action_threshold)

        # 3. Modality Classification & Deontic Escalation
        mod_choice = (raw.modality_choice or "unstated").lower()
        verified_mod = (
            ModalityType(mod_choice)
            if mod_choice in ModalityType._value2member_map_
            else ModalityType.UNSTATED
        )
        is_modality_escalated = (
            prop.modality == ModalityType.MANDATORY
            and verified_mod in (ModalityType.PERMISSIVE, ModalityType.TYPICAL)
        )

        # 4. Epistemic Verification & Negative Record Inversion
        epi_choice = (raw.epistemic_choice or "confirmed").lower()
        verified_epi = (
            EpistemicStatus(epi_choice)
            if epi_choice in EpistemicStatus._value2member_map_
            else EpistemicStatus.CONFIRMED
        )
        is_epistemic_inverted = (
            prop.epistemic_status == EpistemicStatus.CONFIRMED
            and verified_epi == EpistemicStatus.ABSENT_RECORD
        ) or (
            prop.epistemic_status == EpistemicStatus.ABSENT_RECORD
            and verified_epi == EpistemicStatus.CONFIRMED
        )

        # 5. Decision Outcomes Grounding
        if prop.is_decision and raw.outcomes_p is not None:
            outcome_stated = (raw.outcomes_p >= self.outcome_threshold)
        else:
            outcome_stated = True

        # 6. Structured Rejection Rationales
        rejections: List[str] = []
        prov_label = provider.capitalize()
        if not actor_grounded:
            rejections.append(f"Actor '{prop.actor_claim}' not grounded in span evidence ({prov_label} p={raw.actor_p:.2f})")
        if not action_entailed:
            rejections.append(f"Action '{prop.action_verb} {prop.target_object}' not entailed by span ({prov_label} p={raw.action_p:.2f})")
        if is_modality_escalated:
            rejections.append(f"Deontic escalation: Claimed mandatory obligation when span evidence is {verified_mod.value}")
        if is_epistemic_inverted:
            rejections.append("Negative record inversion: Claimed confirmed fact when span states absence of record")
        if not outcome_stated and raw.outcomes_p is not None:
            rejections.append(f"Decision outcomes not stated in span ({prov_label} p={raw.outcomes_p:.2f})")

        # 7. Overall Verification Boolean
        is_verified = (
            actor_grounded
            and action_entailed
            and not is_modality_escalated
            and not is_epistemic_inverted
            and outcome_stated
        )

        # 8. Tri-State Categorical Grounding Verdict
        if is_verified:
            verdict = GroundingVerdict.SUPPORTED
        elif (
            (raw.actor_p >= self.uncertain_threshold or raw.action_p >= self.uncertain_threshold)
            and not is_epistemic_inverted
            and not is_modality_escalated
        ):
            verdict = GroundingVerdict.UNCERTAIN
        else:
            verdict = GroundingVerdict.UNSUPPORTED

        return System1Verdict(
            proposition_id=prop.id,
            verdict=verdict,
            actor_grounded=actor_grounded,
            actor_confidence=raw.actor_confidence,
            resolved_actor=prop.actor_claim,
            action_entailed=action_entailed,
            action_confidence=raw.action_confidence,
            modality_verified=verified_mod,
            modality_confidence=raw.modality_confidence,
            is_modality_escalated=is_modality_escalated,
            epistemic_verified=verified_epi,
            epistemic_confidence=raw.epistemic_confidence,
            is_epistemic_inverted=is_epistemic_inverted,
            outcome_stated=outcome_stated,
            outcome_confidence=raw.outcomes_confidence or 1.0,
            is_verified=is_verified,
            rejection_reasons=rejections,
            provider=provider
        )

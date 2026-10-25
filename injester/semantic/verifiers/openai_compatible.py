"""
OpenAI-Compatible System-1 Verifier Adapter (BYOAI).
Runs System-1 typed grounding verification against ANY OpenAI-compatible chat endpoint
(OpenRouter, Lightning AI, Ollama, vLLM, OpenAI, TypeSafe's OpenAI-compatible gateway).

This is the System-1 counterpart of the main LLM BYOAI contract: the developer supplies
a base URL, an API key, and a model name at runtime and the verifier re-points itself
without any source change. Raw typed decisions are handed to the shared
``System1ValidationPolicy`` so threshold semantics stay identical across providers.
"""

import os
from typing import Any, Dict, List, Literal, Optional

import instructor
from openai import OpenAI
from pydantic import BaseModel, Field

from injester.config import settings
from injester.semantic.schemas import (
    AtomicProposition,
    System1Verdict,
    RawTypedDecisions,
)
from injester.synthesis.spans import SpanRegistry
from injester.semantic.verifiers.base import System1Verifier, UNSET as _UNSET
from injester.semantic.verifiers.policy import System1ValidationPolicy

ModalityLabel = Literal["mandatory", "permissive", "typical", "unstated"]
EpistemicLabel = Literal["confirmed", "tentative", "unrecorded"]


class NoulDecision(BaseModel):
    """A Noul-style yes/no grounding probability with confidence."""
    probability: float = Field(ge=0.0, le=1.0, description="P(evidence supports the statement), 0.0 to 1.0")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Calibrated confidence in this probability")


class ModalityDecision(BaseModel):
    """A Choice-style deontic modality classification."""
    choice: ModalityLabel = Field(default="unstated", description="Obligation level stated by the evidence")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class EpistemicDecision(BaseModel):
    """A Choice-style epistemic status classification."""
    choice: EpistemicLabel = Field(default="confirmed", description="Epistemic status stated by the evidence")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class PropositionDecision(BaseModel):
    """System-1 typed decisions for a single atomic proposition."""
    proposition_id: str = Field(description="Identifier of the proposition this decision belongs to")
    actor_supported: NoulDecision = Field(description="Is the claimed actor explicitly present in the evidence?")
    action_entailed: NoulDecision = Field(description="Is the claimed action explicitly entailed by the evidence?")
    modality: ModalityDecision = Field(description="Obligation level expressed in the evidence")
    epistemic: EpistemicDecision = Field(description="Epistemic status expressed in the evidence")
    outcomes_supported: Optional[NoulDecision] = Field(
        default=None,
        description="Are the stated decision branch outcomes explicitly present in the evidence?"
    )


class DecisionBatch(BaseModel):
    """Container for a batch of System-1 typed decisions."""
    decisions: List[PropositionDecision] = Field(default_factory=list)


class OpenAICompatibleSystem1Verifier(System1Verifier):
    """
    System-1 Verifier backed by any OpenAI-compatible chat completion endpoint.

    Verifies all propositions of a run in a single batched structured-output call, then
    interprets the raw decisions through the shared System1ValidationPolicy.
    """

    provider_name: str = "openai"

    SYSTEM_PROMPT = (
        "You are a System-1 grounding verifier. You receive atomic procedural claims together "
        "with their verbatim evidence text and must decide, strictly from the evidence, whether "
        "each claim is grounded.\n"
        "You never infer information that is not present in the evidence.\n"
        "For every proposition return:\n"
        "1. actor_supported: probability that the evidence explicitly confirms the claimed actor performs the step.\n"
        "2. action_entailed: probability that the evidence explicitly confirms the claimed action takes place or is described.\n"
        "3. modality: the obligation level stated in the evidence "
        "('mandatory' for must/shall/required, 'permissive' for may/can/optional, "
        "'typical' for normally/typically/usually, 'unstated' for a neutral assertion).\n"
        "4. epistemic: the epistemic status stated in the evidence "
        "('confirmed' for established fact, 'tentative' for appears/seems/alleged, "
        "'unrecorded' for an explicit absence of record such as 'not recorded' or 'does not state').\n"
        "5. outcomes_supported: for decision points, the probability that the stated branch outcomes "
        "are explicitly present in the evidence.\n"
        "Return exactly one decision per proposition, using the proposition_id verbatim."
    )

    def __init__(
        self,
        base_url: Optional[str] = _UNSET,
        api_key: Optional[str] = _UNSET,
        model: Optional[str] = _UNSET,
        policy: Optional[System1ValidationPolicy] = None,
        timeout: float = 120.0,
        client: Any = None,
    ):
        self._explicit_base_url = base_url
        self._explicit_api_key = api_key
        self._explicit_model = model
        self.timeout = timeout
        self.policy = policy or System1ValidationPolicy()
        self.client = client
        self._client_fingerprint: Optional[tuple] = None
        self._init_client()

    # ------------------------------------------------------------------
    # Configuration resolution
    # ------------------------------------------------------------------
    def _resolve_config(self) -> Dict[str, Any]:
        """Resolves the effective endpoint configuration, honouring explicit overrides."""
        effective = settings.system1_effective_config()

        base_url = self._explicit_base_url
        if base_url is _UNSET:
            base_url = effective["base_url"]
        elif base_url is None:
            base_url = None

        api_key = self._explicit_api_key
        if api_key is _UNSET:
            api_key = effective["api_key"]
        elif api_key is None:
            api_key = None

        model = self._explicit_model
        if model is _UNSET:
            model = effective["model"]
        elif model is None:
            model = None

        return {
            "base_url": (base_url or "").strip() or None,
            "api_key": (api_key or "").strip() or None,
            "model": (model or "").strip() or None,
        }

    def _init_client(self) -> None:
        """Builds the instructor-wrapped OpenAI client for the resolved configuration."""
        config = self._resolve_config()
        self._client_fingerprint = (config["base_url"], config["api_key"], config["model"])

        if not config["base_url"]:
            self.client = None
            return

        raw_client = OpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"] or "byoai-token",
            timeout=self.timeout,
            max_retries=2,
        )
        self.client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)

    def _ensure_client_current(self) -> None:
        """Rebuilds the client when the runtime configuration has changed (hot-swap)."""
        config = self._resolve_config()
        fingerprint = (config["base_url"], config["api_key"], config["model"])
        if fingerprint == self._client_fingerprint and (self.client is not None or not config["base_url"]):
            return
        self._init_client()

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def verify_propositions(
        self,
        propositions: List[AtomicProposition],
        span_registry: SpanRegistry
    ) -> Dict[str, System1Verdict]:
        """
        Runs batched typed semantic verification for all propositions against cited spans.
        """
        verdicts: Dict[str, System1Verdict] = {}
        if not propositions:
            return verdicts

        self._ensure_client_current()
        config = self._resolve_config()

        prop_spans: Dict[str, str] = {}
        for prop in propositions:
            spans = [
                span_registry.get_span(sid)
                for sid in prop.evidence_spans
                if span_registry.get_span(sid)
            ]
            prop_spans[prop.id] = " ".join(s.text for s in spans) if spans else ""

        if self.client is not None:
            try:
                batch = self._evaluate_batch(propositions, prop_spans, config["model"])
                for prop in propositions:
                    decision = batch.decisions_map.get(prop.id)
                    if decision is not None:
                        verdicts[prop.id] = self._to_verdict(prop, decision, config["model"])
                    else:
                        verdicts[prop.id] = self._verify_structural_fallback(prop, prop_spans.get(prop.id, ""))
                return verdicts
            except Exception as e:
                if os.getenv("TESTING", "false").lower() not in ("true", "1"):
                    raise e

        for prop in propositions:
            verdicts[prop.id] = self._verify_structural_fallback(prop, prop_spans.get(prop.id, ""))

        return verdicts

    def _evaluate_batch(
        self,
        propositions: List[AtomicProposition],
        prop_spans: Dict[str, str],
        model: Optional[str],
    ) -> "_BatchResult":
        """Runs a single structured-output call covering every proposition in the run."""
        blocks: List[str] = []
        for prop in propositions:
            evidence = prop_spans.get(prop.id, "").strip() or "(no evidence text available)"
            outcomes = ", ".join(prop.potential_outcomes) if prop.potential_outcomes else "(not a decision point)"
            blocks.append(
                f"PROPOSITION {prop.id}\n"
                f"CLAIM ACTOR: {prop.actor_claim}\n"
                f"CLAIM ACTION: {prop.action_verb} {prop.target_object}\n"
                f"CLAIM CONDITION: {prop.condition or 'none'}\n"
                f"IS DECISION POINT: {'yes' if prop.is_decision else 'no'}\n"
                f"STATED OUTCOMES: {outcomes}\n"
                f"EVIDENCE: {evidence}"
            )

        user_prompt = "Verify each proposition against its evidence.\n\n" + "\n\n".join(blocks)

        batch: DecisionBatch = self.client.chat.completions.create(
            model=model or settings.MODEL_NAME,
            response_model=DecisionBatch,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )

        return _BatchResult(decisions_map={d.proposition_id: d for d in batch.decisions})

    def _to_verdict(
        self,
        prop: AtomicProposition,
        decision: PropositionDecision,
        model: Optional[str] = None,
    ) -> System1Verdict:
        """Translates a raw typed decision into the authoritative System1Verdict."""
        raw = RawTypedDecisions(
            actor_p=decision.actor_supported.probability,
            actor_confidence=decision.actor_supported.confidence,
            action_p=decision.action_entailed.probability,
            action_confidence=decision.action_entailed.confidence,
            modality_choice=decision.modality.choice,
            modality_confidence=decision.modality.confidence,
            epistemic_choice=decision.epistemic.choice,
            epistemic_confidence=decision.epistemic.confidence,
            outcomes_p=decision.outcomes_supported.probability if decision.outcomes_supported else None,
            outcomes_confidence=decision.outcomes_supported.confidence if decision.outcomes_supported else None,
            raw_metadata={
                "system1_mode": "openai_compatible",
                "model": model or settings.MODEL_NAME,
            },
        )
        return self.policy.evaluate(prop, raw, provider="openai")


class _BatchResult:
    """Internal carrier for the indexed decision batch."""

    def __init__(self, decisions_map: Dict[str, PropositionDecision]):
        self.decisions_map = decisions_map

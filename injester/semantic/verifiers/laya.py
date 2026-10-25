"""
Laya System-1 Verifier Adapter.
Integrates the official Laya non-autoregressive decision engine (convaiinnovations/laya)
to perform batched, typed semantic checks over atomic propositions and cited evidence spans.
Raw decision outputs are passed to the shared System1ValidationPolicy.
"""

import os
from typing import List, Dict, Optional, Any
import torch

from injester.semantic.schemas import (
    AtomicProposition,
    System1Verdict,
    RawTypedDecisions,
)
from injester.synthesis.spans import SpanRegistry
from injester.semantic.verifiers.base import System1Verifier
from injester.semantic.verifiers.policy import System1ValidationPolicy


class LayaVerifier(System1Verifier):
    """
    Sub-35ms Non-Autoregressive System-1 Verifier using official Laya checkpoints.
    Evaluates actor grounding, action entailment, modality classification,
    epistemic status, and outcome existence. Raw predictions are evaluated by System1ValidationPolicy.
    """

    provider_name: str = "laya"

    def __init__(
        self,
        model_name: str = "typed-decisions",
        device: Optional[str] = None,
        policy: Optional[System1ValidationPolicy] = None,
    ):
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.policy = policy or System1ValidationPolicy()
        self.router = None
        self._init_laya()

    def _init_laya(self):
        is_testing = os.getenv("TESTING", "false").lower() in ("true", "1")
        try:
            import laya
            from laya import Router
            self.router = Router(preload=False, device=self.device)
        except Exception as e:
            if not is_testing:
                raise RuntimeError(
                    f"CRITICAL: Failed to load Laya checkpoint '{self.model_name}' on device '{self.device}'. "
                    f"Production requires official Laya weights from convaiinnovations/laya. Details: {e}"
                )
            else:
                self.router = None

    def verify_propositions(
        self,
        propositions: List[AtomicProposition],
        span_registry: SpanRegistry
    ) -> Dict[str, System1Verdict]:
        """
        Runs batched typed semantic verification for all propositions against cited spans.
        Returns a dictionary mapping proposition_id -> System1Verdict.
        """
        verdicts: Dict[str, System1Verdict] = {}

        for prop in propositions:
            spans = [span_registry.get_span(sid) for sid in prop.evidence_spans if span_registry.get_span(sid)]
            span_text = " ".join(s.text for s in spans) if spans else ""

            if self.router is not None:
                try:
                    verdict = self._verify_single_with_laya(prop, span_text)
                    verdicts[prop.id] = verdict
                    continue
                except Exception as e:
                    if os.getenv("TESTING", "false").lower() not in ("true", "1"):
                        raise e

            # Pure structural-only fallback (for testing without Laya weights)
            verdict = self._verify_structural_fallback(prop, span_text)
            verdicts[prop.id] = verdict

        return verdicts

    def _verify_single_with_laya(self, prop: AtomicProposition, span_text: str) -> System1Verdict:
        """
        Queries Laya router and passes raw typed outputs to the shared System1ValidationPolicy.
        """
        state = {
            "claim": f"{prop.actor_claim} {prop.action_verb} {prop.target_object}",
            "evidence": span_text,
            "actor": prop.actor_claim,
            "action": f"{prop.action_verb} {prop.target_object}",
            "condition": prop.condition or "none"
        }

        questions = {
            "actor_supported": {
                "type": "noul",
                "instructions": f"Does the evidence text explicitly confirm that '{prop.actor_claim}' performs this step?"
            },
            "action_entailed": {
                "type": "noul",
                "instructions": f"Does the evidence text confirm that '{prop.action_verb} {prop.target_object}' takes place or is described?"
            },
            "modality": {
                "type": "choice",
                "instructions": "What level of obligation is stated in the evidence text?",
                "criteria": {
                    "mandatory": "strictly required, must, shall, mandatory, obligation",
                    "permissive": "discretionary, may, can, optional, permitted, allowed",
                    "typical": "normally, typically, usually, routine practice",
                    "unstated": "neutral assertion with no modal operator"
                }
            },
            "epistemic": {
                "type": "choice",
                "instructions": "What is the epistemic status in the evidence text?",
                "criteria": {
                    "confirmed": "confirmed factual event, verified, completed, happened",
                    "tentative": "uncertain, appears, seems, alleged, suspected",
                    "unrecorded": "explicit absence of record, not recorded, does not state whether, unverified"
                }
            }
        }

        if prop.is_decision and prop.potential_outcomes:
            questions["outcomes_supported"] = {
                "type": "noul",
                "instructions": f"Are these decision branch outcomes explicitly stated: {', '.join(prop.potential_outcomes)}?"
            }

        res = self.router.predict(state, questions)
        answers = res.get("answers", {})

        # 1. Actor Grounding
        act_ans = answers.get("actor_supported", {})
        act_p = float(act_ans.get("noul", 0.5)) if act_ans.get("type") == "noul" else 0.5
        act_conf = float(act_ans.get("confidence", act_p))

        # 2. Action Entailment
        actn_ans = answers.get("action_entailed", {})
        actn_p = float(actn_ans.get("noul", 0.5)) if actn_ans.get("type") == "noul" else 0.5
        actn_conf = float(actn_ans.get("confidence", actn_p))

        # 3. Modality
        mod_ans = answers.get("modality", {})
        mod_choice = mod_ans.get("choice", "unstated")
        mod_conf = float(mod_ans.get("confidence", 0.8))

        # 4. Epistemic
        epi_ans = answers.get("epistemic", {})
        epi_choice = epi_ans.get("choice", "confirmed")
        epi_conf = float(epi_ans.get("confidence", 0.8))

        # 5. Outcomes
        if prop.is_decision:
            out_ans = answers.get("outcomes_supported", {})
            out_p = float(out_ans.get("noul", 1.0)) if out_ans.get("type") == "noul" else 1.0
            out_conf = float(out_ans.get("confidence", out_p))
        else:
            out_p = None
            out_conf = None

        raw = RawTypedDecisions(
            actor_p=act_p,
            actor_confidence=act_conf,
            action_p=actn_p,
            action_confidence=actn_conf,
            modality_choice=mod_choice,
            modality_confidence=mod_conf,
            epistemic_choice=epi_choice,
            epistemic_confidence=epi_conf,
            outcomes_p=out_p,
            outcomes_confidence=out_conf,
            raw_metadata={"router_response": res}
        )

        return self.policy.evaluate(prop, raw, provider="laya")


# Compatibility alias
LayaSystem1Verifier = LayaVerifier

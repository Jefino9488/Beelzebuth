"""
TypeSafe Jev System-1 Verifier Adapter.
Integrates TypeSafe Jev (TypeSafe System One) via typesafe-sdk.
Sends atomic propositions and cited evidence spans as typed Noul/Choice queries
and returns raw decisions evaluated by the shared System1ValidationPolicy.

Follows the Bring Your Own API (BYOAI) contract: the endpoint, API key, and model
are resolved from the runtime settings at call time, so a developer can re-point the
System-1 verifier at a different TypeSafe deployment without touching source code.
"""

import os
from typing import Any, Dict, List, Optional

from injester.config import settings
from injester.semantic.schemas import (
    AtomicProposition,
    System1Verdict,
    RawTypedDecisions,
)
from injester.sop.spans import SpanRegistry
from injester.semantic.verifiers.base import System1Verifier, UNSET as _UNSET
from injester.semantic.verifiers.policy import System1ValidationPolicy


class JevVerifier(System1Verifier):
    """
    TypeSafe Jev System-1 Verifier using the official TypeSafe AI API.
    Evaluates propositions using calibrated Noul and Choice primitives.
    Raw decisions are interpreted by the shared System1ValidationPolicy.
    """

    provider_name: str = "jev"

    def __init__(
        self,
        api_key: Optional[str] = _UNSET,
        model: Optional[str] = _UNSET,
        base_url: Optional[str] = _UNSET,
        policy: Optional[System1ValidationPolicy] = None,
        timeout: float = 30.0,
        client: Any = None,
    ):
        self._explicit_api_key = api_key
        self._explicit_model = model
        self._explicit_base_url = base_url
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

        base_url = self._explicit_base_url
        if base_url is _UNSET:
            base_url = effective["base_url"]
        elif base_url is None:
            base_url = None

        return {
            "api_key": (api_key or "").strip() or None,
            "model": (model or "").strip() or None,
            "base_url": (base_url or "").strip() or None,
        }

    def _init_client(self) -> None:
        """Initializes the TypeSafe client when an API key is available."""
        config = self._resolve_config()
        self._client_fingerprint = (config["api_key"], config["base_url"])

        if not config["api_key"]:
            self.client = None
            return

        try:
            from typesafe_sdk import TypeSafeClient
            client_kwargs: Dict[str, Any] = {
                "api_key": config["api_key"],
                "timeout": self.timeout,
            }
            if config["base_url"]:
                client_kwargs["base_url"] = config["base_url"]
            if config["model"]:
                client_kwargs["model"] = config["model"]
            self.client = TypeSafeClient(**client_kwargs)
        except Exception as e:
            is_testing = os.getenv("TESTING", "false").lower() in ("true", "1")
            if not is_testing:
                raise RuntimeError(f"Failed to initialize TypeSafeClient for Jev: {e}")
            else:
                self.client = None

    def _ensure_client_current(self) -> None:
        """Rebuilds the client when the runtime configuration has changed (hot-swap)."""
        config = self._resolve_config()
        fingerprint = (config["api_key"], config["base_url"])
        if fingerprint == self._client_fingerprint and (self.client is not None or not config["api_key"]):
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
        Returns a dictionary mapping proposition_id -> System1Verdict.
        """
        verdicts: Dict[str, System1Verdict] = {}
        if not propositions:
            return verdicts

        self._ensure_client_current()
        config = self._resolve_config()

        for prop in propositions:
            spans = [span_registry.get_span(sid) for sid in prop.evidence_spans if span_registry.get_span(sid)]
            span_text = " ".join(s.text for s in spans) if spans else ""

            if self.client is not None:
                try:
                    verdict = self._verify_single_with_jev(prop, span_text, config["model"])
                    verdicts[prop.id] = verdict
                    continue
                except Exception as e:
                    if os.getenv("TESTING", "false").lower() not in ("true", "1"):
                        raise e

            # Pure structural-only fallback (for testing without live Jev credentials)
            verdict = self._verify_structural_fallback(prop, span_text)
            verdicts[prop.id] = verdict

        return verdicts

    def _verify_single_with_jev(self, prop: AtomicProposition, span_text: str, model: Optional[str] = None) -> System1Verdict:
        """
        Queries TypeSafe Jev via typesafe-sdk and passes raw typed outputs to System1ValidationPolicy.
        """
        from typesafe_sdk import Noul, Choice

        state = {
            "claim": f"{prop.actor_claim} {prop.action_verb} {prop.target_object}",
            "evidence": span_text,
            "actor": prop.actor_claim,
            "action": f"{prop.action_verb} {prop.target_object}",
            "condition": prop.condition or "none"
        }

        questions = {
            "actor_supported": Noul(
                instructions=f"Does the evidence text explicitly confirm that '{prop.actor_claim}' performs this step?"
            ),
            "action_entailed": Noul(
                instructions=f"Does the evidence text confirm that '{prop.action_verb} {prop.target_object}' takes place or is described?"
            ),
            "modality": Choice(
                instructions="What level of obligation is stated in the evidence text?",
                criteria={
                    "mandatory": "strictly required, must, shall, mandatory, obligation",
                    "permissive": "discretionary, may, can, optional, permitted, allowed",
                    "typical": "normally, typically, usually, routine practice",
                    "unstated": "neutral assertion with no modal operator"
                }
            ),
            "epistemic": Choice(
                instructions="What is the epistemic status in the evidence text?",
                criteria={
                    "confirmed": "confirmed factual event, verified, completed, happened",
                    "tentative": "uncertain, appears, seems, alleged, suspected",
                    "unrecorded": "explicit absence of record, not recorded, does not state whether, unverified"
                }
            )
        }

        if prop.is_decision and prop.potential_outcomes:
            questions["outcomes_supported"] = Noul(
                instructions=f"Are these decision branch outcomes explicitly stated: {', '.join(prop.potential_outcomes)}?"
            )

        res = self.client.system_one(state=state, questions=questions, model=model)

        # 1. Actor Grounding
        act_noul = res.nouls.get("actor_supported")
        act_p = float(act_noul.noul) if act_noul is not None else 0.5
        act_conf = float(getattr(act_noul, "confidence", act_p))

        # 2. Action Entailment
        actn_noul = res.nouls.get("action_entailed")
        actn_p = float(actn_noul.noul) if actn_noul is not None else 0.5
        actn_conf = float(getattr(actn_noul, "confidence", actn_p))

        # 3. Modality
        mod_choice_obj = res.choices.get("modality")
        mod_choice = mod_choice_obj.choice if mod_choice_obj is not None else "unstated"
        mod_conf = float(mod_choice_obj.confidence) if mod_choice_obj is not None else 0.8

        # 4. Epistemic
        epi_choice_obj = res.choices.get("epistemic")
        epi_choice = epi_choice_obj.choice if epi_choice_obj is not None else "confirmed"
        epi_conf = float(epi_choice_obj.confidence) if epi_choice_obj is not None else 0.8

        # 5. Outcomes
        if prop.is_decision:
            out_noul = res.nouls.get("outcomes_supported")
            out_p = float(out_noul.noul) if out_noul is not None else 1.0
            out_conf = float(getattr(out_noul, "confidence", out_p))
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
            raw_metadata={"jev_model": model or "jev-latest"}
        )

        return self.policy.evaluate(prop, raw, provider="jev")

"""
OpenJev Local Decision Verifier Adapter (AlexWortega/openjev).
Integrates the official openjev Qwen3.5 NLI model (AlexWortega/openjev) running locally on CUDA.
Evaluates atomic propositions against cited evidence spans using calibrated cross-encoder entailment.
Keeps raw continuous predictions separate from threshold policy logic.
"""

import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
from typing import List, Dict, Optional, Any, Tuple
import torch


from injester.semantic.schemas import (
    AtomicProposition,
    System1Verdict,
    RawTypedDecisions,
)
from injester.synthesis.spans import SpanRegistry
from injester.semantic.verifiers.base import System1Verifier
from injester.semantic.verifiers.policy import System1ValidationPolicy


class OpenJevVerifier(System1Verifier):
    """
    Local OpenJev System-1 Verifier based on AlexWortega/openjev (Qwen3.5 NLI cross-encoder).
    Runs directly on local GPU (e.g. NVIDIA RTX 5050) without external API dependencies.
    Computes calibrated entailment probabilities for actor grounding and action entailment.
    """

    provider_name: str = "openjev"

    def __init__(
        self,
        model_id: str = "AlexWortega/openjev",
        subfolder: str = "qwen3.5-0.8b-nli-v2s-long",
        device: Optional[str] = None,
        policy: Optional[System1ValidationPolicy] = None,
        load_model: bool = True,
        **kwargs
    ):
        self.model_id = model_id
        self.subfolder = subfolder
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.policy = policy or System1ValidationPolicy()
        self.model = None
        self.tokenizer = None
        self._model_loaded = not load_model


    def _ensure_model_loaded(self):
        """Lazily load the NLI model on first use to avoid VRAM contention during LLM steps."""
        if self._model_loaded:
            return
        self._model_loaded = True
        is_testing = os.getenv("TESTING", "false").lower() in ("true", "1")
        if self.device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                subfolder=self.subfolder,
                local_files_only=False
            )
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_id,
                subfolder=self.subfolder,
                local_files_only=False,
                dtype=torch.bfloat16 if self.device == "cuda" else torch.float32
            ).to(self.device)
            self.model.eval()
        except Exception as e:
            if not is_testing:
                raise RuntimeError(
                    f"Failed to load OpenJev model '{self.model_id}' ({self.subfolder}) on {self.device}: {e}"
                )
            self.model = None
            self.tokenizer = None

    def unload_model(self):
        """Frees model and tokenizer from VRAM to avoid GPU contention with Ollama."""
        if self.model is not None:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
            self._model_loaded = False
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def verify_propositions(
        self,
        propositions: List[AtomicProposition],
        span_registry: SpanRegistry
    ) -> Dict[str, System1Verdict]:
        """
        Runs batched OpenJev semantic verification for all propositions against cited spans.
        """
        verdicts: Dict[str, System1Verdict] = {}
        if not propositions:
            return verdicts

        # Ensure model is lazily loaded
        self._ensure_model_loaded()

        # Prepare evidence texts
        prop_spans: Dict[str, str] = {}
        for p in propositions:
            spans = [span_registry.get_span(sid) for sid in p.evidence_spans if span_registry.get_span(sid)]
            prop_spans[p.id] = " ".join(s.text for s in spans) if spans else ""

        # If live local OpenJev model is available on GPU, run batched cross-encoder inference
        if self.model is not None and self.tokenizer is not None:
            try:
                raw_dict = self._evaluate_batch_nli(propositions, prop_spans)
                for p in propositions:
                    raw = raw_dict.get(p.id)
                    if raw:
                        verdicts[p.id] = self.policy.evaluate(p, raw, provider="openjev")
                    else:
                        verdicts[p.id] = self._verify_structural_fallback(p, prop_spans.get(p.id, ""))
                # Free VRAM immediately so Reasoner has full GPU memory
                self.unload_model()
                return verdicts
            except Exception as e:
                if os.getenv("TESTING", "false").lower() not in ("true", "1"):
                    raise e


        # Fallback for testing mode when model is uninitialized
        for p in propositions:
            verdicts[p.id] = self._verify_structural_fallback(p, prop_spans.get(p.id, ""))

        return verdicts

    def _evaluate_batch_nli(
        self,
        propositions: List[AtomicProposition],
        prop_spans: Dict[str, str]
    ) -> Dict[str, RawTypedDecisions]:
        """
        Batches pairs of (Premise: span, Hypothesis: claim) through AlexWortega/openjev.
        Output label 1 corresponds to 'entailment' in Qwen3.5 NLI.
        """
        results: Dict[str, RawTypedDecisions] = {}
        pairs_actor: List[Tuple[str, str]] = []
        pairs_action: List[Tuple[str, str]] = []

        for p in propositions:
            evidence = prop_spans.get(p.id, "").strip() or "No evidence provided."
            # Actor hypothesis (skip unassigned or system actions)
            if not p.actor_claim or p.actor_claim.lower() in ("system", "none", "unassigned", ""):
                h_actor = ""
            else:
                h_actor = f"The actor performing this action is {p.actor_claim}."
            pairs_actor.append((evidence, h_actor))

            # Action hypothesis
            if p.actor_claim and p.actor_claim.lower() not in ("system", "none", "unassigned", ""):
                h_action = f"{p.actor_claim} {p.action_verb} {p.target_object}."
            else:
                h_action = f"{p.action_verb} {p.target_object}."
            pairs_action.append((evidence, h_action))

        # Batch inference for actor grounding
        actor_probs = self._predict_entailment_probs(pairs_actor)
        # Batch inference for action entailment
        action_probs = self._predict_entailment_probs(pairs_action)

        for i, p in enumerate(propositions):
            if not p.actor_claim or p.actor_claim.lower() in ("system", "none", "unassigned", ""):
                act_p = 1.0
            else:
                act_p = actor_probs[i]
            actn_p = action_probs[i]


            evidence_lower = prop_spans.get(p.id, "").lower()
            if any(w in evidence_lower for w in ("must", "shall", "required", "mandatory", "has to")):
                mod_choice = "mandatory"
            elif any(w in evidence_lower for w in ("may", "can", "optional", "recommended", "should")):
                mod_choice = "permissive"
            else:
                mod_choice = "unstated"

            if any(w in evidence_lower for w in ("no record", "not recorded", "unrecorded", "not documented", "does not state")):
                epi_choice = "unrecorded"
            elif any(w in evidence_lower for w in ("alleged", "supposed", "tentative", "seems", "believed")):
                epi_choice = "tentative"
            else:
                epi_choice = "confirmed"

            results[p.id] = RawTypedDecisions(
                actor_p=act_p,
                actor_confidence=act_p if act_p > 0.5 else 1.0 - act_p,
                action_p=actn_p,
                action_confidence=actn_p if actn_p > 0.5 else 1.0 - actn_p,
                modality_choice=mod_choice,
                modality_confidence=0.85,
                epistemic_choice=epi_choice,
                epistemic_confidence=0.85,
                outcomes_p=1.0 if p.is_decision else None,
                outcomes_confidence=1.0 if p.is_decision else None,
                raw_metadata={"openjev_model": f"{self.model_id}/{self.subfolder}", "device": self.device}
            )

        return results

    def _predict_entailment_probs(self, pairs: List[Tuple[str, str]], batch_size: int = 4) -> List[float]:
        """
        Computes P(entailment) across a list of (premise, hypothesis) pairs in mini-batches.
        Label 1 = 'entailment', Label 0 = 'contradiction', Label 2 = 'neutral'.
        """
        if not pairs:
            return []

        if self.device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()

        entailment_probs: List[float] = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            premises = [p[0] for p in batch]
            hypotheses = [p[1] for p in batch]

            inputs = self.tokenizer(
                premises,
                hypotheses,
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt"
            ).to(self.device)

            with torch.inference_mode():
                logits = self.model(**inputs).logits
                probs = torch.softmax(logits, dim=-1)

            # Label 1 is entailment
            entailment_probs.extend(probs[:, 1].float().tolist())

        return [float(p) for p in entailment_probs]

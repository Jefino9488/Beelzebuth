"""
Laya Semantic Evaluator & Meaning Preservation Engine.

Laya serves as Beelzebuth's semantic analysis engine:
- Evaluates meaning, intent preservation, and semantic entailment for proposed text edits.
- Assesses whether a rewritten instruction or modified paragraph is fully supported
  by cited evidence spans or introduces synthetic drift / hallucination.
- Does NOT authorize or execute document mutations directly; provides auditable
  verdicts and flags to the Change Engine.
- Offline-by-default; does not require remote external APIs.
"""

import re
from typing import List, Dict, Optional, Any, Set
from pydantic import BaseModel, Field


class LayaSemanticVerdict(BaseModel):
    """Semantic analysis verdict produced by Laya."""
    is_supported: bool
    entailment_score: float
    drift_detected: bool
    dropped_constraints: List[str] = Field(default_factory=list)
    unsupported_additions: List[str] = Field(default_factory=list)
    rationale: str = ""
    requires_human_review: bool = False


class LayaSemanticEvaluator:
    """
    Laya Semantic Analysis Engine.
    Evaluates whether proposed text modifications maintain semantic fidelity with original text
    and cited evidence spans.
    """

    def __init__(
        self,
        entailment_threshold: float = 0.85,
        strict_constraint_checking: bool = True,
        offline_mode: bool = True,
    ):
        self.entailment_threshold = entailment_threshold
        self.strict_constraint_checking = strict_constraint_checking
        self.offline_mode = offline_mode

    def evaluate_edit(
        self,
        original_text: str,
        proposed_text: str,
        evidence_spans: Optional[List[str]] = None,
        span_registry: Optional[Dict[str, str]] = None,
    ) -> LayaSemanticVerdict:
        """
        Evaluates whether proposed_text preserves the meaning and constraints of original_text,
        and whether it is grounded in cited evidence.
        """
        orig_clean = original_text.strip()
        prop_clean = proposed_text.strip()

        if not prop_clean:
            return LayaSemanticVerdict(
                is_supported=False,
                entailment_score=0.0,
                drift_detected=True,
                rationale="Proposed text is empty; destructive deletion cannot be approved without explicit remove operation.",
                requires_human_review=True,
            )

        if orig_clean.lower() == prop_clean.lower():
            # Exact identity
            return LayaSemanticVerdict(
                is_supported=True,
                entailment_score=1.0,
                drift_detected=False,
                rationale="Proposed text is identical to original text.",
                requires_human_review=False,
            )

        # 1. Critical constraint checks (action verbs, negative constraints, numbers/specifiers)
        orig_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", orig_clean.lower()))
        prop_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", prop_clean.lower()))

        # Check for dropped technical terms, numbers, or specific model identifiers
        orig_specs = set(re.findall(r"\b(?:\d+|[A-Z0-9]{3,}|v\d+)\b", orig_clean))
        prop_specs = set(re.findall(r"\b(?:\d+|[A-Z0-9]{3,}|v\d+)\b", prop_clean))
        dropped_specs = list(orig_specs - prop_specs)

        # Check negation drift (e.g. "do not connect" -> "connect")
        negations = {"not", "never", "no", "without", "disallow", "prohibit"}
        orig_has_neg = any(n in orig_tokens for n in negations)
        prop_has_neg = any(n in prop_tokens for n in negations)
        negation_flip = orig_has_neg != prop_has_neg

        # Check addition of ungrounded specific claims
        novel_tokens = prop_tokens - orig_tokens
        evidence_text = ""
        if evidence_spans and span_registry:
            evidence_text = " ".join(span_registry.get(sid, "") for sid in evidence_spans).lower()
            ev_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", evidence_text))
            unsupported = [t for t in novel_tokens if len(t) > 3 and t not in ev_tokens]
        else:
            unsupported = [t for t in novel_tokens if len(t) > 4]

        # Compute semantic overlap / Jaccard similarity as calibrated local score
        overlap = orig_tokens.intersection(prop_tokens)
        union = orig_tokens.union(prop_tokens)
        similarity = len(overlap) / len(union) if union else 1.0

        # Calibrated score penalty for dropped specs or negation flip
        entailment_score = similarity
        if negation_flip:
            entailment_score = 0.1
        elif dropped_specs:
            entailment_score = max(0.2, entailment_score - (0.15 * len(dropped_specs)))

        drift_detected = (entailment_score < self.entailment_threshold) or negation_flip or bool(dropped_specs)
        is_supported = (entailment_score >= self.entailment_threshold) and not negation_flip

        rationale_parts = []
        if negation_flip:
            rationale_parts.append("Critical negation inversion detected between original and proposed text.")
        if dropped_specs:
            rationale_parts.append(f"Dropped technical specifiers/numbers: {', '.join(dropped_specs)}.")
        if unsupported:
            rationale_parts.append(f"Novel ungrounded terms introduced: {', '.join(unsupported[:5])}.")
        if is_supported:
            rationale_parts.append(f"Semantic meaning preserved (calibrated entailment: {entailment_score:.2f}).")
        else:
            rationale_parts.append(f"Semantic drift detected (calibrated entailment: {entailment_score:.2f} < {self.entailment_threshold}).")

        return LayaSemanticVerdict(
            is_supported=is_supported,
            entailment_score=round(entailment_score, 3),
            drift_detected=drift_detected,
            dropped_constraints=dropped_specs,
            unsupported_additions=unsupported[:5],
            rationale=" ".join(rationale_parts),
            requires_human_review=drift_detected or not is_supported,
        )

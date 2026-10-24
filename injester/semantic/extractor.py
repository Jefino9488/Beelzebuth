"""
Atomic Proposition Extractor for the Evidence-First Pipeline.
Extracts fine-grained, grounded semantic propositions from granular [S###] spans
without forcing complete macro-graph interpretation in the LLM.
"""

import time
from typing import List, Optional
from openai import OpenAI
import instructor

from injester.config import settings
from injester.infrastructure.heartbeat import HeartbeatLogger
from injester.sop.spans import SpanRegistry
from injester.semantic.schemas import PropositionBatch, AtomicProposition


class AtomicPropositionExtractor:
    """
    Extracts flat atomic semantic proposition tuples from source evidence spans
    using a strong LLM in a single pass.
    """

    SYSTEM_PROMPT = (
        "You are an expert procedural semanticist. Your task is to extract atomic procedural propositions "
        "from the provided document evidence.\n"
        "CRITICAL EVIDENCE & RESTRAINT INSTRUCTIONS:\n"
        "1. Do NOT construct a workflow graph, diagram, or sequence of nodes.\n"
        "2. Extract atomic assertions as discrete facts: actor_claim, action_verb, target_object, condition, "
        "   modality (mandatory/permissive/typical/unstated), epistemic_status (confirmed/tentative/unrecorded), "
        "   and potential_outcomes if the statement is a decision point.\n"
        "3. Every proposition MUST cite exact Span IDs [S###] from the evidence text.\n"
        "4. Actor Grounding: Use the exact individual name or role title as stated in the evidence span "
        "   (e.g., 'Raj', 'AP', 'Finance Manager'). For automated system actions, use 'System'. Do NOT replace individual "
        "   names with inferred departments.\n"
        "5. Modality Grounding: Set modality strictly based on the span:\n"
        "   - 'mandatory' ONLY if the span uses obligatory language ('must', 'shall', 'required').\n"
        "   - 'permissive' if the span indicates discretion or option ('may', 'can', 'optional').\n"
        "   - 'typical' if the span notes routine or customary practice ('normally', 'typically', 'usually').\n"
        "   - 'unstated' if neutral.\n"
        "6. Epistemic Status Grounding:\n"
        "   - 'confirmed' if stated as an established fact.\n"
        "   - 'tentative' if stated with uncertainty ('appears', 'seems', 'alleged').\n"
        "   - 'unrecorded' if the text explicitly states absence of record ('not recorded', 'does not state', 'unverified').\n"
        "7. Temporal Connectives: Identify explicit connective text ('then', 'after', 'subsequently', 'if', 'retry'). "
        "   If no causal connective is stated, set connective to 'unspecified'. Do NOT extrapolate unstated order."
    )

    def __init__(self, client: Optional[instructor.Instructor] = None, model_name: Optional[str] = None):
        if client is not None:
            self.client = client
        else:
            raw_client = OpenAI(
                base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL else None,
                api_key=settings.OPENAI_API_KEY if settings.OPENAI_API_KEY else "byoai-token",
                timeout=getattr(settings, "LLM_TIMEOUT", 600.0),
                max_retries=2,
            )
            self.client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
        self.model_name = model_name or settings.MODEL_NAME

    def extract_propositions(self, span_registry: SpanRegistry, chunks: List[Any] = None) -> PropositionBatch:
        """
        Extracts all atomic propositions from the span registry.
        """
        if chunks:
            chunk_reprs = [span_registry.format_chunk_with_spans(c) for c in chunks]
            evidence_text = "\n\n".join(chunk_reprs)
        else:
            evidence_text = "\n".join(
                f"[{s.span_id}] {s.text}" for s in span_registry.spans_by_id.values()
            )

        user_prompt = (
            f"DOCUMENT EVIDENCE WITH GRANULAR SPANS:\n\n"
            f"{evidence_text}\n\n"
            f"Extract all atomic procedural propositions in order across all sections. "
            f"Be comprehensive: capture every single procedural action, decision, notification, escalation, and outcome."
        )

        import time
        t0 = time.time()
        batch: Optional[PropositionBatch] = None
        for attempt in range(4):
            try:
                detail = f"~{len(user_prompt)} chars / ~{len(user_prompt)//4} tokens | attempt {attempt+1}/4"
                with HeartbeatLogger(
                    stage="EXTRACTOR",
                    model_name=self.model_name,
                    detail=detail,
                    interval=6.0,
                    provider=settings.OPENAI_BASE_URL or "",
                ):
                    batch = self.client.chat.completions.create(
                        model=self.model_name,
                        response_model=PropositionBatch,
                        max_retries=1,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.0
                    )
                break
            except Exception as e:
                if ("429" in str(e) or "rate" in str(e).lower()) and attempt < 3:
                    wait_time = (attempt + 1) * 5
                    print(f"  [EXTRACTOR {time.strftime('%H:%M:%S')}] Rate limited (attempt {attempt+1}/4). Retrying in {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                else:
                    raise

        if batch is None:
            raise RuntimeError("Failed to extract proposition batch.")

        print(f"  [EXTRACTOR {time.strftime('%H:%M:%S')}] ✅ LLM returned {len(batch.propositions)} propositions in {time.time()-t0:.2f}s", flush=True)

        # Normalize order indices if needed
        for idx, prop in enumerate(batch.propositions):
            if prop.order_index == 0:
                prop.order_index = idx

        return batch

import re
from typing import List, Dict, Set, Optional, Union, NamedTuple
from pydantic import BaseModel, Field
from injester.ingestion.schema import DocumentChunk
from injester.sop.schemas import SOPDocument, SOPSection, CitationRef, ClaimCitation, SOPClaim
from injester.sop.spans import SpanRegistry, SourceSpan
from injester.sop.knowledge_map import extract_knowledge_map, DocumentKnowledgeMap, ExpectedRule

class EntailmentVerdict(NamedTuple):
    is_entailed: bool
    confidence: float = 1.0
    provider: str = "deterministic"
    model: Optional[str] = None

    def __bool__(self):
        return bool(self.is_entailed)

class ValidationReport(BaseModel):
    is_valid: bool = Field(description="True if there are zero critical errors")
    chunk_coverage_score: float = Field(default=1.0, description="% of eligible source chunks represented in citations")
    rule_coverage_score: float = Field(default=1.0, description="% of source rules and thresholds represented in the SOP")
    claim_entailment_score: float = Field(default=1.0, description="% of citations with verified factual entailment")
    citation_correctness_score: float = Field(default=1.0, description="% of citations properly formed and mapped to valid spans")
    unsupported_claims_count: int = Field(default=0, description="Number of procedural/rule claims lacking valid citations")
    unsupported_claims: List[str] = Field(default_factory=list, description="Verbatim list of ungrounded or unentailed claims")
    unrepresented_rules: List[str] = Field(default_factory=list, description="Expected source rules missing from the SOP")
    errors: List[str] = Field(default_factory=list, description="Critical citation or provenance failures")
    warnings: List[str] = Field(default_factory=list, description="Non-critical warnings")
    verified_citation_index: Dict[str, CitationRef] = Field(default_factory=dict)

class CitationValidator:
    """
    Independent, deterministic verification engine.
    Audits claim-to-span entailment, resolves span IDs against immutable source text,
    verifies source-rule coverage, and detects unsupported procedural expansions.
    """
    CITATION_REGEX = re.compile(r'\[(S\d{3,4}|C\d+(?:\.\d+)?)\]')

    def __init__(self, nli_verifier: Optional[Any] = None):
        self.nli_verifier = nli_verifier
        self._nli_initialized = False

    def _get_nli(self) -> Optional[Any]:
        if self.nli_verifier is not None:
            return self.nli_verifier
        if not self._nli_initialized:
            self._nli_initialized = True
            try:
                from injester.semantic.verifiers.openjev import OpenJevVerifier
                verifier = OpenJevVerifier(load_model=True)
                verifier._ensure_model_loaded()
                if verifier.model is not None:
                    self.nli_verifier = verifier
            except Exception:
                self.nli_verifier = None
        return self.nli_verifier

    def validate_document(
        self,
        sop_doc: SOPDocument,
        available_chunks: List[DocumentChunk],
        knowledge_map: Optional[DocumentKnowledgeMap] = None
    ) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []
        unsupported_claims: List[str] = []
        master_citation_index: Dict[str, CitationRef] = {}

        # 1. Deterministic Span Registry from chunks
        span_registry = SpanRegistry.from_chunks(available_chunks)
        chunk_lookup: Dict[str, DocumentChunk] = {c.chunk_id: c for c in available_chunks}

        # 2. Audit Citations per Section
        for section in sop_doc.sections:
            tags_in_text: Set[str] = set(self.CITATION_REGEX.findall(section.content))
            section_citations_by_tag: Dict[str, Union[ClaimCitation, CitationRef]] = {}

            # First, resolve any explicit structured citations in section (legacy or structured)
            for cit in section.citations:
                tag = cit.citation_tag
                section_citations_by_tag[tag] = cit

                if cit.chunk_id not in chunk_lookup:
                    errors.append(
                        f"Section '{section.section_title}': Citation [{tag}] references non-existent chunk ID '{cit.chunk_id}' (hallucinated reference)."
                    )
                    continue

                actual_chunk = chunk_lookup[cit.chunk_id]
                span_id = getattr(cit, 'span_id', '')

                if span_id:
                    span = span_registry.get_span(span_id)
                    if not span:
                        errors.append(
                            f"Section '{section.section_title}': Citation [{tag}] references non-existent span ID '{span_id}'."
                        )
                        continue
                    if span.chunk_id != cit.chunk_id:
                        errors.append(
                            f"Section '{section.section_title}': Citation [{tag}] chunk_id '{cit.chunk_id}' does not match span chunk '{span.chunk_id}'."
                        )
                        continue
                    evidence_text = span.text
                    loc = span.location
                    sec_path = span.section
                else:
                    evidence_text = getattr(cit, 'evidence_quote', '') or actual_chunk.text[:200]
                    loc = getattr(cit, 'location', '') or actual_chunk.provenance.source_location
                    sec_path = getattr(cit, 'section', '') or (" > ".join(actual_chunk.section_hierarchy) if actual_chunk.section_hierarchy else "")
                    chunk_spans = span_registry.get_chunk_spans(cit.chunk_id)
                    span_id = chunk_spans[0].span_id if chunk_spans else "S000"

                ref = CitationRef(
                    citation_tag=tag,
                    chunk_id=cit.chunk_id,
                    span_id=span_id,
                    source_doc=actual_chunk.filename,
                    location=loc,
                    section=sec_path,
                    evidence_quote=evidence_text,
                    entailment_status="entailed",
                )
                master_citation_index[tag] = ref

            # Directly resolve immutable [S###] tags from text
            for tag in tags_in_text:
                if tag.startswith("S") and tag[1:].isdigit():
                    span = span_registry.get_span(tag)
                    if span:
                        ref = CitationRef(
                            citation_tag=tag,
                            chunk_id=span.chunk_id,
                            span_id=span.span_id,
                            source_doc=span.source_doc,
                            location=span.location,
                            section=span.section,
                            evidence_quote=span.text,
                            entailment_status="entailed",
                        )
                        master_citation_index[tag] = ref
                        section_citations_by_tag[tag] = ref
                    else:
                        errors.append(
                            f"Section '{section.section_title}': Citation tag [{tag}] used in text references non-existent span ID."
                        )
                elif tag not in section_citations_by_tag and tag not in master_citation_index:
                    errors.append(
                        f"Section '{section.section_title}': Citation tag [{tag}] used in text has no accompanying metadata."
                    )

            # 3. Typed Claims Grounding & Entailment Audit
            for claim in section.claims:
                ctype = claim.claim_type
                requires_citation = ctype in ["rule", "threshold", "exception", "sla", "role", "procedure"]

                target_span_id = claim.span_id or (getattr(claim.citation, 'span_id', '') if claim.citation else '')
                if not target_span_id:
                    # Check for [S###] in claim text
                    m = re.search(r'\[(S\d{3,4})\]', claim.claim_text)
                    if m:
                        target_span_id = m.group(1)
                    elif claim.citation:
                        target_span_id = claim.citation.citation_tag

                if target_span_id:
                    span = span_registry.get_span(target_span_id)
                    if not span and target_span_id in master_citation_index:
                        span = span_registry.get_span(master_citation_index[target_span_id].span_id)
                    if span:
                        is_entailed = self._verify_entailment(claim.claim_text, span.text)
                        if is_entailed:
                            master_citation_index[span.span_id] = CitationRef(
                                citation_tag=span.span_id,
                                chunk_id=span.chunk_id,
                                span_id=span.span_id,
                                source_doc=span.source_doc,
                                location=span.location,
                                section=span.section,
                                evidence_quote=span.text,
                                entailment_status="entailed",
                            )
                        else:
                            unsupported_claims.append(f"[UNENTAILED] {claim.claim_text} (cited: {span.text[:60]})")
                            warnings.append(
                                f"Section '{section.section_title}': Claim '{claim.claim_text[:60]}' not entailed by span [{span.span_id}]."
                            )
                    else:
                        errors.append(
                            f"Section '{section.section_title}': Claim references non-existent span ID '{target_span_id}'."
                        )
                elif requires_citation:
                    # If procedural/rule claim lacks explicit span_id, check if section has valid spans
                    if not tags_in_text:
                        unsupported_claims.append(f"[{ctype.upper()}] {claim.claim_text}")
                        warnings.append(
                            f"Section '{section.section_title}': {ctype.capitalize()} claim '{claim.claim_text[:60]}' lacks supporting citation."
                        )
                    else:
                        # Check if any tag in section entails the claim
                        entailed = any(
                            self._verify_entailment(claim.claim_text, span_registry.get_span(t).text)
                            for t in tags_in_text if span_registry.get_span(t)
                        )
                        if not entailed:
                            unsupported_claims.append(f"[{ctype.upper()}] {claim.claim_text}")

        # 4. Independent Source Coverage Evaluation
        kmap = knowledge_map if knowledge_map is not None else extract_knowledge_map(available_chunks, span_registry)
        all_expected_rules: List[ExpectedRule] = kmap.core_rules + kmap.exception_rules + kmap.sla_rules
        unrepresented_rules: List[str] = []

        sop_full_text = " ".join(s.content for s in sop_doc.sections).lower()
        for rule in all_expected_rules:
            # Check key terms in SOP text
            if rule.key_terms:
                matched_terms = [t for t in rule.key_terms if t.lower() in sop_full_text]
                if not matched_terms:
                    unrepresented_rules.append(f"[{rule.category.upper()}] {rule.description}")
            else:
                # Fallback: check if significant words appear
                words = [w for w in re.findall(r'\b\w{4,}\b', rule.description.lower())]
                matched = [w for w in words if w in sop_full_text]
                if words and (len(matched) / len(words)) < 0.4:
                    unrepresented_rules.append(f"[{rule.category.upper()}] {rule.description}")

        # Metrics calculation
        eligible_chunk_ids = set(kmap.eligible_chunk_ids)
        cited_chunk_ids = set(c.chunk_id for c in master_citation_index.values())
        represented_chunks = eligible_chunk_ids & cited_chunk_ids
        chunk_coverage = len(represented_chunks) / max(len(eligible_chunk_ids), 1) if eligible_chunk_ids else 1.0

        rule_coverage = (len(all_expected_rules) - len(unrepresented_rules)) / max(len(all_expected_rules), 1) if all_expected_rules else 1.0

        total_claims_checked = sum(len(s.claims) for s in sop_doc.sections)
        if total_claims_checked > 0:
            claim_entailment_score = max(0.0, (total_claims_checked - len(unsupported_claims)) / total_claims_checked)
        else:
            claim_entailment_score = 1.0

        total_citations = max(len(master_citation_index) + len(errors), 1)
        citation_correctness = 1.0 if not errors else max(0.0, 1.0 - (len(errors) / total_citations))

        # Primary acceptance criteria
        is_valid = (len(errors) == 0) and (len(unsupported_claims) == 0)

        sop_doc.citation_index = master_citation_index

        return ValidationReport(
            is_valid=is_valid,
            chunk_coverage_score=round(chunk_coverage, 3),
            rule_coverage_score=round(rule_coverage, 3),
            claim_entailment_score=round(claim_entailment_score, 3),
            citation_correctness_score=round(citation_correctness, 3),
            unsupported_claims_count=len(unsupported_claims),
            unsupported_claims=unsupported_claims,
            unrepresented_rules=unrepresented_rules,
            errors=errors,
            warnings=warnings,
            verified_citation_index=master_citation_index,
        )

    def _verify_entailment(self, claim_text: str, span_text: str) -> EntailmentVerdict:
        """
        Deterministic & NLI entailment verification.
        Verifies numerical consistency, currency/threshold fidelity, and entity alignment.
        """
        claim_lower = claim_text.lower()
        span_lower = span_text.lower()

        # Clean non-factual artifacts from claim (e.g. inline [S014], [C1] citation tags, and leading step numbering)
        clean_claim = re.sub(r'\[(?:s\d{3,4}|c\d+(?:\.\d+)?)\]', '', claim_lower)
        clean_claim = re.sub(r'^(?:step\s+\d+|decision\s+\d+|\d+\.)\s*', '', clean_claim).strip()

        # 1. Number & Currency Verification: any substantive business number in claim must be present in span with token boundary
        span_normalized = span_lower.replace(',', '')
        claim_numbers = re.findall(r'[\$€£]?\b\d+(?:,\d+)*(?:\.\d+)?%?', clean_claim)
        for num in claim_numbers:
            num_clean = re.sub(r'[\$€£,%]', '', num)
            pattern = r'\b' + re.escape(num_clean) + r'\b'
            if not re.search(pattern, span_normalized):
                return EntailmentVerdict(is_entailed=False, confidence=0.0, provider="number_rule")

        # 2. Condition Phrase Verification: if claim introduces a condition/prerequisite (after, upon, etc.),
        # the condition's key content words must be anchored in the span.
        cond_matches = re.findall(r'\b(?:after|upon|provided that|subject to|conditioned on|pending)\s+([a-zA-Z0-9\s,\$]{4,50})', clean_claim)
        for cond_phrase in cond_matches:
            cond_words = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', cond_phrase) if w not in {'that', 'this', 'with', 'from', 'have', 'been', 'their'}]
            if cond_words:
                def _stem_simple(w: str) -> str:
                    for suffix in ['ies', 'ing', 'ed', 'es', 's']:
                        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                            return w[:-len(suffix)]
                    return w
                span_word_stems = {_stem_simple(sw) for sw in re.findall(r'\b[a-zA-Z]{4,}\b', span_lower)}
                cond_in_span = any(_stem_simple(cw) in span_word_stems for cw in cond_words)
                if not cond_in_span:
                    return EntailmentVerdict(is_entailed=False, confidence=0.0, provider="condition_rule")

        # 3. Role / Actor Modifier Verification: if claim introduces role modifiers (e.g. senior, chief, head),
        # they must be present in the span.
        role_modifiers = {'senior', 'chief', 'lead', 'head', 'external', 'independent', 'deputy'}
        claim_words_all = set(re.findall(r'\b[a-zA-Z]{4,}\b', clean_claim))
        span_words_all = set(re.findall(r'\b[a-zA-Z]{4,}\b', span_lower))
        for mod in role_modifiers:
            if mod in claim_words_all and mod not in span_words_all:
                return EntailmentVerdict(is_entailed=False, confidence=0.0, provider="role_modifier_rule")

        # 4. Exact text or normalization match
        norm_claim = re.sub(r'[^\w\s]', '', clean_claim).strip()
        norm_span = re.sub(r'[^\w\s]', '', span_lower).strip()
        if norm_claim in norm_span:
            return EntailmentVerdict(is_entailed=True, confidence=1.0, provider="exact_normalized_match")

        # 5. Semantic entailment via true NLI model (never lexical fallback)
        nli = self._get_nli()
        if nli is not None and getattr(nli, "model", None) is not None:
            try:
                probs = nli._predict_entailment_probs([(span_text, claim_text)])
                if probs and probs[0] >= 0.65:
                    return EntailmentVerdict(
                        is_entailed=True,
                        confidence=round(float(probs[0]), 4),
                        provider="cross_encoder_nli",
                        model=getattr(nli, "model_name", "nli-deberta-v3-small")
                    )
                return EntailmentVerdict(
                    is_entailed=False,
                    confidence=round(float(probs[0]) if probs else 0.0, 4),
                    provider="cross_encoder_nli",
                    model=getattr(nli, "model_name", "nli-deberta-v3-small")
                )
            except Exception:
                return EntailmentVerdict(is_entailed=False, confidence=0.0, provider="cross_encoder_nli")

        # If NLI is not available, we cannot verify entailment of non-exact claims
        return EntailmentVerdict(is_entailed=False, confidence=0.0, provider="unmatched")

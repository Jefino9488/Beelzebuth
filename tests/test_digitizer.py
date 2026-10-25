import pytest
from injester.application.digitizer import reconstruct_digital_markdown
from injester.ingestion.schema import NormalizedElement, ProvenanceMetadata
from injester.synthesis.spans import SpanRegistry, SourceSpan


class MockSpanRegistry:
    def __init__(self, spans_dict):
        self.spans_by_id = spans_dict


def test_digitizer_span_matching_rejects_short_substring_collisions():
    """
    Evidence Grounding: Short words and headings ('Step', 'Install', 'Summary')
    must NEVER match unrelated longer spans via substring containment.
    """
    registry = MockSpanRegistry({
        "S001": SourceSpan(
            span_id="S001",
            chunk_id="c1",
            source_doc="doc1.docx",
            text="Configure UEFI Secure Boot in motherboard BIOS setup and enable TPM 2.0.",
            location="Page 1",
            section="Firmware Configuration",
        ),
        "S002": SourceSpan(
            span_id="S002",
            chunk_id="c2",
            source_doc="doc1.docx",
            text="Install the operating system and configure network interfaces for deployment.",
            location="Page 2",
            section="OS Setup",
        ),
    })

    meta = ProvenanceMetadata(tenant_id="t1", document_id="doc1", filename="doc1.docx")
    # Element has short text "Install"
    el_short = NormalizedElement(
        element_id="el_1",
        text="Install",
        element_type="NarrativeText",
        metadata=meta,
    )
    # Element has short heading "Summary"
    el_summary = NormalizedElement(
        element_id="el_2",
        text="Summary",
        element_type="Header",
        metadata=meta,
    )

    annotated, clean, raw = reconstruct_digital_markdown([el_short, el_summary], span_registry=registry)
    # The body text itself must not attach citations to these short titles/words
    body = annotated.split("## Citation & Source Provenance Index")[0]
    assert "[S001]" not in body, "S001 should not match short word 'Install'"
    assert "[S002]" not in body, "S002 should not match short word 'Install'"


def test_digitizer_span_matching_exact_and_normalized():
    """
    Evidence Grounding: Full verbatim or normalized phrases correctly match and attach citations.
    """
    span_text = "Configure UEFI Secure Boot in motherboard BIOS setup and enable TPM 2.0."
    registry = MockSpanRegistry({
        "S001": SourceSpan(
            span_id="S001",
            chunk_id="c1",
            source_doc="doc1.docx",
            text=span_text,
            location="Page 1",
            section="Firmware",
        ),
    })

    meta = ProvenanceMetadata(tenant_id="t1", document_id="doc1", filename="doc1.docx")
    # Exact match
    el_exact = NormalizedElement(
        element_id="el_exact",
        text=span_text,
        element_type="NarrativeText",
        metadata=meta,
    )
    annotated_exact, _, _ = reconstruct_digital_markdown([el_exact], span_registry=registry)
    assert "[S001]" in annotated_exact

    # Normalized match (different casing and extra whitespace)
    el_norm = NormalizedElement(
        element_id="el_norm",
        text="configure  uefi secure boot in motherboard bios setup and enable tpm 2.0.",
        element_type="NarrativeText",
        metadata=meta,
    )
    annotated_norm, _, _ = reconstruct_digital_markdown([el_norm], span_registry=registry)
    assert "[S001]" in annotated_norm


def test_digitizer_span_matching_rejects_ambiguous_near_ties():
    """
    Evidence Grounding: When two distinct candidate spans tie or have ambiguous overlap,
    the engine rejects the match rather than guessing the wrong citation.
    """
    registry = MockSpanRegistry({
        "S010": SourceSpan(
            span_id="S010",
            chunk_id="c10",
            source_doc="doc1.docx",
            text="Verify primary server database cluster replication status and latency thresholds.",
            location="Page 5",
            section="Database",
        ),
        "S011": SourceSpan(
            span_id="S011",
            chunk_id="c11",
            source_doc="doc1.docx",
            text="Verify secondary server database cluster replication status and latency thresholds.",
            location="Page 6",
            section="Database",
        ),
    })

    meta = ProvenanceMetadata(tenant_id="t1", document_id="doc1", filename="doc1.docx")
    # Snippet drops 'primary' / 'secondary' - ambiguous between S010 and S011
    el_ambiguous = NormalizedElement(
        element_id="el_ambiguous",
        text="Verify server database cluster replication status and latency thresholds for production.",
        element_type="NarrativeText",
        metadata=meta,
    )
    annotated, _, _ = reconstruct_digital_markdown([el_ambiguous], span_registry=registry)
    body = annotated.split("## Citation & Source Provenance Index")[0]
    assert "[S010]" not in body, "Ambiguous near-tie span S010 must not be attached inline"
    assert "[S011]" not in body, "Ambiguous near-tie span S011 must not be attached inline"


def test_digitizer_duplicate_text_at_different_locations_disambiguated():
    """
    Evidence Grounding: When two distinct source spans have identical verbatim text
    at different locations (e.g. initial submission vs final approval),
    the digitizer disambiguates using section/location context without overwriting.
    """
    dup_text = "Click the Submit button to finalize the application and submit to supervisor."
    registry = MockSpanRegistry({
        "S001": SourceSpan(
            span_id="S001",
            chunk_id="c1",
            source_doc="sop.docx",
            text=dup_text,
            location="Page 1",
            section="Step A > Initial Submission",
        ),
        "S002": SourceSpan(
            span_id="S002",
            chunk_id="c2",
            source_doc="sop.docx",
            text=dup_text,
            location="Page 5",
            section="Step E > Final Approval",
        ),
    })

    meta_a = ProvenanceMetadata(
        tenant_id="t1",
        document_id="doc1",
        filename="sop.docx",
        page_number=1,
        section_path=["Step A", "Initial Submission"],
    )
    el_a = NormalizedElement(
        element_id="el_a",
        text=dup_text,
        element_type="NarrativeText",
        metadata=meta_a,
    )

    meta_e = ProvenanceMetadata(
        tenant_id="t1",
        document_id="doc1",
        filename="sop.docx",
        page_number=5,
        section_path=["Step E", "Final Approval"],
    )
    el_e = NormalizedElement(
        element_id="el_e",
        text=dup_text,
        element_type="NarrativeText",
        metadata=meta_e,
    )

    annotated_a, _, _ = reconstruct_digital_markdown([el_a], span_registry=registry)
    body_a = annotated_a.split("## Citation & Source Provenance Index")[0]
    assert "[S001]" in body_a, "Element A should resolve to S001"
    assert "[S002]" not in body_a, "Element A must NOT receive S002"

    annotated_e, _, _ = reconstruct_digital_markdown([el_e], span_registry=registry)
    body_e = annotated_e.split("## Citation & Source Provenance Index")[0]
    assert "[S002]" in body_e, "Element E should resolve to S002"
    assert "[S001]" not in body_e, "Element E must NOT receive S001"


def test_digitizer_duplicate_text_without_context_unresolved():
    """
    Evidence Grounding: When duplicate text appears across multiple distinct spans
    and context cannot unambiguously distinguish them, the engine leaves the citation
    unresolved rather than attaching the wrong span.
    """
    dup_text = "Click the Submit button to finalize the application and submit to supervisor."
    registry = MockSpanRegistry({
        "S001": SourceSpan(
            span_id="S001",
            chunk_id="c1",
            source_doc="sop.docx",
            text=dup_text,
            location="Page 1",
            section="Step A",
        ),
        "S002": SourceSpan(
            span_id="S002",
            chunk_id="c2",
            source_doc="sop.docx",
            text=dup_text,
            location="Page 5",
            section="Step E",
        ),
    })

    # Element has no section path and no page number
    meta_ambiguous = ProvenanceMetadata(
        tenant_id="t1",
        document_id="doc1",
        filename="sop.docx",
    )
    el = NormalizedElement(
        element_id="el_unknown",
        text=dup_text,
        element_type="NarrativeText",
        metadata=meta_ambiguous,
    )

    annotated, _, _ = reconstruct_digital_markdown([el], span_registry=registry)
    body = annotated.split("## Citation & Source Provenance Index")[0]
    assert "[S001]" not in body, "Ambiguous duplicate without context must NOT resolve to S001"
    assert "[S002]" not in body, "Ambiguous duplicate without context must NOT resolve to S002"



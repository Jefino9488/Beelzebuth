import tempfile
from pathlib import Path
import pytest
from injester.ingestion.extractor import DocumentExtractor
from injester.application.digitizer import reconstruct_digital_markdown, convert_table_to_gfm
from injester.ingestion.schema import NormalizedElement, ProvenanceMetadata


def test_extractor_unstructured_backend():
    extractor = DocumentExtractor()
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write("# Financial Report\n\nQuarterly profits increased by 15%.\n\n| Metric | Value |\n| --- | --- |\n| Revenue | $2.5M |\n")
        f_path = f.name

    try:
        elements = extractor.extract(f_path, document_id="doc_unst", backend="unstructured")
        assert len(elements) >= 2
        titles = [e for e in elements if e.element_type in ("Title", "Header")]
        assert len(titles) >= 1
        assert "Financial Report" in titles[0].text
    finally:
        Path(f_path).unlink(missing_ok=True)


def test_extractor_docling_backend():
    extractor = DocumentExtractor()
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write("# Architecture Notes\n\nDocling provides deep learning table structure recognition.\n\n| Backend | Table F1 |\n| --- | --- |\n| Docling | 89.9 |\n")
        f_path = f.name

    try:
        elements = extractor.extract(f_path, document_id="doc_docling", backend="docling")
        assert len(elements) >= 2
        tables = [e for e in elements if e.element_type == "Table"]
        assert len(tables) >= 1
        assert "Table F1" in tables[0].text
        assert "89.9" in tables[0].text
    finally:
        Path(f_path).unlink(missing_ok=True)


def test_beautifulsoup_table_conversion():
    meta = ProvenanceMetadata(
        document_id="doc_tbl",
        filename="table.html",
        tenant_id="default",
        source_location="Page 1",
        element_type="Table",
        extra={"text_as_html": "<table><tr><th>Metric</th><th>Score</th></tr><tr><td>Accuracy</td><td>98.5%</td></tr></table>"}
    )
    el = NormalizedElement(
        element_id="el_tbl_01",
        element_type="Table",
        text="Accuracy 98.5%",
        metadata=meta,
    )
    gfm = convert_table_to_gfm(el)
    assert "| Metric | Score |" in gfm
    assert "| Accuracy | 98.5% |" in gfm


def test_digitizer_prose_does_not_hallucinate_mermaid():
    """Verify that regular text containing arrows or numbered steps is NOT converted into Mermaid."""
    meta = ProvenanceMetadata(
        document_id="doc_prose",
        filename="prose.txt",
        tenant_id="default",
        source_location="Page 1",
        element_type="NarrativeText"
    )
    el = NormalizedElement(
        element_id="el_prose_01",
        element_type="NarrativeText",
        text="The progression was A -> B -> C during phase 1.",
        metadata=meta,
    )
    annotated_md, clean_md, _ = reconstruct_digital_markdown([el], document_title="Prose Test")
    assert "```mermaid" not in annotated_md
    assert "```mermaid" not in clean_md
    assert "The progression was A -> B -> C during phase 1." in clean_md

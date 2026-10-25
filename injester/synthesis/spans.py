import re
import hashlib
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from injester.ingestion.schema import DocumentChunk

class SourceSpan(BaseModel):
    """
    Deterministic atomic unit of source evidence.
    Pre-extracted from a DocumentChunk so LLMs reference fixed span IDs rather than fabricating text.
    Carries full immutable provenance (tenant, document, version, and content hashes).
    """
    span_id: str = Field(description="Deterministic span identifier, e.g. 'S001'")
    canonical_id: Optional[str] = Field(default=None, description="SHA-256 version-immutable identifier")
    chunk_id: str = Field(description="Source chunk ID")
    source_doc: str = Field(description="Original filename")
    location: str = Field(default="", description="Location or page number in source")
    section: str = Field(default="", description="Section hierarchy path")
    text: str = Field(description="Exact verbatim text of the span")
    tenant_id: Optional[str] = Field(default=None, description="Tenant organization scope")
    file_id: Optional[str] = Field(default=None, description="Database File record ID")
    file_version_id: Optional[str] = Field(default=None, description="File version ID")
    file_hash: Optional[str] = Field(default=None, description="SHA-256 hash of original file blob")
    text_hash: Optional[str] = Field(default=None, description="SHA-256 of verbatim span text")

class SpanRegistry:
    """
    Immutable repository of all source spans for a tenant/document set.
    Allows exact resolution of span IDs back to verifiable source text.
    """
    def __init__(self):
        self.spans_by_id: Dict[str, SourceSpan] = {}
        self.spans_by_chunk: Dict[str, List[SourceSpan]] = {}

    def register_chunk(self, chunk: DocumentChunk, start_index: int = 1) -> int:
        """
        Deterministically segments a DocumentChunk into atomic spans and registers them.
        Returns the next sequential index.
        """
        raw_text = chunk.text.strip()
        if not raw_text:
            return start_index

        loc = chunk.provenance.source_location or (f"Page {chunk.page_numbers[0]}" if chunk.page_numbers else "")
        sec = " > ".join(chunk.section_hierarchy) if chunk.section_hierarchy else ""
        tenant = getattr(chunk.provenance, 'tenant_id', None) or getattr(chunk, 'tenant_id', None) or "platform"
        file_ver = (
            getattr(chunk.provenance, 'file_version_id', None)
            or getattr(chunk, 'file_version_id', None)
        )
        if not file_ver:
            raise ValueError(f"Chunk '{chunk.chunk_id}' is missing mandatory file_version_id; unversioned spans are prohibited.")

        # Deterministic segmentation: split by lines, bullets, and sentences
        raw_spans = self._segment_text(raw_text)

        chunk_spans = []
        current_idx = start_index
        for text_unit in raw_spans:
            text_clean = text_unit.strip()
            if not text_clean or len(text_clean) < 5:
                continue
            span_id = f"S{current_idx:03d}"
            text_hash = hashlib.sha256(text_clean.encode("utf-8")).hexdigest()
            canonical_id = f"S_{hashlib.sha256(f'{tenant}:{file_ver}:{loc}:{text_clean}'.encode('utf-8')).hexdigest()}"

            span = SourceSpan(
                span_id=span_id,
                canonical_id=canonical_id,
                chunk_id=chunk.chunk_id,
                source_doc=chunk.filename,
                location=loc,
                section=sec,
                text=text_clean,
                tenant_id=tenant,
                file_version_id=str(file_ver),
                text_hash=text_hash,
            )
            # Register by both sequential ID and canonical SHA-256 ID
            self.spans_by_id[span_id] = span
            self.spans_by_id[canonical_id] = span
            chunk_spans.append(span)
            current_idx += 1

        self.spans_by_chunk[chunk.chunk_id] = chunk_spans
        return current_idx

    def _segment_text(self, text: str) -> List[str]:
        """
        Splits text into bullet lines or sentences deterministically.
        """
        units: List[str] = []
        lines = text.split("\n")
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            # Check if line is a bullet item or list item or table row
            if re.match(r"^(\*|-|\+|\d+[\.)]|[a-zA-Z][\.)]|\|)", line_str):
                units.append(line_str)
            else:
                # Split line by sentence terminators if reasonably long
                sentences = re.split(r"(?<=[.?!])\s+(?=[A-Z0-9\"'])", line_str)
                for s in sentences:
                    s_clean = s.strip()
                    if s_clean:
                        units.append(s_clean)
        return units

    def get_span(self, span_id: str) -> Optional[SourceSpan]:
        return self.spans_by_id.get(span_id)

    def get_chunk_spans(self, chunk_id: str) -> List[SourceSpan]:
        return self.spans_by_chunk.get(chunk_id, [])

    def format_chunk_with_spans(self, chunk: DocumentChunk) -> str:
        """
        Formats a chunk with embedded [S###] span identifiers for prompt injection.
        """
        spans = self.get_chunk_spans(chunk.chunk_id)
        if not spans:
            return chunk.text

        lines = []
        loc = chunk.provenance.source_location or (f"Page {chunk.page_numbers[0]}" if chunk.page_numbers else "")
        sec = " > ".join(chunk.section_hierarchy) if chunk.section_hierarchy else "General"
        lines.append(f"[CHUNK {chunk.chunk_id} | Source: {chunk.filename} | Location: {loc} | Section: {sec}]")
        for span in spans:
            lines.append(f"[{span.span_id}] {span.text}")
        lines.append(f"[END CHUNK {chunk.chunk_id}]")
        return "\n".join(lines)

    @classmethod
    def from_chunks(cls, chunks: List[DocumentChunk]) -> "SpanRegistry":
        registry = cls()
        current_idx = 1
        for c in chunks:
            current_idx = registry.register_chunk(c, start_index=current_idx)
        return registry

    def compute_manifest_hash(self) -> str:
        """
        Computes the canonical SHA-256 hash of all registered spans.
        Sorts spans by span_id and hashes canonical_id:tenant_id:file_version_id:text_hash:location.
        """
        if not self.spans_by_id:
            return hashlib.sha256(b"empty_span_registry").hexdigest()
        parts = []
        for sid in sorted(self.spans_by_id.keys()):
            span = self.spans_by_id[sid]
            part = f"{sid}:{span.canonical_id or ''}:{span.tenant_id or ''}:{span.file_version_id or ''}:{span.text_hash or ''}:{span.location or ''}"
            parts.append(part)
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

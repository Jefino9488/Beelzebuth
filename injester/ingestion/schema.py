from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ProvenanceMetadata(BaseModel):
    """Deep provenance metadata for full traceability back to source documents."""
    document_id: str = Field(description="Unique ID of the parent File record")
    filename: str = Field(description="Original filename (e.g. IT_Access_Policy.pdf)")
    tenant_id: str = Field(description="Organisation tenant ID")
    page_number: Optional[int] = Field(default=None, description="Page number for PDFs/Docs")
    slide_number: Optional[int] = Field(default=None, description="Slide number for presentations")
    sheet_name: Optional[str] = Field(default=None, description="Sheet name for spreadsheets")
    section_path: List[str] = Field(default_factory=list, description="Hierarchy of headings, e.g. ['Access Control', 'Provisioning']")
    element_type: str = Field(default="NarrativeText", description="Title, NarrativeText, Table, ListItem, etc.")
    source_location: str = Field(default="", description="Human-readable citation location, e.g. 'Page 14, Section: Access Provisioning'")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Additional unstructured metadata")

class NormalizedElement(BaseModel):
    """A normalized piece of document content with preserved hierarchy and provenance."""
    element_id: str
    text: str
    element_type: str
    metadata: ProvenanceMetadata

class DocumentChunk(BaseModel):
    """
    An indexed chunk ready for embedding and citation-backed generation.
    Each chunk is fully traceable back to its origin.
    """
    chunk_id: str = Field(description="Unique chunk identifier, e.g. chunk_8f31")
    document_id: str
    filename: str
    tenant_id: str
    text: str
    section_hierarchy: List[str] = Field(default_factory=list)
    page_numbers: List[int] = Field(default_factory=list)
    provenance: ProvenanceMetadata

    def to_citation_format(self, citation_tag: str = "C1") -> str:
        """Outputs the structured citation format."""
        loc = self.provenance.source_location or f"Page {self.page_numbers[0] if self.page_numbers else 1}"
        sec = " > ".join(self.section_hierarchy) if self.section_hierarchy else "General"
        return (
            f"[{citation_tag}]\n"
            f"Source: {self.filename}\n"
            f"Location: {loc}\n"
            f"Section: {sec}\n"
            f"Chunk ID: {self.chunk_id}"
        )

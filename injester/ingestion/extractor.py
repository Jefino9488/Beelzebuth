import os
import uuid
from pathlib import Path
from typing import List, Optional
from unstructured.partition.auto import partition
from injester.ingestion.schema import NormalizedElement, ProvenanceMetadata

class DocumentExtractor:
    """
    Extracts content from heterogeneous document formats using Unstructured
    and normalizes them into structured elements with provenance tracking.
    """
    def __init__(self):
        pass

    def extract(
        self,
        file_path: str | Path,
        document_id: str,
        filename: Optional[str] = None,
        tenant_id: str = "default"
    ) -> List[NormalizedElement]:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        doc_filename = filename or path.name

        # Extract unstructured elements using partition
        raw_elements = partition(filename=str(path))
        normalized_elements: List[NormalizedElement] = []
        
        # Track running section breadcrumbs
        current_section_path: List[str] = []

        for idx, el in enumerate(raw_elements):
            el_type = type(el).__name__
            text = str(el).strip()
            if not text:
                continue

            # Update running section hierarchy when encountering Titles/Headings
            if el_type in ("Title", "Header"):
                # Clean up title text
                clean_title = text.strip()
                # For top-level or new section, update section hierarchy
                current_section_path = [clean_title]

            # Extract page / metadata
            page_number = None
            if hasattr(el, "metadata") and el.metadata:
                page_number = getattr(el.metadata, "page_number", None)

            # Build readable source location string
            loc_parts = []
            if page_number:
                loc_parts.append(f"Page: {page_number}")
            if current_section_path:
                loc_parts.append(f"Section: {' > '.join(current_section_path)}")
            source_loc = ", ".join(loc_parts) if loc_parts else f"File: {doc_filename}"

            meta = ProvenanceMetadata(
                document_id=document_id,
                filename=doc_filename,
                tenant_id=tenant_id,
                page_number=page_number,
                section_path=list(current_section_path),
                element_type=el_type,
                source_location=source_loc,
            )

            elem = NormalizedElement(
                element_id=f"{document_id}_el_{idx}",
                text=text,
                element_type=el_type,
                metadata=meta,
            )
            normalized_elements.append(elem)

        return normalized_elements

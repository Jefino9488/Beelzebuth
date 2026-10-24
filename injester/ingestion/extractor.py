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
        tenant_id: str = "default",
        file_version_id: Optional[str] = None,
        file_hash: Optional[str] = None,
    ) -> List[NormalizedElement]:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        doc_filename = filename or path.name

        # Extract unstructured elements using partition
        raw_elements = partition(filename=str(path))
        normalized_elements: List[NormalizedElement] = []
        
        # Track running section breadcrumbs as a hierarchical stack
        section_stack: List[str] = []
        current_section_path: List[str] = []

        import re

        for idx, el in enumerate(raw_elements):
            el_type = type(el).__name__
            text = str(el).strip()
            if not text:
                continue

            # Update running section hierarchy when encountering Titles/Headings
            if el_type in ("Title", "Header"):
                clean_title = text.strip()
                depth = 1
                if hasattr(el, "metadata") and el.metadata and getattr(el.metadata, "category_depth", None) is not None:
                    depth = int(el.metadata.category_depth) + 1
                elif clean_title.startswith("#"):
                    m = re.match(r"^(#+)", clean_title)
                    depth = len(m.group(1)) if m else 1
                    clean_title = clean_title.lstrip("#").strip()
                elif re.match(r"^(\d+\.)+", clean_title):
                    m = re.match(r"^(\d+(?:\.\d+)*)", clean_title)
                    depth = len(m.group(1).split(".")) if m else 1

                if depth <= 1:
                    section_stack = [clean_title]
                else:
                    section_stack = section_stack[:depth - 1]
                    section_stack.append(clean_title)
                current_section_path = list(section_stack)

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

            extra_dict = {}
            if file_hash:
                extra_dict["file_hash"] = file_hash
            if hasattr(el, "metadata") and el.metadata:
                if getattr(el.metadata, "text_as_html", None):
                    extra_dict["text_as_html"] = el.metadata.text_as_html
                if getattr(el.metadata, "image_path", None):
                    extra_dict["image_path"] = el.metadata.image_path

            meta = ProvenanceMetadata(
                document_id=document_id,
                filename=doc_filename,
                tenant_id=tenant_id,
                page_number=page_number,
                section_path=list(current_section_path),
                element_type=el_type,
                source_location=source_loc,
                file_version_id=file_version_id,
                extra=extra_dict,
            )

            elem = NormalizedElement(
                element_id=f"{document_id}_el_{idx}",
                text=text,
                element_type=el_type,
                metadata=meta,
            )
            normalized_elements.append(elem)

        return normalized_elements

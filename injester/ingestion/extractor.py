import os
import re
import uuid
from pathlib import Path
from typing import List, Optional
from unstructured.partition.auto import partition
from injester.ingestion.schema import NormalizedElement, ProvenanceMetadata

class DocumentExtractor:
    """
    Extracts content from heterogeneous document formats using either:
    1. Docling (Deep-learning layout analysis and TableFormer for best-in-class table F1)
    2. Unstructured (Fast deterministic partitioning with configurable hi_res / auto strategy)

    Normalizes all content into structured NormalizedElement objects with full provenance tracking.
    """
    def __init__(self, default_backend: Optional[str] = None):
        self.default_backend = default_backend or os.getenv("INJESTER_EXTRACTOR_BACKEND", "docling")

    def extract(
        self,
        file_path: str | Path,
        document_id: str,
        filename: Optional[str] = None,
        tenant_id: str = "default",
        file_version_id: Optional[str] = None,
        file_hash: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> List[NormalizedElement]:
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        doc_filename = filename or path.name
        active_backend = (backend or self.default_backend or "docling").lower()

        # Docling is the primary extraction engine for layout and table reconstruction
        if active_backend in ("docling", "auto"):
            try:
                elements = self._extract_with_docling(
                    path=path,
                    document_id=document_id,
                    doc_filename=doc_filename,
                    tenant_id=tenant_id,
                    file_version_id=file_version_id,
                    file_hash=file_hash,
                )
                if elements:
                    return elements
            except Exception:
                # Graceful fallback to Unstructured for unsupported filetypes or failures
                pass

        return self._extract_with_unstructured(
            path=path,
            document_id=document_id,
            doc_filename=doc_filename,
            tenant_id=tenant_id,
            file_version_id=file_version_id,
            file_hash=file_hash,
        )

    def _extract_with_docling(
        self,
        path: Path,
        document_id: str,
        doc_filename: str,
        tenant_id: str,
        file_version_id: Optional[str],
        file_hash: Optional[str],
    ) -> List[NormalizedElement]:
        """Extracts elements using Docling layout analysis and TableFormer."""
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(str(path))
        doc = result.document

        normalized_elements: List[NormalizedElement] = []
        section_stack: List[str] = []
        current_section_path: List[str] = []

        for idx, (item, level) in enumerate(doc.iterate_items()):
            itype = type(item).__name__
            text = getattr(item, "text", "")
            if hasattr(item, "export_to_markdown") and "Table" in itype:
                text = item.export_to_markdown(doc=doc)

            text = text.strip() if text else ""
            if not text:
                continue

            if "Title" in itype or "Header" in itype:
                clean_title = text.strip()
                if level <= 1:
                    section_stack = [clean_title]
                else:
                    section_stack = section_stack[:level - 1]
                    section_stack.append(clean_title)
                current_section_path = list(section_stack)
                el_type = "Title" if level <= 1 else "Header"
            elif "Table" in itype:
                el_type = "Table"
            elif "List" in itype:
                el_type = "ListItem"
            elif "Picture" in itype or "Figure" in itype:
                el_type = "Figure"
                caption = getattr(item, "caption", None)
                text = caption.text if caption else "Figure"
            else:
                el_type = "NarrativeText"

            page_number = None
            if hasattr(item, "prov") and item.prov:
                page_number = getattr(item.prov[0], "page_no", None)

            loc_parts = []
            if page_number:
                loc_parts.append(f"Page: {page_number}")
            if current_section_path:
                loc_parts.append(f"Section: {' > '.join(current_section_path)}")
            source_loc = ", ".join(loc_parts) if loc_parts else f"File: {doc_filename}"

            extra_dict = {}
            if file_hash:
                extra_dict["file_hash"] = file_hash

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

            normalized_elements.append(NormalizedElement(
                element_id=f"{document_id}_docling_{idx}",
                element_type=el_type,
                text=text,
                metadata=meta,
            ))

        return normalized_elements

    def _extract_with_unstructured(
        self,
        path: Path,
        document_id: str,
        doc_filename: str,
        tenant_id: str,
        file_version_id: Optional[str],
        file_hash: Optional[str],
    ) -> List[NormalizedElement]:
        """Extracts elements using Unstructured auto/hi_res partitioning."""
        strategy = os.getenv("INJESTER_PARTITION_STRATEGY", "auto")
        infer_table_structure = os.getenv("INJESTER_INFER_TABLE_STRUCTURE", "true").lower() in ("true", "1")
        partition_kwargs = {
            "filename": str(path),
            "strategy": strategy,
        }
        if infer_table_structure:
            partition_kwargs["skip_infer_table_types"] = []

        try:
            raw_elements = partition(**partition_kwargs)
        except Exception:
            raw_elements = partition(filename=str(path))

        normalized_elements: List[NormalizedElement] = []
        section_stack: List[str] = []
        current_section_path: List[str] = []

        for idx, el in enumerate(raw_elements):
            el_type = type(el).__name__
            text = str(el).strip()
            if not text:
                continue

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

            page_number = None
            if hasattr(el, "metadata") and el.metadata:
                page_number = getattr(el.metadata, "page_number", None)

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

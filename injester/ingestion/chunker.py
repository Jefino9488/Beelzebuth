import hashlib
from typing import List
from injester.ingestion.schema import NormalizedElement, DocumentChunk, ProvenanceMetadata

class HierarchicalChunker:
    """
    Intelligently chunks normalized document elements by preserving:
    - Section boundaries (flushes on new Title/Header)
    - Structural units (Tables, ListItems)
    - Source provenance (document ID, filename, pages, section breadcrumbs)
    """
    def __init__(self, target_chunk_size: int = 1200, overlap_size: int = 150):
        self.target_chunk_size = target_chunk_size
        self.overlap_size = overlap_size

    def chunk_elements(self, elements: List[NormalizedElement]) -> List[DocumentChunk]:
        if not elements:
            return []

        chunks: List[DocumentChunk] = []
        current_texts: List[str] = []
        current_len = 0
        current_pages: set[int] = set()
        current_section: List[str] = []
        first_elem_meta: ProvenanceMetadata = elements[0].metadata

        chunk_counter = 1

        def flush_chunk(is_section_boundary: bool = False):
            nonlocal current_texts, current_len, current_pages, current_section, chunk_counter
            if not current_texts:
                return

            merged_text = "\n\n".join(current_texts).strip()
            if not merged_text:
                current_texts = []
                current_len = 0
                current_pages = set()
                return

            # Generate short, readable chunk ID e.g. chunk_8f31a2
            doc_id_hash = hashlib.md5(f"{first_elem_meta.document_id}_{chunk_counter}_{merged_text[:30]}".encode()).hexdigest()[:6]
            chunk_id = f"chunk_{doc_id_hash}"

            sorted_pages = sorted(list(current_pages))
            loc_parts = []
            if sorted_pages:
                loc_parts.append(f"Page: {', '.join(map(str, sorted_pages))}")
            if current_section:
                loc_parts.append(f"Section: {' > '.join(current_section)}")
            loc_str = ", ".join(loc_parts) if loc_parts else f"File: {first_elem_meta.filename}"

            chunk_meta = ProvenanceMetadata(
                document_id=first_elem_meta.document_id,
                filename=first_elem_meta.filename,
                tenant_id=first_elem_meta.tenant_id,
                page_number=sorted_pages[0] if sorted_pages else None,
                section_path=list(current_section),
                element_type="CompositeChunk",
                source_location=loc_str,
                file_version_id=first_elem_meta.file_version_id,
                extra=dict(first_elem_meta.extra) if getattr(first_elem_meta, "extra", None) else {},
            )

            chunk = DocumentChunk(
                chunk_id=chunk_id,
                document_id=first_elem_meta.document_id,
                filename=first_elem_meta.filename,
                tenant_id=first_elem_meta.tenant_id,
                text=merged_text,
                section_hierarchy=list(current_section),
                page_numbers=sorted_pages,
                file_version_id=first_elem_meta.file_version_id,
                provenance=chunk_meta,
            )
            chunks.append(chunk)
            chunk_counter += 1

            if is_section_boundary or self.overlap_size <= 0:
                current_texts = []
                current_len = 0
                current_pages = set()
            else:
                # Sliding window overlap within same section
                overlap_texts: List[str] = []
                overlap_len = 0
                for t in reversed(current_texts):
                    if overlap_len + len(t) <= self.overlap_size or not overlap_texts:
                        overlap_texts.insert(0, t)
                        overlap_len += len(t)
                    else:
                        break
                current_texts = overlap_texts
                current_len = overlap_len

        for elem in elements:
            meta = elem.metadata
            el_text = elem.text.strip()
            if not el_text:
                continue

            # Strict section boundary: flush without cross-section overlap
            is_new_section = elem.element_type in ("Title", "Header")
            section_changed = bool(current_section and meta.section_path != current_section)

            if is_new_section or section_changed:
                flush_chunk(is_section_boundary=True)
                current_section = list(meta.section_path)

            if not current_section and meta.section_path:
                current_section = list(meta.section_path)

            # Check if adding this element exceeds chunk size limit
            if current_len + len(el_text) > self.target_chunk_size and current_len > 0:
                flush_chunk(is_section_boundary=False)
                current_section = list(meta.section_path)

            current_texts.append(el_text)
            current_len += len(el_text)
            if meta.page_number:
                current_pages.add(meta.page_number)

        flush_chunk(is_section_boundary=True)
        return chunks

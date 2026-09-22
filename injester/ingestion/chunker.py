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

        def flush_chunk():
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
            )

            chunk = DocumentChunk(
                chunk_id=chunk_id,
                document_id=first_elem_meta.document_id,
                filename=first_elem_meta.filename,
                tenant_id=first_elem_meta.tenant_id,
                text=merged_text,
                section_hierarchy=list(current_section),
                page_numbers=sorted_pages,
                provenance=chunk_meta,
            )
            chunks.append(chunk)
            chunk_counter += 1

            current_texts = []
            current_len = 0
            current_pages = set()

        for elem in elements:
            meta = elem.metadata
            el_text = elem.text.strip()
            if not el_text:
                continue

            # If encountering a major section change, flush existing chunk
            is_new_section = elem.element_type in ("Title", "Header")
            section_changed = meta.section_path != current_section

            if (is_new_section or section_changed) and current_len > 300:
                flush_chunk()
                current_section = list(meta.section_path)

            if not current_section and meta.section_path:
                current_section = list(meta.section_path)

            # Check if adding this element exceeds chunk size limit
            if current_len + len(el_text) > self.target_chunk_size and current_len > 0:
                flush_chunk()
                current_section = list(meta.section_path)

            current_texts.append(el_text)
            current_len += len(el_text)
            if meta.page_number:
                current_pages.add(meta.page_number)

        flush_chunk()
        return chunks

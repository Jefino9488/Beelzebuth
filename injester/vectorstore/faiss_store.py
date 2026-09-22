import json
from pathlib import Path
from typing import List, Tuple, Dict
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

from injester.config import settings
from injester.ingestion.schema import DocumentChunk
from injester.vectorstore.base import VectorStore

class FaissVectorStore(VectorStore):
    """
    FAISS-backed Vector Store with per-tenant isolation.
    Each tenant has its own isolated index and chunk metadata storage.
    """
    _embedding_model: SentenceTransformer = None

    def __init__(self, base_storage_dir: Path = None):
        self.storage_dir = (base_storage_dir or settings.STORAGE_DIR) / "vectorstore"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if FaissVectorStore._embedding_model is None:
            FaissVectorStore._embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
        self.model = FaissVectorStore._embedding_model

    def _get_tenant_dir(self, tenant_id: str) -> Path:
        t_dir = self.storage_dir / tenant_id
        t_dir.mkdir(parents=True, exist_ok=True)
        return t_dir

    def _load_tenant_index(self, tenant_id: str) -> Tuple[faiss.Index, List[DocumentChunk]]:
        t_dir = self._get_tenant_dir(tenant_id)
        index_file = t_dir / "index.faiss"
        chunks_file = t_dir / "chunks.json"

        if index_file.exists() and chunks_file.exists():
            index = faiss.read_index(str(index_file))
            with open(chunks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                chunks = [DocumentChunk(**item) for item in data]
            return index, chunks

        # Initialize fresh index with model dimension
        dim = getattr(self.model, "get_embedding_dimension", getattr(self.model, "get_sentence_embedding_dimension", None))()
        index = faiss.IndexFlatIP(dim)
        return index, []

    def _save_tenant_index(self, tenant_id: str, index: faiss.Index, chunks: List[DocumentChunk]) -> None:
        t_dir = self._get_tenant_dir(tenant_id)
        index_file = t_dir / "index.faiss"
        chunks_file = t_dir / "chunks.json"

        faiss.write_index(index, str(index_file))
        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump([chunk.model_dump() for chunk in chunks], f, indent=2)

    def add_documents(self, tenant_id: str, chunks: List[DocumentChunk]) -> None:
        if not chunks:
            return

        index, existing_chunks = self._load_tenant_index(tenant_id)

        texts = [chunk.text for chunk in chunks]
        embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        embeddings = embeddings.astype(np.float32)

        index.add(embeddings)
        all_chunks = existing_chunks + chunks

        self._save_tenant_index(tenant_id, index, all_chunks)

    def search(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Tuple[DocumentChunk, float]]:
        index, chunks = self._load_tenant_index(tenant_id)
        if not chunks or index.ntotal == 0:
            return []

        query_embedding = self.model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        query_embedding = query_embedding.astype(np.float32)

        actual_k = min(top_k, index.ntotal)
        scores, indices = index.search(query_embedding, actual_k)

        results: List[Tuple[DocumentChunk, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx < len(chunks):
                results.append((chunks[idx], float(score)))

        return results

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        index, chunks = self._load_tenant_index(tenant_id)
        if not chunks:
            return

        # Filter out chunks matching document_id
        retained_chunks = [c for c in chunks if c.document_id != document_id]
        if len(retained_chunks) == len(chunks):
            return

        # Rebuild index
        dim = getattr(self.model, "get_embedding_dimension", getattr(self.model, "get_sentence_embedding_dimension", None))()
        new_index = faiss.IndexFlatIP(dim)

        if retained_chunks:
            texts = [c.text for c in retained_chunks]
            embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True).astype(np.float32)
            new_index.add(embeddings)

        self._save_tenant_index(tenant_id, new_index, retained_chunks)

from abc import ABC, abstractmethod
from typing import List, Tuple
from injester.ingestion.schema import DocumentChunk

class VectorStore(ABC):
    """
    Abstract Vector Store interface.
    Enforces tenant isolation: all read/write operations must be scoped to tenant_id.
    This abstraction allows switching from FAISS to pgvector or Qdrant without altering business logic.
    """

    @abstractmethod
    def add_documents(self, tenant_id: str, chunks: List[DocumentChunk]) -> None:
        """Embeds and indexes document chunks for a specific tenant."""
        pass

    @abstractmethod
    def search(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Retrieves top_k relevant chunks for a query within the tenant partition.
        Returns tuples of (DocumentChunk, similarity_score).
        """
        pass

    @abstractmethod
    def delete_document(self, tenant_id: str, document_id: str) -> None:
        """Removes all indexed chunks associated with a specific document."""
        pass

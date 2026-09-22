from typing import List, Dict, Tuple
from rank_bm25 import BM25Okapi
from injester.ingestion.schema import DocumentChunk
from injester.vectorstore.base import VectorStore

class HybridRetriever:
    """
    Hybrid retriever combining dense vector search (FAISS) with
    sparse lexical keyword matching (BM25) using Reciprocal Rank Fusion (RRF).
    Scoped strictly to tenant_id.
    """
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    def retrieve(
        self,
        tenant_id: str,
        query: str,
        all_tenant_chunks: List[DocumentChunk],
        top_k: int = 5
    ) -> List[DocumentChunk]:
        if not all_tenant_chunks:
            return []

        # 1. Dense Vector Search
        vector_results = self.vector_store.search(tenant_id, query, top_k=top_k * 2)

        # 2. Sparse BM25 Search
        tokenized_corpus = [chunk.text.lower().split() for chunk in all_tenant_chunks]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = query.lower().split()
        bm25_scores = bm25.get_scores(tokenized_query)

        # Sort BM25 results
        bm25_ranked_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k * 2]

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores: Dict[str, float] = {}
        chunk_map: Dict[str, DocumentChunk] = {c.chunk_id: c for c in all_tenant_chunks}

        k_constant = 60.0

        for rank, (chunk, _) in enumerate(vector_results):
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + (1.0 / (k_constant + rank + 1))

        for rank, idx in enumerate(bm25_ranked_indices):
            c_id = all_tenant_chunks[idx].chunk_id
            rrf_scores[c_id] = rrf_scores.get(c_id, 0.0) + (1.0 / (k_constant + rank + 1))

        # Sort chunks by fused score
        sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

        ranked_chunks = [chunk_map[cid] for cid in sorted_chunk_ids if cid in chunk_map]
        return ranked_chunks[:top_k]

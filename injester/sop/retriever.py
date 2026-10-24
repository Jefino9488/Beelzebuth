import hashlib
import logging
from typing import List, Dict, Tuple, Optional
from rank_bm25 import BM25Okapi
from injester.ingestion.schema import DocumentChunk
from injester.vectorstore.base import VectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """
    Hybrid retriever combining dense vector search (FAISS) with
    sparse lexical keyword matching (BM25) using Reciprocal Rank Fusion (RRF),
    followed by an optional neural Cross-Encoder semantic reranker stage.
    Scoped strictly to tenant_id with in-memory BM25 index caching.
    """
    _cross_encoder = None
    _bm25_cache: Dict[str, Tuple[str, BM25Okapi]] = {}

    def __init__(
        self,
        vector_store: VectorStore,
        reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ):
        self.vector_store = vector_store
        self.reranker_model_name = reranker_model

    def _get_cross_encoder(self):
        if HybridRetriever._cross_encoder is None:
            try:
                from sentence_transformers import CrossEncoder
                HybridRetriever._cross_encoder = CrossEncoder(self.reranker_model_name)
            except Exception as e:
                logger.info("Neural CrossEncoder not available (%s); will use RRF.", e)
                HybridRetriever._cross_encoder = False
        return HybridRetriever._cross_encoder

    def retrieve(
        self,
        tenant_id: str,
        query: str,
        all_tenant_chunks: List[DocumentChunk],
        top_k: int = 5
    ) -> List[DocumentChunk]:
        if not all_tenant_chunks:
            return []

        # 1. Dense Vector Search (Candidate pooling)
        pool_size = max(top_k * 3, 15)
        vector_results = self.vector_store.search(tenant_id, query, top_k=pool_size)

        # 2. Sparse BM25 Search with corpus caching
        chunk_ids_fingerprint = hashlib.sha256("".join(c.chunk_id for c in all_tenant_chunks).encode("utf-8")).hexdigest()[:16]
        cached_entry = HybridRetriever._bm25_cache.get(tenant_id)
        if cached_entry and cached_entry[0] == chunk_ids_fingerprint:
            bm25 = cached_entry[1]
        else:
            tokenized_corpus = [chunk.text.lower().split() for chunk in all_tenant_chunks]
            bm25 = BM25Okapi(tokenized_corpus)
            HybridRetriever._bm25_cache[tenant_id] = (chunk_ids_fingerprint, bm25)

        tokenized_query = query.lower().split()
        bm25_scores = bm25.get_scores(tokenized_query)

        # Sort BM25 results
        bm25_ranked_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:pool_size]

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores: Dict[str, float] = {}
        chunk_map: Dict[str, DocumentChunk] = {c.chunk_id: c for c in all_tenant_chunks}

        k_constant = 60.0

        for rank, (chunk, _) in enumerate(vector_results):
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + (1.0 / (k_constant + rank + 1))

        for rank, idx in enumerate(bm25_ranked_indices):
            c_id = all_tenant_chunks[idx].chunk_id
            rrf_scores[c_id] = rrf_scores.get(c_id, 0.0) + (1.0 / (k_constant + rank + 1))

        # Sort chunks by fused RRF score
        sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)
        rrf_candidates = [chunk_map[cid] for cid in sorted_chunk_ids if cid in chunk_map][:pool_size]

        # 4. Neural Cross-Encoder Reranker Stage
        encoder = self._get_cross_encoder()
        if encoder and len(rrf_candidates) > 1:
            try:
                pairs = [[query, c.text] for c in rrf_candidates]
                ce_scores = encoder.predict(pairs)
                reranked_with_scores = sorted(
                    zip(rrf_candidates, ce_scores),
                    key=lambda x: float(x[1]),
                    reverse=True
                )
                return [c for c, _ in reranked_with_scores][:top_k]
            except Exception as e:
                logger.warning("Neural CrossEncoder reranking failed (%s); falling back cleanly to RRF candidates.", e)

        return rrf_candidates[:top_k]

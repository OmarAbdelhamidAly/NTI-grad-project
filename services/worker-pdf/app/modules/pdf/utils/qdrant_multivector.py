"""Advanced Qdrant Utility for Multi-vector Retrieval (ColPali/MUVERA)."""
import structlog
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient, models
from app.infrastructure.config import settings

logger = structlog.get_logger(__name__)

class QdrantMultiVectorManager:
    def __init__(self, collection_name: str):
        self.client = QdrantClient(url=settings.QDRANT_URL or "http://qdrant:6333")
        self.collection_name = collection_name

    async def ensure_collection(self, vector_size: int = 128, text_vector_size: int = 384):
        """Create a collection optimized for both Vision (ColPali) and Text (Standard) RAG."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        
        if not exists:
            logger.info("creating_hybrid_collection", collection=self.collection_name)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    # Textual description (Standard Embedding)
                    "text": models.VectorParams(
                        size=text_vector_size,
                        distance=models.Distance.COSINE,
                        on_disk=True
                    ),
                    # ColPali multi-vectors (Keep for backward compatibility/legacy mode)
                    "colpali": models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                        multivector_config=models.MultiVectorConfig(
                            comparator=models.MultiVectorComparator.MAX_SIM
                        )
                    )
                }
            )

    def upsert_page(
        self, 
        page_id: str, 
        text_vector: List[float], 
        colpali_vectors: Optional[List[List[float]]] = None, 
        metadata: Dict[str, Any] = {},
        wait: bool = False
    ):
        """Upsert a single page with mandatory text description vector."""
        vector_data = {"text": text_vector}
        if colpali_vectors:
            vector_data["colpali"] = colpali_vectors
            
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=page_id,
                    vector=vector_data,
                    payload=metadata
                )
            ],
            wait=wait
        )

    def upsert_batch(
        self,
        points: List[Dict[str, Any]],
        wait: bool = False
    ):
        """Upsert multiple pages in a single batch."""
        point_structs = []
        for p in points:
            vector_data = {"text": p["text_vector"]}
            if p.get("colpali_vectors"):
                vector_data["colpali"] = p["colpali_vectors"]
                
            point_structs.append(
                models.PointStruct(
                    id=p["id"],
                    vector=vector_data,
                    payload=p["metadata"]
                )
            )
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=point_structs,
            wait=wait
        )

    def search_text(
        self, 
        query_vector: List[float], 
        limit: int = 5,
        filter: Optional[models.Filter] = None
    ):
        """Pure text-based vector search (Llama 3.2 Vision Description)."""
        return self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            using="text",
            limit=limit,
            query_filter=filter,
            with_payload=True
        ).points

    def search_hybrid(
        self, 
        query_text_vector: List[float], 
        query_colpali: Optional[List[List[float]]] = None,
        limit: int = 5
    ):
        """
        Two-stage retrieval if ColPali is available:
        1. Search using Text Description.
        2. (Optional) Re-rank using ColPali.
        """
        if not query_colpali:
            return self.search_text(query_text_vector, limit=limit)
            
        return self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                models.Prefetch(
                    query=query_text_vector,
                    using="text",
                    limit=limit * 5
                )
            ],
            query=query_colpali,
            using="colpali",
            limit=limit,
            with_payload=True
        ).points

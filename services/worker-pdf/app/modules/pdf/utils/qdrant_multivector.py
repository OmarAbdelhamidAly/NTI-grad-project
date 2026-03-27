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

    async def ensure_collection(self, vector_size: int = 128):
        """Create a collection optimized for ColPali multi-vectors and MUVERA FDEs."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        
        if not exists:
            logger.info("creating_multivector_collection", collection=self.collection_name)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    # The original ColPali multi-vectors (for re-ranking/MaxSim)
                    "colpali": models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                        multivector_config=models.MultiVectorConfig(
                            comparator=models.MultiVectorComparator.MAX_SIM
                        )
                    ),
                    # The MUVERA Fixed Dimensional Encoding (for fast HNSW retrieval)
                    "muvera": models.VectorParams(
                        size=40960, # Standard MUVERA dimension
                        distance=models.Distance.COSINE,
                        on_disk=True # MUVERA is huge, keep on disk
                    )
                },
                # HNSW optimized for large MUVERA vectors
                hnsw_config=models.HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                    on_disk=True
                )
            )

    def upsert_page(
        self, 
        page_id: str, 
        colpali_vectors: List[List[float]], 
        muvera_vector: List[float],
        metadata: Dict[str, Any],
        wait: bool = False
    ):
        """Upsert a single page with multi-vector and MUVERA encoding."""
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=page_id,
                    vector={
                        "colpali": colpali_vectors,
                        "muvera": muvera_vector
                    },
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
            point_structs.append(
                models.PointStruct(
                    id=p["id"],
                    vector={
                        "colpali": p["colpali_vectors"],
                        "muvera": p["muvera_vector"]
                    },
                    payload=p["metadata"]
                )
            )
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=point_structs,
            wait=wait
        )

    def search_hybrid(
        self, 
        query_muvera: List[float], 
        query_colpali: List[List[float]],
        limit: int = 5,
        hnsw_ef: int = 128
    ):
        """
        Two-stage retrieval:
        1. HNSW search using MUVERA (fast candidate retrieval).
        2. Re-rank results using ColPali multi-vectors (MaxSim).
        """
        return self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                models.Prefetch(
                    query=query_muvera,
                    using="muvera",
                    limit=limit * 5, # Fetch more candidates for re-ranking
                    params=models.SearchParams(hnsw_ef=hnsw_ef)
                )
            ],
            query=query_colpali,
            using="colpali",
            limit=limit,
            with_payload=True
        ).points

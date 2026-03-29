import structlog
import uuid
from typing import Dict, Any, List
from app.domain.analysis.entities import AnalysisState
from app.modules.pdf.utils.qdrant_multivector import QdrantMultiVectorManager
from app.modules.pdf.flows.deep_vision.agents.indexing_agent import _get_embedding_model

logger = structlog.get_logger(__name__)

async def adaptive_retrieval_agent(state: AnalysisState) -> Dict[str, Any]:
    """Retrieves document pages, with built-in reflection for query adjustment."""
    question = state.get("question")
    kb_id = state.get("kb_id")
    source_id = state.get("source_id")
    retry_count = state.get("retry_count", 0)
    
    logger.info("adaptive_retrieval_started", question=question, retry=retry_count)
    
    # 1. Initialize models and collection
    embed_model = _get_embedding_model()
    
    if kb_id:
        collection_name = f"kb_{str(kb_id).replace('-', '')}"
    else:
        collection_name = f"ds_{str(source_id).replace('-', '')}"
        
    qdrant = QdrantMultiVectorManager(collection_name=collection_name)

    # 2. Encode Query
    query_vector = embed_model.embed_query(question)
        
    # 3. Search via Text Description (Deep Vision collection always has text)
    search_results = qdrant.search_text(
        query_vector=query_vector,
        limit=5
    )
    
    # 4. Reflection: If no results found, flag for retry
    if not search_results:
        if retry_count < 2:
            logger.warning("retrieval_failed_triggering_reflection", retry=retry_count)
            return {"search_results": [], "reflection_needed": True, "retry_count": retry_count + 1}
        else:
            logger.error("retrieval_failed_no_more_retries")
            return {"error": "No relevant pages found after multiple attempts.", "search_results": []}

    # Extract page-level metadata
    page_nums = [hit.payload.get("page_num") for hit in search_results if hit.payload.get("page_num")]
    
    return {
        "search_results": search_results, 
        "page_nums": sorted(list(set(page_nums))),
        "reflection_needed": False,
        "executive_summary": f"Retrieved {len(search_results)} relevant pages."
    }

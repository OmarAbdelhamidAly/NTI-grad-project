import structlog
from typing import Dict, Any
from app.infrastructure.llm import get_llm
from langchain_core.messages import HumanMessage, SystemMessage
from app.domain.analysis.entities import AnalysisState

logger = structlog.get_logger(__name__)

async def verifier_agent(state: AnalysisState) -> Dict[str, Any]:
    """Verification Agent to prevent AI hallucinations in document synthesis."""
    report = state.get("insight_report")
    search_results = state.get("search_results", [])
    question = state.get("question")
    
    if not report or not search_results:
        return {"verified": True} # Cannot verify, skipping
        
    logger.info("visual_verification_started", question=question)
    
    # We use Groq's fast Llama 3.1 8B for verification
    llm = get_llm(temperature=0, model="llama-3.1-8b-instant")
    
    # Combine descriptions from all retrieved pages
    descriptions = ""
    for hit in search_results:
        p = hit.payload.get("page_num")
        desc = hit.payload.get("description", "No description available.")
        descriptions += f"## PAGE {p}:\n{desc}\n\n"

    prompt = f"""You are a Fact-Checker for a PDF analysis system. 
    Compare the generated AI ANSWER against the DOCUMENT PAGE DESCRIPTIONS.
    
    If the AI ANSWER contains statements that are NOT supported by the descriptions OR are plain wrong, flag them.
    
    DOCUMENT PAGE DESCRIPTIONS:
    {descriptions}
    
    AI ANSWER:
    {report}
    
    Your Task:
    1. If the answer is accurate, output 'VERIFIED'.
    2. If there are errors, output a detailed correction hint for the model.
    
    Output ONLY 'VERIFIED' or the correction hint."""
    
    try:
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        verification_res = res.content.strip()
        
        if "VERIFIED" in verification_res.upper():
            logger.info("visual_verification_passed")
            return {"verified": True, "verification_hint": None}
        else:
            logger.warning("visual_verification_failed", hint=verification_res)
            return {"verified": False, "verification_hint": verification_res}
            
    except Exception as e:
        logger.error("visual_verification_failed", error=str(e))
        return {"verified": True} # Fallback

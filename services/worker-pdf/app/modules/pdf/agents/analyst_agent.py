import structlog
from typing import Dict, Any
from app.infrastructure.llm import get_llm
from langchain_core.messages import HumanMessage, SystemMessage
from app.domain.analysis.entities import AnalysisState

logger = structlog.get_logger(__name__)

async def analyst_agent(state: AnalysisState) -> Dict[str, Any]:
    """Analytical Agent to generate high-level insights and professional recommendations."""
    report = state.get("insight_report")
    question = state.get("question")
    
    if not report:
        return {}
        
    logger.info("analyst_insights_started")
    
    # We use Groq's fast Llama 3.1 8B for analysis
    llm = get_llm(temperature=0, model="llama-3.1-8b-instant")
    
    prompt = f"""You are a Strategic Analyst with expertise in document intelligence.
    Review the following AI ANSWER and provide a structured Executive Summary and 3 actionable recommendations. 
    
    RULES:
    1. Respond in the same language as the answer (Arabic or English).
    2. Focus on "What should the user do next?".
    3. Keep it professional and concise.
    
    AI ANSWER:
    {report}
    
    FORMAT:
    Executive Summary: <summary>
    Insights: <insights>
    Recommendations: <1, 2, 3>"""
    
    try:
        res = await llm.ainvoke([HumanMessage(content=prompt)])
        analysis_content = res.content.strip()
        
        # Split into summary and recommendations (simplified)
        summary = analysis_content.split("Recommendations:")[0].replace("Executive Summary:", "").strip()
        recommendations = analysis_content.split("Recommendations:")[-1].strip()
        if not recommendations:
             recommendations = "Consult with a subject matter expert for deep-drive analysis."

        logger.info("analyst_insights_completed")
        return {
            "executive_summary": summary,
            "recommendations": recommendations,
        }
            
    except Exception as e:
        logger.error("analyst_insights_failed", error=str(e))
        return {"executive_summary": "Analysis completed. Review the findings above.", "recommendations": "No specific recommendations at this time."}

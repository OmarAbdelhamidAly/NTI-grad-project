"""Centralized LLM Factory.

All agents should use `get_llm()` instead of instantiating ChatGroq/ChatOpenAI
directly. This makes it easy to swap providers in one place.
"""

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel
from app.infrastructure.config import settings


def get_llm(temperature: float = 0, model: str | None = None) -> BaseChatModel:
    """Return a configured LLM instance with strict fallback chain."""
    
    # If no model provided, use environment default or hardcoded safe bet
    primary_model_name = model or settings.LLM_MODEL
    
    def _make_gemini(m: str = "gemini-flash-latest"):
        return ChatGoogleGenerativeAI(
            model=m,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=temperature,
            max_output_tokens=4096,
            max_retries=1,
        )

    def _make_groq(m: str = "llama-3.1-8b-instant"):
        return ChatOpenAI(
            model=m,
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            temperature=temperature,
            max_tokens=2048,
            max_retries=1,
        )

    # 1. Instantiate Primary Model
    if "gemini" in primary_model_name.lower():
        llm = _make_gemini(primary_model_name)
    elif "groq" in primary_model_name.lower() or "llama-3" in primary_model_name.lower():
        llm = _make_groq(primary_model_name)
    else:
        llm = _make_groq("llama-3.1-8b-instant")

    # 2. Build Fallbacks
    fallbacks = []
    if settings.GEMINI_API_KEY and "gemini" not in primary_model_name.lower():
        fallbacks.append(_make_gemini("gemini-flash-latest"))
    
    if fallbacks:
        return llm.with_fallbacks(fallbacks)
        
    return llm

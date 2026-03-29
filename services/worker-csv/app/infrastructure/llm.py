"""Centralized LLM Factory.

All agents should use `get_llm()` instead of instantiating ChatGroq/ChatOpenAI
directly. This makes it easy to swap providers in one place.

Configured for **OpenRouter** as the primary backend with strict fallbacks.
"""

from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from app.infrastructure.config import settings

def get_llm(temperature: float = 0, model: str | None = None) -> BaseChatModel:
    """Return a configured LLM instance with strict fallback chain: OpenRouter -> Groq -> Gemini."""
    
    primary_model_name = model or settings.LLM_MODEL or "meta-llama/llama-3.1-8b-instruct"
    
    def _make_gemini(m_name: str = "gemini-1.5-flash-latest"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=m_name,
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            temperature=temperature,
            max_tokens=4096,
            max_retries=0,
        )

    def _make_openrouter(m: str = "google/gemini-1.5-flash"):
        return ChatOpenAI(
            model=m,
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            temperature=temperature,
            max_tokens=2048,
            max_retries=1,
            default_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "DataAnalyst.AI",
            },
        )

    def _make_groq(m: str = "llama-3.1-8b-instant"):
        return ChatOpenAI(
            model=m,
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            temperature=temperature,
            max_tokens=2048,
            max_retries=0, 
        )

    def _make_ollama(m: str = "llama3.1"):
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError("langchain-ollama is not installed.")
        return ChatOllama(
            model=m,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=temperature,
        )

    # 1. Instantiate Primary Model
    if primary_model_name.startswith("ollama/"):
        llm = _make_ollama(primary_model_name.replace("ollama/", ""))
    elif primary_model_name.startswith("groq/"):
        llm = _make_groq(primary_model_name.replace("groq/", ""))
    elif "/" in primary_model_name:
        # Standard OpenRouter model format (e.g., anthropic/claude-3-5-haiku)
        llm = _make_openrouter(primary_model_name)
    elif "gemini" in primary_model_name.lower():
        llm = _make_gemini("gemini-1.5-flash-latest" if "flash" in primary_model_name.lower() else "gemini-1.5-pro-latest")
    elif "llama-3" in primary_model_name.lower():
        llm = _make_groq(primary_model_name)
    else:
        llm = _make_openrouter("meta-llama/llama-3.1-8b-instruct") if settings.OPENROUTER_API_KEY else _make_groq("llama-3.1-8b-instant")

    # 2. Build Fallback Chain
    fallbacks = []
    
    # If primary isn't OpenRouter, use OpenRouter Llama 8B or Groq as fallback
    if settings.OPENROUTER_API_KEY and "/" not in primary_model_name:
        fallbacks.append(_make_openrouter("meta-llama/llama-3.1-8b-instruct"))
    elif settings.GROQ_API_KEY and "groq" not in primary_model_name:
        fallbacks.append(_make_groq("llama-3.3-70b-versatile"))

    if settings.GEMINI_API_KEY and "gemini" not in primary_model_name:
        fallbacks.append(_make_gemini("gemini-1.5-flash-latest"))

    if fallbacks:
        return llm.with_fallbacks(fallbacks)
        
    return llm

"""Voice router — Speech-to-Text (STT) and metadata for TTS."""
import os
import structlog
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from typing import Annotated
from groq import Groq
from app.infrastructure.config import settings
from app.infrastructure.api_dependencies import get_current_user
from app.models.user import User

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

@router.post("/stt")
async def speech_to_text(
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
):
    """Transcribe audio using Groq Whisper-large-v3."""
    if not settings.GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured")

    client = Groq(api_key=settings.GROQ_API_KEY)
    
    try:
        # Read file into memory
        content = await file.read()
        filename = file.filename or "audio.webm"
        
        # Groq expects a file-like object with a name attribute
        from io import BytesIO
        audio_file = BytesIO(content)
        audio_file.name = filename

        transcription = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3",
            response_format="json",
            language="en", # Can be auto-detected if removed
            temperature=0.0,
        )
        
        logger.info("stt_success", user_id=str(current_user.id), length=len(content))
        return {"text": transcription.text}

    except Exception as e:
        logger.error("stt_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

# ── STT Agent (faster-whisper local GPU) ─────────────────────────────────
# Added by: feature/stt-agent branch
# Complements the Groq cloud endpoint above with a local GPU alternative.

import tempfile
from app.stt_agent import transcribe_audio

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg"}

@router.post("/transcribe")
async def transcribe_local(
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
    language: str = "en",   # pass ?language=ar for Arabic (Phase 2)
):
    """
    Transcribe audio using faster-whisper large-v3 running locally on GPU.
    Alternative to /stt — no Groq API credits used, audio never leaves the server.
    """
    ext = os.path.splitext(file.filename or "audio.wav")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}"
        )

    content = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.write(content)
    tmp.close()

    try:
        result = transcribe_audio(tmp.name, language=language)
        logger.info("local_stt_success", user_id=str(current_user.id), words=result.word_count)
        return {
            "text": result.text,
            "language": result.language,
            "language_probability": result.language_probability,
            "duration_seconds": result.duration_seconds,
            "word_count": result.word_count,
            "engine": "faster-whisper-large-v3-local"
        }
    except Exception as e:
        logger.error("local_stt_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Local transcription failed: {str(e)}")
    finally:
        os.unlink(tmp.name)


@router.post("/ask-voice")
async def ask_voice(
    current_user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
    language: str = "en",
    source_id: str = None,
):
    """
    Full pipeline: audio → transcription → ready for analysis.
    Frontend calls this, gets back the transcribed question,
    then calls POST /api/v1/analysis/run with that question.
    """
    ext = os.path.splitext(file.filename or "audio.wav")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}"
        )

    content = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.write(content)
    tmp.close()

    try:
        result = transcribe_audio(tmp.name, language=language)

        if not result.text.strip():
            raise HTTPException(status_code=422, detail="Transcription returned empty text.")

        logger.info("ask_voice_success", user_id=str(current_user.id), question=result.text[:80])
        return {
            "transcription": result.text,
            "language": result.language,
            "ready_to_analyze": True,
            "suggested_payload": {
                "question": result.text,
                "source_id": source_id,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("ask_voice_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Voice pipeline failed: {str(e)}")
    finally:
        os.unlink(tmp.name)
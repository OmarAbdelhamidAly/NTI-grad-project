from dataclasses import dataclass
from faster_whisper import WhisperModel
import os

# Load model once when the worker starts (not on every request)
_model = None

def get_model() -> WhisperModel:
    global _model
    if _model is None:
        device = "cuda" if os.environ.get("USE_GPU", "true").lower() == "true" else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        print(f"Loading faster-whisper large-v3 on {device}...")
        _model = WhisperModel("large-v3", device=device, compute_type=compute)
        print("✅ STT model loaded.")
    return _model


@dataclass
class TranscriptionResult:
    text: str
    language: str
    language_probability: float
    duration_seconds: float
    word_count: int


def transcribe_audio(
    audio_path: str,
    language: str = "en",   # Change to "ar" for Arabic (Phase 2)
    task: str = "transcribe"
) -> TranscriptionResult:
    """
    Transcribe an audio file using faster-whisper large-v3.

    Args:
        audio_path : path to .wav / .mp3 / .m4a file
        language   : 'en' for English, 'ar' for Arabic
        task       : 'transcribe' or 'translate' (→ English)

    Returns:
        TranscriptionResult with full text and metadata
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = get_model()

    segments, info = model.transcribe(
        audio_path,
        language=language,
        task=task,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )

    full_text = " ".join([seg.text.strip() for seg in segments])

    return TranscriptionResult(
        text=full_text,
        language=info.language,
        language_probability=round(info.language_probability, 3),
        duration_seconds=round(info.duration, 2),
        word_count=len(full_text.split())
    )
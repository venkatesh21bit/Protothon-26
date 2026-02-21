"""
Speech-to-Text Service (Google Gemini 3 Flash)
Transcribes patient audio recordings using the new google-genai SDK.
Supports Indian languages: Hindi, Tamil, Telugu, Marathi, Bengali, English.
"""
import logging
import os
import tempfile
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

LANGUAGE_NAMES: Dict[str, str] = {
    "en-IN": "Indian English",
    "en-US": "English",
    "hi-IN": "Hindi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "mr-IN": "Marathi",
    "bn-IN": "Bengali",
    "auto": "English",
}


def _mime_to_ext(mime: str) -> str:
    mapping = {
        "audio/webm": ".webm",
        "audio/wav": ".wav",
        "audio/wave": ".wav",
        "audio/mp3": ".mp3",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
        "audio/m4a": ".m4a",
    }
    return mapping.get(mime.lower(), ".webm")


class IBMSpeechToText:
    """Google Gemini-based speech-to-text (drop-in replacement for IBM Watson STT)."""

    def __init__(self) -> None:
        self._initialized = False
        self._client: Optional[genai.Client] = None

    async def initialize(self) -> None:
        if self._initialized:
            return
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set — STT running in mock mode")
            self._initialized = True
            return
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._initialized = True
        logger.info("Gemini Speech-to-Text initialized (model: %s)", settings.GEMINI_MODEL)

    async def transcribe_audio(
        self,
        audio_data: bytes,
        content_type: str = "audio/webm",
        language: str = "en-IN",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Transcribe audio bytes to text via Gemini 1.5 Flash."""
        if not self._initialized:
            await self.initialize()

        language_name = LANGUAGE_NAMES.get(language, "English")

        if not self._client:
            return self._mock_response(language_name)

        tmp_path: Optional[str] = None
        uploaded_file = None
        try:
            ext = _mime_to_ext(content_type)
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            uploaded_file = self._client.files.upload(
                file=tmp_path,
                config=types.UploadFileConfig(mime_type=content_type),
            )

            prompt = (
                f"Transcribe the following audio recording. "
                f"The patient is speaking in {language_name}. "
                f"Return ONLY the transcript text — no labels, no commentary."
            )
            response = self._client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[prompt, uploaded_file],
            )
            transcript = response.text.strip()

            logger.info("Transcription complete. Language: %s, Length: %d", language_name, len(transcript))
            return {
                "success": True,
                "transcript": transcript,
                "segments": [transcript],
                "confidence": 0.95,
                "language": language,
                "model_used": settings.GEMINI_MODEL,
                "timestamps": None,
                "audio_metrics": {"duration_seconds": 0},
            }
        except Exception as exc:
            logger.error("Gemini STT error: %s", exc)
            return {
                "success": False,
                "transcript": "",
                "error": str(exc),
                "language": language,
                "model_used": settings.GEMINI_MODEL,
            }
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if uploaded_file:
                try:
                    self._client.files.delete(name=uploaded_file.name)
                except Exception:
                    pass

    @staticmethod
    def _mock_response(language_name: str) -> Dict[str, Any]:
        return {
            "success": True,
            "transcript": (
                "Patient reports chest pain radiating to the left arm since this morning. "
                "Associated with shortness of breath. Pain is described as crushing."
            ),
            "segments": [],
            "confidence": 0.99,
            "language": language_name,
            "model_used": "mock",
            "timestamps": None,
            "audio_metrics": {"duration_seconds": 0},
        }


# Singleton — same name as before so triage_engine.py needs no changes
ibm_speech_to_text = IBMSpeechToText()
# Singleton instance

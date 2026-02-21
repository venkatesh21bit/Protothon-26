"""
NLU Processor (Google Gemini)
Extracts medical entities, symptoms, medications, and sentiment from
unstructured patient text using Gemini 1.5 Flash structured output.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback keyword lists (used when GEMINI_API_KEY is absent)
# ---------------------------------------------------------------------------
SYMPTOM_KEYWORDS = [
    "pain", "ache", "fever", "cough", "headache", "nausea", "vomiting",
    "dizziness", "fatigue", "weakness", "breathing", "chest", "shortness",
    "swelling", "rash", "itching", "bleeding", "numbness", "tingling",
    "cramping", "diarrhea", "constipation", "insomnia", "anxiety",
    "palpitations", "sweating", "chills", "sore throat", "congestion",
]

MEDICATION_KEYWORDS = [
    "aspirin", "ibuprofen", "paracetamol", "acetaminophen", "metformin",
    "lisinopril", "amlodipine", "omeprazole", "insulin", "levothyroxine",
    "atorvastatin", "simvastatin", "losartan", "gabapentin", "sertraline",
    "mg", "tablet", "capsule", "medication", "medicine", "prescription",
    "antibiotic", "inhaler", "drops", "syrup", "injection",
]


class NLUProcessor:
    """Google Gemini-based NLU (drop-in replacement for IBM Watson NLU)."""

    def __init__(self) -> None:
        self._initialized = False
        self._model: Optional[genai.GenerativeModel] = None

    async def initialize(self) -> None:
        if self._initialized:
            return
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set — NLU running in fallback keyword mode")
            self._initialized = True
            return
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = genai.GenerativeModel(settings.GEMINI_MODEL)
        self._initialized = True
        logger.info("Gemini NLU initialized")

    # ------------------------------------------------------------------
    # Main entry points used by triage_engine.py
    # ------------------------------------------------------------------

    async def extract_from_transcript(
        self, transcript: str
    ) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """
        Extract symptoms and medications from a voice transcript.

        Returns:
            (symptoms, medications, full_extraction_dict)
        """
        result = await self.analyze_text(transcript)
        symptoms = result.get("symptoms", [])
        medications = result.get("medications", [])
        return symptoms, medications, result

    async def process_survey_response(
        self,
        response_text: str,
        questions_answered: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Process a written survey response into extracted entities."""
        extraction = await self.analyze_text(response_text)
        return {
            "extracted_entities": extraction,
            "symptoms": extraction.get("symptoms", []),
            "medications": extraction.get("medications", []),
        }

    async def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Perform NLU analysis and return structured medical entities.

        Returns dict with: symptoms, medications, conditions, keywords,
        sentiment, allergies, duration, vital_signs.
        """
        if not self._initialized:
            await self.initialize()

        if not self._model:
            return self._fallback_extraction(text)

        prompt = f"""You are a medical NLU system. Analyze the following patient text and extract structured medical information.

Patient text:
\"\"\"{text}\"\"\"

Return a JSON object with exactly these keys:
{{
  "symptoms": ["list of symptoms mentioned"],
  "medications": ["list of medications or drugs mentioned"],
  "conditions": ["list of medical conditions or diagnoses mentioned"],
  "keywords": ["important medical keywords"],
  "sentiment": "positive|negative|neutral",
  "allergies": ["list of allergies if mentioned"],
  "durations": ["time expressions e.g. since morning, for 3 days"],
  "vital_signs": {{"temperature": null, "blood_pressure": null, "pulse": null}}
}}

Return ONLY valid JSON. No explanation."""

        try:
            response = self._model.generate_content(prompt)
            raw = response.text.strip()
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except Exception as exc:
            logger.error("Gemini NLU error: %s", exc)
            return self._fallback_extraction(text)

    # ------------------------------------------------------------------
    # Fallback: keyword-based extraction (no API key / API failure)
    # ------------------------------------------------------------------

    def _fallback_extraction(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        symptoms = [s for s in SYMPTOM_KEYWORDS if s in text_lower]
        medications = [m for m in MEDICATION_KEYWORDS if m in text_lower]
        return {
            "symptoms": symptoms,
            "medications": medications,
            "conditions": [],
            "keywords": symptoms + medications,
            "sentiment": "neutral",
            "allergies": [],
            "durations": [],
            "vital_signs": {"temperature": None, "blood_pressure": None, "pulse": None},
        }


# Singleton — same name as before so imports in triage_engine.py are unchanged
nlu_processor = NLUProcessor()

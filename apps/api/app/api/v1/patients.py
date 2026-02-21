"""
Patient endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict, Optional
from datetime import datetime
from pydantic import BaseModel
import uuid
import json
import re
import logging

from google import genai
from google.genai import types

from app.core.security import get_current_user
from app.core.db import db_client
from app.core.config import settings
from app.schemas.patient import PatientCreate, PatientResponse, PatientUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patients", tags=["patients"])

# ==================== Chat Models ====================

class ChatMessage(BaseModel):
    role: str  # 'user' or 'assistant'
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = []
    language: str = "en-IN"

class ChatResponse(BaseModel):
    response: str
    follow_up_questions: Optional[List[str]] = None
    collected_symptoms: Optional[List[str]] = None
    severity_assessment: Optional[str] = None

class ResetRequest(BaseModel):
    confirm: bool = True

# In-memory conversation storage
_conversations: Dict[str, List[Dict]] = {}
_collected_data: Dict[str, Dict] = {}

# ==================== Gemini client (lazy init) ====================

_gemini_client: Optional[genai.Client] = None

MAX_TURNS = 12  # hard ceiling — after this, wrap up regardless

# Required fields and the order in which to collect them
INTAKE_FIELDS = ["symptoms", "duration", "severity", "location", "associated_symptoms", "medical_history"]
INTAKE_THRESHOLD = 4  # minimum fields needed before intake is considered complete

def _get_gemini_client() -> Optional[genai.Client]:
    global _gemini_client
    if _gemini_client is None and settings.GEMINI_API_KEY:
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client

def _build_system_prompt(collected: Dict, turn: int, next_field: Optional[str]) -> str:
    """Build a fully explicit system prompt tailored to the current intake stage."""

    # Summarise what has already been collected so Gemini doesn't re-ask
    collected_summary = []
    if collected["symptoms"]:
        collected_summary.append(f"- Symptoms: {', '.join(collected['symptoms'])}")
    if collected["duration"]:
        collected_summary.append(f"- Duration: {collected['duration']}")
    if collected["severity"]:
        collected_summary.append(f"- Severity: {collected['severity']}/10")
    if collected["location"]:
        collected_summary.append(f"- Location: {collected['location']}")
    if collected["associated_symptoms"]:
        collected_summary.append(f"- Associated symptoms: {', '.join(collected['associated_symptoms'])}")
    if collected["medical_history"]:
        collected_summary.append(f"- Medical history / medications: {', '.join(collected['medical_history'])}")

    collected_text = "\n".join(collected_summary) if collected_summary else "Nothing collected yet."

    # Map next_field → a natural question to ask
    field_questions = {
        "symptoms":           "Ask the patient what symptoms they are experiencing.",
        "duration":           "Ask how long they have been experiencing these symptoms (e.g. hours, days, weeks).",
        "severity":           "Ask them to rate their discomfort on a scale of 1 to 10.",
        "location":           "Ask where exactly on their body they feel the symptom (which side, area).",
        "associated_symptoms":"Ask if they have any other symptoms alongside the main one (e.g. nausea, fever, dizziness).",
        "medical_history":    "Ask if they have any known medical conditions or are currently taking any medications.",
    }

    if turn >= MAX_TURNS:
        next_instruction = (
            "You have reached the maximum number of turns. "
            "Summarise everything collected and tell the patient their doctor will review the details shortly. "
            "Do NOT ask any more questions."
        )
    elif next_field:
        next_instruction = field_questions.get(next_field, "Ask the most relevant follow-up question based on what is missing.")
    else:
        next_instruction = (
            "All required information has been collected. "
            "Provide a warm closing summary of what was noted and reassure the patient their doctor will review it. "
            "Do NOT ask any more questions."
        )

    return f"""You are Nidaan AI, a compassionate medical intake assistant for an Indian clinic.
Your ONLY job is to collect patient symptom information BEFORE their doctor consultation.
You do NOT diagnose, treat, or speculate about conditions.

════════════════════════════════════════
LANGUAGE RULE
════════════════════════════════════════
Detect the language the patient writes in (Hindi, Tamil, Telugu, Marathi, Bengali, English) and reply in the SAME language.

════════════════════════════════════════
ABSOLUTE FORBIDDEN RESPONSES — never violate these
════════════════════════════════════════
1. NEVER say what disease or condition the patient might have.
   If asked ("What do I have?", "Is it serious?", "Do I have X?", "Am I okay?"):
   → Reply: "I'm not able to share diagnoses — your doctor will discuss that with you during your consultation."
2. NEVER recommend medications, dosages, or home remedies.
3. NEVER give a prognosis or tell the patient whether their condition is dangerous.
4. NEVER answer general medical knowledge questions (e.g. "What causes migraines?").
   → Reply: "That's a great question for your doctor. I'm here to note down your symptoms."
5. NEVER go off-topic (personal chat, non-medical topics, jokes).
   → Gently redirect: "I'm here to collect your health information before your consultation."
6. NEVER ask more than ONE question per reply.

════════════════════════════════════════
INFORMATION ALREADY COLLECTED THIS SESSION
════════════════════════════════════════
{collected_text}

════════════════════════════════════════
YOUR NEXT ACTION (follow this exactly)
════════════════════════════════════════
{next_instruction}

════════════════════════════════════════
EMERGENCY RULE
════════════════════════════════════════
If the patient describes severe chest pain radiating to the arm/jaw, sudden inability to speak, facial drooping, or inability to breathe — IMMEDIATELY advise them to call emergency services (112 in India) before anything else.

════════════════════════════════════════
OUTPUT FORMAT (mandatory — do not skip)
════════════════════════════════════════
Write your conversational reply to the patient FIRST.
Then, on a new line, include EXACTLY this hidden block (never shown to the patient):

<data>
{{
  "symptoms": ["extracted symptom 1", "extracted symptom 2"],
  "duration": "e.g. 2 days or null",
  "severity_score": 7,
  "location": "e.g. left side of head or null",
  "associated": ["nausea", "light sensitivity"],
  "history": ["diabetes", "paracetamol"],
  "severity_band": "HIGH|MODERATE|LOW|null",
  "intake_complete": false,
  "follow_ups": ["Short option 1", "Short option 2", "Short option 3"]
}}
</data>

Rules for the <data> block:
- Only include symptoms/details MENTIONED by the patient in this conversation.
- follow_ups are 2-3 SHORT tap-friendly quick-reply suggestions (not questions, just options like "2 days", "Left side", "No other symptoms").
- intake_complete = true only when symptoms + duration + severity are all known.
- severity_score: integer 1-10 if mentioned, else null.
"""


@router.post("/chat/reset")
async def reset_patient_chat(current_user: Dict = Depends(get_current_user)):
    """Reset patient conversation to start fresh."""
    try:
        user_id = current_user.get('user_id', 'anonymous')
        _conversations.pop(user_id, None)
        _collected_data.pop(user_id, None)
        return {"message": "Conversation reset successfully", "user_id": user_id}
    except Exception as e:
        logger.error(f"Reset error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")


def _next_missing_field(collected: Dict) -> Optional[str]:
    """Return the next intake field that still needs to be collected, in priority order."""
    if not collected["symptoms"]:
        return "symptoms"
    if not collected["duration"]:
        return "duration"
    if not collected["severity"]:
        return "severity"
    if not collected["location"]:
        return "location"
    if not collected["associated_symptoms"]:
        return "associated_symptoms"
    if not collected["medical_history"]:
        return "medical_history"
    return None  # all collected


def _fields_collected_count(collected: Dict) -> int:
    count = 0
    if collected["symptoms"]: count += 1
    if collected["duration"]: count += 1
    if collected["severity"]: count += 1
    if collected["location"]: count += 1
    if collected["associated_symptoms"]: count += 1
    if collected["medical_history"]: count += 1
    return count


@router.post("/chat", response_model=ChatResponse)
async def patient_chat(
    chat_request: ChatRequest,
    current_user: Dict = Depends(get_current_user)
):
    """AI-powered patient symptom collection chat — powered by Google Gemini."""
    try:
        user_id = current_user.get('user_id', 'anonymous')
        history = chat_request.conversation_history or []

        # Fresh conversation on first message
        if len(history) <= 1:
            _collected_data.pop(user_id, None)
            _conversations.pop(user_id, None)

        collected = _collected_data.setdefault(user_id, {
            'symptoms': [], 'duration': None, 'severity': None,
            'location': None, 'associated_symptoms': [], 'medical_history': [],
            'turn': 0, 'intake_complete': False
        })

        collected['turn'] = collected.get('turn', 0) + 1
        turn = collected['turn']

        # Determine next field to collect (None = all done or past threshold)
        next_field = None
        if not collected['intake_complete'] and turn < MAX_TURNS:
            if _fields_collected_count(collected) < INTAKE_THRESHOLD:
                next_field = _next_missing_field(collected)

        client = _get_gemini_client()

        if client:
            response_text, follow_ups, severity = await _gemini_chat(
                client, chat_request.message, history, collected, chat_request.language,
                next_field, turn
            )
        else:
            response_text = ("I'm here to help document your symptoms. "
                             "Please describe what you're experiencing — what symptoms do you have, "
                             "when did they start, and how severe are they?")
            follow_ups = ["I have a headache", "Stomach problems", "Feeling unwell"]
            severity = None

        _conversations.setdefault(user_id, []).extend([
            {'role': 'user', 'content': chat_request.message},
            {'role': 'assistant', 'content': response_text},
        ])

        return ChatResponse(
            response=response_text,
            follow_up_questions=follow_ups,
            collected_symptoms=collected['symptoms'],
            severity_assessment=severity
        )

    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


async def _gemini_chat(
    client: genai.Client,
    message: str,
    history: List[ChatMessage],
    collected: Dict,
    language: str,
    next_field: Optional[str],
    turn: int,
) -> tuple[str, List[str], Optional[str]]:
    """Call Gemini with a stage-aware system prompt and parse the structured data block."""

    # Build conversation history (cap at last 10 turns to stay within token budget)
    contents = []
    for msg in history[-10:]:
        role = "user" if msg.role == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    system_prompt = _build_system_prompt(collected, turn, next_field)

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=700,
                temperature=0.3,   # lower = more rule-following
            ),
        )
        raw = response.text or ""
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        raise

    # Strip the hidden <data> block from what the patient sees
    data_match = re.search(r"<data>\s*(\{.*?\})\s*</data>", raw, re.DOTALL)
    visible_text = re.sub(r"\s*<data>.*?</data>", "", raw, flags=re.DOTALL).strip()

    follow_ups: List[str] = []
    severity: Optional[str] = None

    if data_match:
        try:
            parsed = json.loads(data_match.group(1))

            # Merge symptoms
            for sym in parsed.get("symptoms", []):
                if sym and sym not in collected["symptoms"]:
                    collected["symptoms"].append(sym)

            # Merge duration
            dur = parsed.get("duration")
            if dur and dur != "null" and not collected["duration"]:
                collected["duration"] = dur

            # Merge severity score
            sev_score = parsed.get("severity_score")
            if sev_score and isinstance(sev_score, (int, float)) and not collected["severity"]:
                collected["severity"] = str(int(sev_score))

            # Merge location
            loc = parsed.get("location")
            if loc and loc != "null" and not collected["location"]:
                collected["location"] = loc

            # Merge associated symptoms
            for a in parsed.get("associated", []):
                if a and a not in collected["associated_symptoms"]:
                    collected["associated_symptoms"].append(a)

            # Merge medical history
            for h in parsed.get("history", []):
                if h and h not in collected["medical_history"]:
                    collected["medical_history"].append(h)

            # Severity band
            severity = parsed.get("severity_band") or None
            if severity in ("null", ""):
                severity = None

            # Intake complete flag
            if parsed.get("intake_complete") is True:
                collected["intake_complete"] = True

            follow_ups = parsed.get("follow_ups", [])

        except Exception as parse_err:
            logger.warning("Could not parse data block: %s | raw: %s", parse_err, raw[:200])

    # Auto-assess severity band from score if Gemini didn't provide one
    if not severity and collected.get("severity"):
        try:
            s = int(collected["severity"])
            severity = "CRITICAL" if s >= 9 else "HIGH" if s >= 7 else "MODERATE" if s >= 4 else "LOW"
        except ValueError:
            pass

    return visible_text, follow_ups, severity



@router.post("/", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    patient_data: PatientCreate,
    current_user: Dict = Depends(get_current_user)
):
    """Create a new patient"""
    try:
        patient_id = f"PAT_{uuid.uuid4().hex[:12].upper()}"
        
        # In production, store in a separate patients table
        # For MVP, we'll keep it simple
        
        logger.info(f"Created patient {patient_id}")
        
        return PatientResponse(
            patient_id=patient_id,
            **patient_data.dict(),
            created_at=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Error creating patient: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create patient: {str(e)}"
        )


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """Get patient details"""
    # Mock response for MVP
    return PatientResponse(
        patient_id=patient_id,
        name="Mock Patient",
        age=45,
        gender="male",
        phone="+919876543210",
        language_preference="hi-IN",
        clinic_id=current_user.get("clinic_id"),
        created_at=datetime.utcnow()
    )


@router.get("/{patient_id}/visits")
async def get_patient_visits(
    patient_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """Get all visits for a patient"""
    try:
        visits = db_client.list_patient_visits(patient_id, limit=50)
        return {"visits": visits}
        
    except Exception as e:
        logger.error(f"Error fetching patient visits: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch visits: {str(e)}"
        )

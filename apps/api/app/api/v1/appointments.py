"""
Appointments endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import uuid
import logging

from app.core.security import get_current_user
from app.core.db import save_triage_case
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/appointments", tags=["appointments"])

# ==================== Models ====================

class _ChatMsg(BaseModel):
    role: str
    content: str

class AppointmentCreate(BaseModel):
    patient_name: str
    patient_email: Optional[str] = None
    patient_phone: Optional[str] = None
    symptoms: List[str] = []
    symptom_details: Optional[str] = None
    severity: Optional[str] = None
    duration: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    notes: Optional[str] = None
    language: str = "en-IN"
    conversation_history: Optional[List[_ChatMsg]] = []

class AppointmentResponse(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    patient_email: Optional[str] = None
    patient_phone: Optional[str] = None
    symptoms: List[str] = []
    symptom_details: Optional[str] = None
    severity: Optional[str] = None
    duration: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    status: str  # pending, confirmed, completed, cancelled
    notes: Optional[str] = None
    doctor_id: Optional[str] = None
    doctor_name: Optional[str] = None
    created_at: str
    updated_at: str
    # AI Agent fields
    ai_processed: Optional[bool] = False
    ai_workflow_id: Optional[str] = None
    ai_urgency: Optional[str] = None
    ai_care_level: Optional[int] = None
    ai_department: Optional[str] = None
    ai_conditions: Optional[List[str]] = []
    ai_recommendations: Optional[List[str]] = []

class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    doctor_id: Optional[str] = None
    doctor_name: Optional[str] = None
    notes: Optional[str] = None

# ==================== In-Memory Storage ====================

# In-memory appointment storage for demo
_appointments: Dict[str, Dict] = {}

# Initialize with comprehensive sample data showing different departments
def _init_sample_appointments():
    sample_appointments = [
        # Cardiac Department - Chest Pain
        {
            "id": "APT_CARDIAC_001",
            "patient_id": "USR_PAT_001",
            "patient_name": "Rajesh Kumar",
            "patient_email": "rajesh@example.com",
            "patient_phone": "+91 9876543210",
            "symptoms": ["Chest pain", "Shortness of breath", "Left arm pain"],
            "symptom_details": "Severe chest pain radiating to left arm since morning. Difficulty breathing.",
            "severity": "9/10",
            "duration": "6 hours",
            "preferred_date": "2026-02-01",
            "preferred_time": "URGENT",
            "scheduled_date": "2026-02-01",
            "scheduled_time": "09:00 AM",
            "status": "confirmed",
            "notes": "Emergency cardiac evaluation required",
            "doctor_id": "USR_DOC_CARDIO",
            "doctor_name": "Dr. Priya Sharma",
            "created_at": "2026-02-01T06:00:00Z",
            "updated_at": "2026-02-01T06:30:00Z",
            "ai_processed": True,
            "ai_urgency": "critical",
            "ai_care_level": 1,
            "ai_department": "cardiac",
            "ai_conditions": ["Angina", "Possible MI", "Cardiac Emergency"],
            "ai_recommendations": ["Immediate ECG", "Troponin levels", "Aspirin if not contraindicated"]
        },
        # Gastro Department - Stomach Issues
        {
            "id": "APT_GASTRO_001",
            "patient_id": "USR_PAT_002",
            "patient_name": "Lakshmi Devi",
            "patient_email": "lakshmi@example.com",
            "patient_phone": "+91 9876543211",
            "symptoms": ["Abdominal pain", "Nausea", "Vomiting"],
            "symptom_details": "Severe stomach pain after meals, vomiting since yesterday",
            "severity": "7/10",
            "duration": "2 days",
            "preferred_date": "2026-02-02",
            "preferred_time": "10:00 AM",
            "scheduled_date": "2026-02-02",
            "scheduled_time": "10:30 AM",
            "status": "confirmed",
            "notes": "Suspected acute gastritis",
            "doctor_id": "USR_DOC_GASTRO",
            "doctor_name": "Dr. Amit Patel",
            "created_at": "2026-02-01T08:00:00Z",
            "updated_at": "2026-02-01T08:30:00Z",
            "ai_processed": True,
            "ai_urgency": "medium",
            "ai_care_level": 3,
            "ai_department": "gastro",
            "ai_conditions": ["Gastritis", "GERD", "Food poisoning"],
            "ai_recommendations": ["Endoscopy if persists", "PPI medication", "Bland diet"]
        },
        # Respiratory Department - Breathing Issues
        {
            "id": "APT_RESP_001",
            "patient_id": "USR_PAT_003",
            "patient_name": "Mohammad Ali",
            "patient_email": "ali@example.com",
            "patient_phone": "+91 9876543212",
            "symptoms": ["Cough", "Fever", "Breathing difficulty"],
            "symptom_details": "High fever 103°F with persistent cough and difficulty breathing for 3 days",
            "severity": "8/10",
            "duration": "3 days",
            "preferred_date": "2026-02-01",
            "preferred_time": "11:00 AM",
            "scheduled_date": "2026-02-01",
            "scheduled_time": "11:30 AM",
            "status": "confirmed",
            "notes": "Respiratory infection suspected",
            "doctor_id": "USR_DOC_RESP",
            "doctor_name": "Dr. Sunita Reddy",
            "created_at": "2026-02-01T07:00:00Z",
            "updated_at": "2026-02-01T07:30:00Z",
            "ai_processed": True,
            "ai_urgency": "high",
            "ai_care_level": 2,
            "ai_department": "respiratory",
            "ai_conditions": ["Pneumonia", "Bronchitis", "COVID-19"],
            "ai_recommendations": ["Chest X-ray", "Oxygen saturation check", "Antibiotics if bacterial"]
        },
        # Neuro Department - Head Issues
        {
            "id": "APT_NEURO_001",
            "patient_id": "USR_PAT_004",
            "patient_name": "Anita Reddy",
            "patient_email": "anita@example.com",
            "patient_phone": "+91 9876543213",
            "symptoms": ["Severe headache", "Blurred vision", "Dizziness"],
            "symptom_details": "Severe throbbing headache with visual disturbance for 2 days, worse in morning",
            "severity": "8/10",
            "duration": "2 days",
            "preferred_date": "2026-02-02",
            "preferred_time": "09:00 AM",
            "scheduled_date": "2026-02-02",
            "scheduled_time": "09:30 AM",
            "status": "confirmed",
            "notes": "Neurological evaluation needed",
            "doctor_id": "USR_DOC_NEURO",
            "doctor_name": "Dr. Vikram Singh",
            "created_at": "2026-02-01T10:00:00Z",
            "updated_at": "2026-02-01T10:30:00Z",
            "ai_processed": True,
            "ai_urgency": "high",
            "ai_care_level": 2,
            "ai_department": "neuro",
            "ai_conditions": ["Migraine", "Tension headache", "Intracranial pressure"],
            "ai_recommendations": ["CT scan if red flags", "Neurological exam", "Pain management"]
        },
        # Ortho Department - Joint Issues
        {
            "id": "APT_ORTHO_001",
            "patient_id": "USR_PAT_005",
            "patient_name": "Suresh Patel",
            "patient_email": "suresh@example.com",
            "patient_phone": "+91 9876543214",
            "symptoms": ["Joint pain", "Knee swelling", "Difficulty walking"],
            "symptom_details": "Both knees painful and swollen for 3 months, worse when climbing stairs",
            "severity": "6/10",
            "duration": "3 months",
            "preferred_date": "2026-02-03",
            "preferred_time": "02:00 PM",
            "scheduled_date": "2026-02-03",
            "scheduled_time": "02:30 PM",
            "status": "confirmed",
            "notes": "Chronic joint pain - orthopedic evaluation",
            "doctor_id": "USR_DOC_ORTHO",
            "doctor_name": "Dr. Ravi Menon",
            "created_at": "2026-02-01T11:00:00Z",
            "updated_at": "2026-02-01T11:30:00Z",
            "ai_processed": True,
            "ai_urgency": "low",
            "ai_care_level": 4,
            "ai_department": "ortho",
            "ai_conditions": ["Osteoarthritis", "Rheumatoid arthritis", "Meniscus injury"],
            "ai_recommendations": ["X-ray both knees", "RA factor test", "Physiotherapy referral"]
        },
        # General Medicine - Pending Appointment
        {
            "id": "APT_GEN_001",
            "patient_id": "USR_DEMO_PAT",
            "patient_name": "Patient Demo",
            "patient_email": "patient@nidaan.ai",
            "patient_phone": "+91 9876543215",
            "symptoms": ["Fatigue", "Weakness", "Loss of appetite"],
            "symptom_details": "Feeling very tired and weak for 2 weeks, no appetite",
            "severity": "5/10",
            "duration": "2 weeks",
            "preferred_date": "2026-02-04",
            "preferred_time": "10:00 AM",
            "scheduled_date": None,
            "scheduled_time": None,
            "status": "pending",
            "notes": "General checkup requested",
            "doctor_id": None,
            "doctor_name": None,
            "created_at": "2026-02-01T12:00:00Z",
            "updated_at": "2026-02-01T12:00:00Z",
            "ai_processed": False
        }
    ]
    
    for apt in sample_appointments:
        _appointments[apt["id"]] = apt

_init_sample_appointments()

# ==================== AI Agent Integration ====================

async def _process_with_ai_agents(appointment_data: Dict) -> Dict:
    """Process appointment through AI agents"""
    try:
        from app.services.ai_agents.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        return await orchestrator.process_appointment(appointment_data)
    except Exception as e:
        logger.error(f"AI processing error: {str(e)}")
        return None

async def _send_confirmation_emails(appointment_data: Dict):
    """Send confirmation emails to patient and doctor"""
    try:
        from app.services.email_service import get_email_service
        email_service = get_email_service()
        
        # Send patient confirmation
        patient_email = appointment_data.get('patient_email')
        if patient_email:
            patient_result = await email_service.send_appointment_confirmation(
                patient_email=patient_email,
                patient_name=appointment_data.get('patient_name', 'Patient'),
                appointment_data=appointment_data
            )
            logger.info(f"Patient email: {patient_result}")
        
        # Send doctor notification
        doctor_name = appointment_data.get('doctor_name')
        if doctor_name:
            # Demo doctor email - in production, look up from database
            doctor_email = "doctor@nidaan.ai"
            doctor_result = await email_service.send_doctor_notification(
                doctor_email=doctor_email,
                doctor_name=doctor_name,
                appointment_data=appointment_data
            )
            logger.info(f"Doctor email: {doctor_result}")
            
    except Exception as e:
        logger.error(f"Email sending error: {str(e)}")


async def _generate_soap_note(appointment_data: Dict) -> Dict:
    """Generate SOAP note from appointment data using Gemini."""
    symptoms     = appointment_data.get('symptoms', [])
    details      = appointment_data.get('symptom_details', '')
    severity     = appointment_data.get('severity', 'not specified')
    duration     = appointment_data.get('duration', 'not specified')
    history      = appointment_data.get('conversation_history', [])
    patient_name = appointment_data.get('patient_name', 'Patient')

    # Build a readable conversation transcript
    transcript_lines = []
    for msg in (history or []):
        role = msg.get('role', '')
        content = msg.get('content', '')
        prefix = 'Patient' if role == 'user' else 'AI'
        transcript_lines.append(f"{prefix}: {content}")
    conversation_text = '\n'.join(transcript_lines) or details

    fallback = {
        'subjective': f"Patient {patient_name} reports: {', '.join(symptoms)}. {details}",
        'objective':  f"Severity: {severity}. Duration: {duration}.",
        'assessment': f"Pending doctor evaluation. Reported symptoms: {', '.join(symptoms)}.",
        'plan':       "Doctor to review and provide clinical assessment."
    }

    if not settings.GEMINI_API_KEY:
        return fallback

    try:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        prompt = f"""You are a clinical documentation AI. Based on the patient intake conversation below, generate a concise SOAP note for the doctor.

Patient: {patient_name}
Symptoms reported: {', '.join(symptoms)}
Duration: {duration}
Severity: {severity}

Full intake conversation:
{conversation_text}

Respond ONLY with valid JSON (no markdown):
{{
  "subjective": "What the patient reported in their own words",
  "objective": "Measurable observations: severity score, duration, location, vital signs if mentioned",
  "assessment": "Clinical impression based on reported symptoms — do not diagnose, use phrases like 'consistent with', 'suggests', 'rule out'",
  "plan": "Recommended next steps: tests to order, referrals, follow-up"
}}"""
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=[gtypes.Content(role='user', parts=[gtypes.Part(text=prompt)])],
            config=gtypes.GenerateContentConfig(max_output_tokens=1500, temperature=0.2)
        )
        import re, json
        raw = response.text or ''
        # Robustly extract the JSON object — handles code fences, leading text, etc.
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            raise ValueError("No JSON object found in Gemini response")
        soap = json.loads(json_match.group(0))
        return soap
    except Exception as e:
        logger.warning("SOAP generation failed: %s — using fallback", e)
        return fallback


async def _create_doctor_visit(appointment_data: Dict):
    """Generate SOAP note and persist visit to PostgreSQL for the doctor dashboard."""
    try:
        urgency = appointment_data.get('ai_urgency', 'low') or 'low'
        risk_map = {'critical': 'CRITICAL', 'high': 'HIGH', 'medium': 'MODERATE', 'low': 'LOW'}
        risk_level = risk_map.get(urgency.lower(), 'LOW')

        soap = await _generate_soap_note(appointment_data)

        visit_data = {
            'visit_id':          appointment_data.get('id'),
            'clinic_id':         'CLINIC_DEMO',
            'patient_id':        appointment_data.get('patient_id'),
            'doctor_id':         appointment_data.get('doctor_id') or 'UNASSIGNED',
            'patient_name':      appointment_data.get('patient_name', 'Unknown'),
            'patient_age':       appointment_data.get('patient_age', 0),
            'chief_complaint':   ', '.join(appointment_data.get('symptoms', [])) or 'General consultation',
            'symptom_details':   appointment_data.get('symptom_details', ''),
            'status':            'pending',
            'risk_level':        risk_level,
            'severity_score':    risk_level,
            'language_code':     appointment_data.get('language', 'en-IN'),
            'transcript':        appointment_data.get('symptom_details', ''),
            'soap_note':         soap,
            'differential_diagnosis': [
                {'condition': c, 'probability': 0.6, 'reasoning': 'Reported symptom match'}
                for c in appointment_data.get('ai_conditions', [])[:3]
            ],
            'red_flags': {
                'has_red_flags': urgency in ['critical', 'high'],
                'severity': risk_level,
                'red_flags_detected': [],
                'triage_recommendation': f"Urgency: {urgency.upper()}"
            },
            'appointment_id':    appointment_data.get('id'),
            'created_at':        appointment_data.get('created_at', datetime.utcnow().isoformat()),
        }

        await save_triage_case(visit_data)
        logger.info("Saved doctor visit for appointment %s", appointment_data.get('id'))
    except Exception as e:
        logger.error("Error creating doctor visit: %s", e)

# ==================== Endpoints ====================

@router.post("", response_model=AppointmentResponse)
async def create_appointment(
    appointment: AppointmentCreate,
    current_user: Dict = Depends(get_current_user)
):
    """
    Create a new appointment request (patient submits symptoms).
    Automatically triggers AI agent processing for:
    - Symptom analysis & urgency assessment
    - Auto-scheduling based on urgency
    - Triage and department routing
    - Follow-up plan creation
    - Email confirmation to patient and doctor
    """
    try:
        apt_id = f"APT_{uuid.uuid4().hex[:8].upper()}"
        now = datetime.utcnow().isoformat() + "Z"
        
        new_appointment = {
            "id": apt_id,
            "patient_id": current_user.get("user_id"),
            "patient_name": appointment.patient_name or current_user.get("name", "Patient"),
            "patient_email": appointment.patient_email or current_user.get("email"),
            "patient_phone": appointment.patient_phone,
            "symptoms": appointment.symptoms,
            "symptom_details": appointment.symptom_details,
            "severity": appointment.severity,
            "duration": appointment.duration,
            "preferred_date": appointment.preferred_date,
            "preferred_time": appointment.preferred_time,
            "scheduled_date": None,
            "scheduled_time": None,
            "status": "pending",
            "notes": appointment.notes,
            "doctor_id": None,
            "doctor_name": None,
            "created_at": now,
            "updated_at": now,
            "ai_processed": False,
            "email_sent": False,
            # Carry conversation history for SOAP generation
            "conversation_history": [m.dict() for m in (appointment.conversation_history or [])],
            "language": appointment.language,
        }
        
        _appointments[apt_id] = new_appointment
        logger.info(f"Created appointment: {apt_id} for patient {current_user.get('user_id')}")

        # ===== ALWAYS save a visit to the doctor dashboard =====
        await _create_doctor_visit(new_appointment)
        
        # ===== AUTO-TRIGGER AI AGENTS =====
        if appointment.symptoms:
            logger.info(f"Auto-triggering AI agents for appointment: {apt_id}")
            
            ai_result = await _process_with_ai_agents(new_appointment)
            
            if ai_result and ai_result.get('final_status') == 'completed':
                # Apply AI-determined updates
                updates = ai_result.get('appointment_updates', {})
                new_appointment.update({
                    "status": updates.get('status', 'confirmed'),
                    "scheduled_date": updates.get('scheduled_date'),
                    "scheduled_time": updates.get('scheduled_time'),
                    "doctor_id": updates.get('doctor_id'),
                    "doctor_name": updates.get('doctor_name'),
                    "ai_processed": True,
                    "ai_workflow_id": ai_result.get('workflow_id'),
                    "ai_urgency": ai_result.get('summary', {}).get('urgency_assessment'),
                    "ai_care_level": updates.get('care_level'),
                    "ai_department": updates.get('department'),
                    "ai_conditions": ai_result.get('summary', {}).get('possible_conditions', []),
                    "ai_recommendations": ai_result.get('summary', {}).get('recommendations', []),
                    "updated_at": datetime.utcnow().isoformat() + "Z"
                })
                _appointments[apt_id] = new_appointment

                # Update the saved visit with AI data + refreshed SOAP
                await _create_doctor_visit(new_appointment)
                
                # ===== AUTO-SEND CONFIRMATION EMAILS =====
                if new_appointment.get('status') == 'confirmed':
                    await _send_confirmation_emails(new_appointment)
                    new_appointment['email_sent'] = True
                    _appointments[apt_id] = new_appointment
        
        return AppointmentResponse(**{k: v for k, v in new_appointment.items() if k in AppointmentResponse.__annotations__})
        
    except Exception as e:
        logger.error(f"Create appointment error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create appointment: {str(e)}"
        )


@router.get("", response_model=List[AppointmentResponse])
async def list_appointments(
    status_filter: Optional[str] = None,
    current_user: Dict = Depends(get_current_user)
):
    """
    List appointments.
    - Patients see their own appointments
    - Doctors/Admins see all appointments
    """
    try:
        role = current_user.get("role", "patient")
        user_id = current_user.get("user_id")
        
        appointments = list(_appointments.values())
        
        # Filter by role
        if role == "patient":
            appointments = [a for a in appointments if a["patient_id"] == user_id]
        
        # Filter by status
        if status_filter:
            appointments = [a for a in appointments if a["status"] == status_filter]
        
        # Sort by created_at descending
        appointments.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return [AppointmentResponse(**apt) for apt in appointments]
        
    except Exception as e:
        logger.error(f"List appointments error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list appointments: {str(e)}"
        )


@router.get("/stats")
async def get_appointment_stats(
    current_user: Dict = Depends(get_current_user)
):
    """
    Get appointment statistics (for admin dashboard)
    """
    try:
        role = current_user.get("role", "patient")
        
        if role not in ["admin", "doctor"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and doctors can view stats"
            )
        
        appointments = list(_appointments.values())
        
        stats = {
            "total": len(appointments),
            "pending": len([a for a in appointments if a["status"] == "pending"]),
            "confirmed": len([a for a in appointments if a["status"] == "confirmed"]),
            "completed": len([a for a in appointments if a["status"] == "completed"]),
            "cancelled": len([a for a in appointments if a["status"] == "cancelled"]),
            "today": len([a for a in appointments if a.get("scheduled_date") == datetime.utcnow().strftime("%Y-%m-%d")])
        }
        
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get stats error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stats: {str(e)}"
        )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Get a specific appointment
    """
    try:
        if appointment_id not in _appointments:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        appointment = _appointments[appointment_id]
        role = current_user.get("role", "patient")
        user_id = current_user.get("user_id")
        
        # Patients can only see their own appointments
        if role == "patient" and appointment["patient_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        return AppointmentResponse(**appointment)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get appointment error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get appointment: {str(e)}"
        )


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: str,
    update: AppointmentUpdate,
    current_user: Dict = Depends(get_current_user)
):
    """
    Update an appointment (doctors/admins only)
    """
    try:
        role = current_user.get("role", "patient")
        
        if role not in ["admin", "doctor"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and doctors can update appointments"
            )
        
        if appointment_id not in _appointments:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        appointment = _appointments[appointment_id]
        
        # Update fields
        if update.status:
            appointment["status"] = update.status
        if update.scheduled_date:
            appointment["scheduled_date"] = update.scheduled_date
        if update.scheduled_time:
            appointment["scheduled_time"] = update.scheduled_time
        if update.doctor_id:
            appointment["doctor_id"] = update.doctor_id
        if update.doctor_name:
            appointment["doctor_name"] = update.doctor_name
        if update.notes:
            appointment["notes"] = update.notes
        
        appointment["updated_at"] = datetime.utcnow().isoformat() + "Z"
        
        _appointments[appointment_id] = appointment
        logger.info(f"Updated appointment: {appointment_id}")
        
        return AppointmentResponse(**appointment)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update appointment error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update appointment: {str(e)}"
        )


@router.delete("/{appointment_id}")
async def cancel_appointment(
    appointment_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Cancel an appointment
    """
    try:
        if appointment_id not in _appointments:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
        
        appointment = _appointments[appointment_id]
        role = current_user.get("role", "patient")
        user_id = current_user.get("user_id")
        
        # Patients can only cancel their own appointments
        if role == "patient" and appointment["patient_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        appointment["status"] = "cancelled"
        appointment["updated_at"] = datetime.utcnow().isoformat() + "Z"
        
        _appointments[appointment_id] = appointment
        logger.info(f"Cancelled appointment: {appointment_id}")
        
        return {"message": "Appointment cancelled successfully", "id": appointment_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel appointment error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel appointment: {str(e)}"
        )

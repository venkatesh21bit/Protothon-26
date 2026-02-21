"""
Doctor dashboard endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Optional
from pydantic import BaseModel
import logging
from datetime import datetime, timedelta

from app.core.security import get_current_user, require_role
from app.core.db import fetch_triage_cases, fetch_triage_case, save_triage_case
from app.schemas.medical import VisitResponse, VisitSummary, VisitStatus, RiskLevel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("/dashboard/visits", response_model=List[VisitSummary])
async def get_dashboard_visits(
    status_filter: Optional[VisitStatus] = Query(None),
    limit: int = Query(50, le=100),
    current_user: Dict = Depends(require_role(["doctor", "admin"]))
):
    """Get visits for doctor's dashboard."""
    try:
        clinic_id = current_user.get('clinic_id', 'CLINIC_DEMO')
        visits = await fetch_triage_cases(clinic_id, limit=limit)

        if status_filter:
            visits = [v for v in visits if v.get('status', '').upper() == status_filter.upper()]

        visit_summaries = []
        for visit in visits:
            created_raw = visit.get('created_at', '')
            try:
                created_dt = datetime.fromisoformat(created_raw.replace('Z', '+00:00'))
            except Exception:
                created_dt = datetime.utcnow()

            raw_status = visit.get('status', 'PENDING')
            normalized_status = raw_status.upper() if raw_status else 'PENDING'
            # Map 'REVIEWED' → 'COMPLETED' since enums only have the above values
            status_map = {'REVIEWED': 'COMPLETED', 'PROCESSED': 'COMPLETED'}
            normalized_status = status_map.get(normalized_status, normalized_status)
            # Fallback to PENDING if value isn't a valid enum member
            valid_statuses = {v.value for v in VisitStatus}
            if normalized_status not in valid_statuses:
                normalized_status = 'PENDING'

            raw_risk = visit.get('risk_level') or visit.get('severity_score')
            normalized_risk = raw_risk.upper() if raw_risk else None
            valid_risks = {v.value for v in RiskLevel}
            if normalized_risk and normalized_risk not in valid_risks:
                normalized_risk = None

            visit_summaries.append(VisitSummary(
                visit_id=visit.get('visit_id') or visit.get('id', ''),
                patient_name=visit.get('patient_name', 'Unknown'),
                patient_age=visit.get('patient_age') or 0,
                chief_complaint=visit.get('chief_complaint', 'Processing...'),
                status=normalized_status,
                risk_level=normalized_risk,
                created_at=created_dt,
                has_red_flags=bool(visit.get('red_flags', {}).get('has_red_flags', False))
            ))

        return visit_summaries

    except Exception as e:
        logger.error(f"Error fetching dashboard visits: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch visits: {str(e)}")


@router.get("/visits/{visit_id}", response_model=VisitResponse)
async def get_visit_details(
    visit_id: str,
    current_user: Dict = Depends(require_role(["doctor", "admin"]))
):
    """Get detailed SOAP note and full data for a specific visit."""
    try:
        visit = await fetch_triage_case(visit_id)

        if not visit:
            raise HTTPException(status_code=404, detail=f"Visit {visit_id} not found")

        from app.schemas.medical import SOAPNote, DifferentialDiagnosis, RedFlagAnalysis, RedFlag

        def transform_differential(dd_list):
            if not dd_list:
                return None
            out = []
            for dd in dd_list:
                out.append(DifferentialDiagnosis(
                    diagnosis=dd.get('diagnosis') or dd.get('condition') or 'Unknown',
                    probability=str(dd.get('probability', 'MEDIUM')),
                    supporting_factors=dd.get('supporting_factors') or ['Based on symptoms'],
                    against=dd.get('against') or ['Requires confirmation'],
                    next_steps=dd.get('next_steps') or ['Clinical evaluation']
                ))
            return out

        def transform_red_flags(rf_list):
            if not rf_list:
                return []
            out = []
            for rf in rf_list:
                out.append(RedFlag(
                    category=rf.get('category', 'General'),
                    finding=rf.get('finding') or rf.get('description', 'Alert'),
                    urgency=rf.get('urgency', 'ROUTINE'),
                    action=rf.get('action') or rf.get('recommendation', 'Evaluate')
                ))
            return out

        def parse_dt(s):
            if not s:
                return datetime.utcnow()
            try:
                return datetime.fromisoformat(s.replace('Z', '+00:00'))
            except Exception:
                return datetime.utcnow()

        soap_data = visit.get('soap_note')
        soap = SOAPNote(**soap_data) if isinstance(soap_data, dict) else None

        # Normalize status to uppercase enum value
        _valid_statuses = {v.value for v in VisitStatus}
        _status_map = {'REVIEWED': 'COMPLETED', 'PROCESSED': 'COMPLETED'}
        _raw_status = (visit.get('status') or 'PENDING').upper()
        _norm_status = _status_map.get(_raw_status, _raw_status)
        if _norm_status not in _valid_statuses:
            _norm_status = 'PENDING'

        # Normalize risk_level to uppercase enum value
        _valid_risks = {v.value for v in RiskLevel}
        _raw_risk = (visit.get('risk_level') or visit.get('severity_score') or '')
        _norm_risk = _raw_risk.upper() if _raw_risk else None
        if _norm_risk and _norm_risk not in _valid_risks:
            _norm_risk = None

        # Normalize red_flags severity
        _rf_data = visit.get('red_flags') or {}
        _rf_severity_raw = (_rf_data.get('severity') or 'ROUTINE').upper()
        _rf_severity = _rf_severity_raw if _rf_severity_raw in _valid_risks else 'ROUTINE'

        return VisitResponse(
            visit_id=visit.get('visit_id') or visit.get('id', ''),
            patient_id=visit.get('patient_id', ''),
            clinic_id=visit.get('clinic_id', ''),
            doctor_id=visit.get('doctor_id'),
            status=_norm_status,
            language_code=visit.get('language_code', 'en-IN'),
            audio_s3_key=visit.get('audio_s3_key'),
            transcript=visit.get('transcript'),
            translated_text=visit.get('translated_text') or visit.get('transcript'),
            soap_note=soap,
            differential_diagnosis=transform_differential(visit.get('differential_diagnosis')),
            red_flags=RedFlagAnalysis(
                has_red_flags=bool(_rf_data.get('has_red_flags', False)),
                severity=_rf_severity,
                red_flags_detected=transform_red_flags(_rf_data.get('red_flags_detected', [])),
                triage_recommendation=_rf_data.get('triage_recommendation', '')
            ) if _rf_data else None,
            risk_level=_norm_risk,
            created_at=parse_dt(visit.get('created_at')),
            updated_at=parse_dt(visit.get('updated_at') or visit.get('created_at')),
            processing_time_seconds=visit.get('processing_time_seconds')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching visit details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch visit details: {str(e)}")


@router.get("/stats/summary")
async def get_dashboard_stats(
    current_user: Dict = Depends(require_role(["doctor", "admin"]))
):
    """Summary statistics for the doctor dashboard."""
    try:
        clinic_id = current_user.get('clinic_id', 'CLINIC_DEMO')
        visits = await fetch_triage_cases(clinic_id, limit=200)

        today = datetime.utcnow().date()

        def parse_dt(s):
            try:
                return datetime.fromisoformat(s.replace('Z', '+00:00'))
            except Exception:
                return datetime.utcnow()

        today_visits     = [v for v in visits if parse_dt(v.get('created_at', '')).date() == today]
        pending_count    = len([v for v in visits if v.get('status', '').lower() == 'pending'])
        high_risk_count  = len([v for v in visits if v.get('risk_level') in ['HIGH', 'CRITICAL']])
        critical_count   = len([v for v in visits if v.get('risk_level') == 'CRITICAL'])

        return {
            "total_visits_today": len(today_visits),
            "pending_visits":     pending_count,
            "pending_reviews":    pending_count,
            "high_risk_visits":   high_risk_count,
            "critical_alerts":    critical_count,
            "completed_today":    len([v for v in today_visits if v.get('status', '').lower() == 'completed']),
            "clinic_id":          clinic_id
        }

    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch statistics: {str(e)}")


class VisitUpdateRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


@router.patch("/visits/{visit_id}")
async def update_visit_status(
    visit_id: str,
    update_data: VisitUpdateRequest,
    current_user: Dict = Depends(require_role(["doctor", "admin"]))
):
    """Update visit status (e.g., mark as reviewed/completed)."""
    try:
        visit = await fetch_triage_case(visit_id)
        if not visit:
            raise HTTPException(status_code=404, detail=f"Visit {visit_id} not found")

        if update_data.status:
            valid = ['pending', 'processing', 'completed', 'reviewed']
            if update_data.status.lower() not in valid:
                raise HTTPException(status_code=400, detail=f"Invalid status. Use: {valid}")
            visit['status'] = update_data.status.lower()

        if update_data.notes:
            visit['doctor_notes'] = update_data.notes

        visit['updated_at'] = datetime.utcnow().isoformat()
        await save_triage_case(visit)

        return {"message": "Visit updated successfully", "visit_id": visit_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating visit: {str(e)}")

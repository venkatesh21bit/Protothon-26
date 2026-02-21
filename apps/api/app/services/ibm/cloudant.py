"""
Database Service (PostgreSQL)
Drop-in replacement for the IBM Cloudant service.
Keeps the same public API so triage_engine.py and routes need no changes.
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.utcnow().isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class CloudantService:
    """PostgreSQL-backed document store (API-compatible with the IBM Cloudant version)."""

    def __init__(self) -> None:
        self._initialized = False

    async def initialize(self) -> None:
        """No-op — tables are created by db.create_tables() at startup."""
        self._initialized = True
        logger.info("CloudantService (PostgreSQL) ready")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _insert(self, table: str, row_id: str, data: Dict[str, Any], **cols) -> Dict[str, Any]:
        """Insert a JSONB document row and return it."""
        now = _now()
        async with AsyncSessionLocal() as session:
            col_names = ["id", "data", "created_at", "updated_at"] + list(cols.keys())
            placeholders = ", ".join(f":{c}" for c in col_names)
            col_list = ", ".join(col_names)
            stmt = text(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) RETURNING *"
            )
            params = {"id": row_id, "data": json.dumps(data), "created_at": now, "updated_at": now, **cols}
            result = await session.execute(stmt, params)
            await session.commit()
        row = dict(result.mappings().first())
        doc = json.loads(row["data"])
        doc["_id"] = row["id"]
        doc["id"] = row["id"]
        doc["created_at"] = str(row.get("created_at", now))
        doc["updated_at"] = str(row.get("updated_at", now))
        return doc

    async def _get(self, table: str, row_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"SELECT * FROM {table} WHERE id = :id"), {"id": row_id}
            )
            row = result.mappings().first()
        if not row:
            return None
        doc = json.loads(row["data"])
        doc["_id"] = row["id"]
        doc["id"] = row["id"]
        doc["created_at"] = str(row.get("created_at", ""))
        doc["updated_at"] = str(row.get("updated_at", ""))
        return doc

    async def _update(self, table: str, row_id: str, patch: Dict[str, Any], **col_updates) -> Dict[str, Any]:
        """Merge patch into the JSONB data column and update indexed columns."""
        existing = await self._get(table, row_id)
        if not existing:
            raise ValueError(f"{table} row {row_id} not found")
        merged = {**existing, **patch}
        merged.pop("_id", None)
        merged.pop("id", None)
        now = _now()
        merged["updated_at"] = now

        set_clauses = ["data = :data", "updated_at = :updated_at"]
        params: Dict[str, Any] = {"id": row_id, "data": json.dumps(merged), "updated_at": now}
        for k, v in col_updates.items():
            set_clauses.append(f"{k} = :{k}")
            params[k] = v

        async with AsyncSessionLocal() as session:
            await session.execute(
                text(f"UPDATE {table} SET {', '.join(set_clauses)} WHERE id = :id"),
                params,
            )
            await session.commit()

        merged["_id"] = row_id
        merged["id"] = row_id
        return merged

    # ------------------------------------------------------------------
    # TRIAGE CASE OPERATIONS
    # ------------------------------------------------------------------

    async def create_triage_case(
        self,
        patient_id: str,
        patient_name: str,
        symptoms: List[str],
        medications: List[str],
        transcript: str,
        severity_score: str,
        red_flags: List[str],
        extracted_entities: Dict[str, Any],
        appointment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        case_id = _new_id("triage")
        data = {
            "type": "triage_case",
            "patient_id": patient_id,
            "patient_name": patient_name,
            "symptoms": symptoms,
            "medications": medications,
            "transcript": transcript,
            "severity_score": severity_score,
            "red_flags": red_flags,
            "extracted_entities": extracted_entities,
            "appointment_id": appointment_id,
            "status": "pending",
            "nurse_alerted": severity_score == "HIGH",
            "doctor_notes": None,
        }
        return await self._insert(
            "triage_cases",
            case_id,
            data,
            patient_id=patient_id,
            severity_score=severity_score,
            nurse_alerted=(severity_score == "HIGH"),
        )

    async def get_triage_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        return await self._get("triage_cases", case_id)

    async def get_urgent_cases(self) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT * FROM triage_cases "
                    "WHERE severity_score = 'HIGH' AND status != 'seen' "
                    "ORDER BY created_at DESC LIMIT 50"
                )
            )
            rows = result.mappings().all()
        cases = []
        for row in rows:
            doc = json.loads(row["data"])
            doc["_id"] = row["id"]
            doc["id"] = row["id"]
            doc["created_at"] = str(row.get("created_at", ""))
            cases.append(doc)
        logger.info("Found %d urgent cases", len(cases))
        return cases

    async def get_cases_by_severity(self, severity: str) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT * FROM triage_cases WHERE severity_score = :sev ORDER BY created_at DESC"),
                {"sev": severity},
            )
            rows = result.mappings().all()
        return [dict(json.loads(r["data"]), _id=r["id"], id=r["id"]) for r in rows]

    async def update_case_status(
        self, case_id: str, status: str, doctor_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        patch: Dict[str, Any] = {"status": status}
        if doctor_notes:
            patch["doctor_notes"] = doctor_notes
        return await self._update("triage_cases", case_id, patch, status=status)

    async def mark_case_as_seen(self, case_id: str) -> Dict[str, Any]:
        return await self.update_case_status(case_id, "seen")

    # ------------------------------------------------------------------
    # SURVEY OPERATIONS
    # ------------------------------------------------------------------

    async def create_survey(
        self,
        patient_id: str,
        patient_email: str,
        appointment_id: str,
        survey_questions: List[Dict[str, str]],
        patient_history: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        survey_id = _new_id("survey")
        data = {
            "type": "survey",
            "patient_id": patient_id,
            "patient_email": patient_email,
            "appointment_id": appointment_id,
            "survey_questions": survey_questions,
            "patient_history": patient_history,
            "status": "pending",
            "sent_at": _now(),
            "response": None,
            "response_received_at": None,
            "processed": False,
        }
        return await self._insert(
            "surveys", survey_id, data,
            patient_id=patient_id, appointment_id=appointment_id,
        )

    async def get_survey(self, survey_id: str) -> Optional[Dict[str, Any]]:
        return await self._get("surveys", survey_id)

    async def update_survey_response(
        self, survey_id: str, response_text: str, extracted_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        patch = {
            "response": response_text,
            "extracted_data": extracted_data,
            "response_received_at": _now(),
            "status": "completed",
            "processed": True,
        }
        return await self._update("surveys", survey_id, patch, status="completed")

    async def get_pending_surveys(self) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT * FROM surveys WHERE status = 'pending' ORDER BY created_at ASC")
            )
            rows = result.mappings().all()
        return [dict(json.loads(r["data"]), _id=r["id"], id=r["id"]) for r in rows]

    # ------------------------------------------------------------------
    # APPOINTMENT OPERATIONS
    # ------------------------------------------------------------------

    async def create_appointment(
        self,
        patient_id: str,
        patient_name: str,
        patient_email: str,
        doctor_id: str,
        appointment_date: str,
        appointment_time: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        appt_id = _new_id("appt")
        data = {
            "type": "appointment",
            "patient_id": patient_id,
            "patient_name": patient_name,
            "patient_email": patient_email,
            "doctor_id": doctor_id,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
            "reason": reason,
            "status": "scheduled",
            "survey_id": None,
            "triage_case_id": None,
        }
        return await self._insert(
            "appointments", appt_id, data,
            patient_id=patient_id, doctor_id=doctor_id,
        )

    async def get_appointment(self, appointment_id: str) -> Optional[Dict[str, Any]]:
        return await self._get("appointments", appointment_id)

    async def link_survey_to_appointment(
        self, appointment_id: str, survey_id: str
    ) -> Dict[str, Any]:
        return await self._update(
            "appointments", appointment_id,
            {"survey_id": survey_id, "status": "survey_sent"},
            survey_id=survey_id, status="survey_sent",
        )

    async def link_triage_to_appointment(
        self, appointment_id: str, triage_case_id: str
    ) -> Dict[str, Any]:
        return await self._update(
            "appointments", appointment_id,
            {"triage_case_id": triage_case_id},
            triage_case_id=triage_case_id,
        )

    # ------------------------------------------------------------------
    # EHR / PATIENT HISTORY
    # ------------------------------------------------------------------

    async def update_patient_ehr(
        self, patient_id: str, triage_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        ehr_id = _new_id("ehr_update")
        data = {
            "type": "ehr_update",
            "patient_id": patient_id,
            "summary": {
                "chief_complaint": triage_summary.get("symptoms", []),
                "current_medications": triage_summary.get("medications", []),
                "allergies": triage_summary.get("allergies", []),
                "vital_signs_reported": triage_summary.get("vital_signs", {}),
                "pain_level": triage_summary.get("pain_level"),
                "symptom_duration": triage_summary.get("duration"),
                "pre_visit_notes": triage_summary.get("notes", ""),
            },
            "severity_assessment": triage_summary.get("severity_score"),
            "red_flags_detected": triage_summary.get("red_flags", []),
            "source": "automated_triage",
        }
        async with AsyncSessionLocal() as session:
            now = _now()
            await session.execute(
                text(
                    "INSERT INTO ehr_updates (id, patient_id, data, created_at) "
                    "VALUES (:id, :patient_id, :data, :created_at)"
                ),
                {"id": ehr_id, "patient_id": patient_id, "data": json.dumps(data), "created_at": now},
            )
            await session.commit()
        data["_id"] = ehr_id
        data["id"] = ehr_id
        return data

    async def get_patient_history(self, patient_id: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        async with AsyncSessionLocal() as session:
            for table in ("triage_cases", "surveys", "ehr_updates"):
                rows = (await session.execute(
                    text(f"SELECT * FROM {table} WHERE patient_id = :pid ORDER BY created_at DESC LIMIT 20"),
                    {"pid": patient_id},
                )).mappings().all()
                for row in rows:
                    doc = json.loads(row["data"])
                    doc["_id"] = row["id"]
                    doc["id"] = row["id"]
                    results.append(doc)
        return results


# Singleton — same name as before
cloudant_service = CloudantService()

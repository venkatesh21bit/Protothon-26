"""
Database Module — PostgreSQL via SQLAlchemy Async
Replaces the previous DynamoDB-based implementation.
"""
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Table DDL — created on startup
# ---------------------------------------------------------------------------

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS triage_cases (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL,
    severity_score TEXT NOT NULL DEFAULT 'LOW',
    status        TEXT NOT NULL DEFAULT 'pending',
    nurse_alerted BOOLEAN NOT NULL DEFAULT FALSE,
    data          JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_triage_cases_patient
    ON triage_cases (patient_id);
CREATE INDEX IF NOT EXISTS idx_triage_cases_severity_status
    ON triage_cases (severity_score, status);

CREATE TABLE IF NOT EXISTS surveys (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL,
    appointment_id  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    data            JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_surveys_patient
    ON surveys (patient_id);
CREATE INDEX IF NOT EXISTS idx_surveys_appointment
    ON surveys (appointment_id);

CREATE TABLE IF NOT EXISTS appointments (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL,
    doctor_id       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'scheduled',
    survey_id       TEXT,
    triage_case_id  TEXT,
    data            JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_appointments_patient
    ON appointments (patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor
    ON appointments (doctor_id);

CREATE TABLE IF NOT EXISTS ehr_updates (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL,
    data        JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ehr_patient
    ON ehr_updates (patient_id);
"""


async def create_tables() -> None:
    """Create all tables (idempotent — safe to call on every startup).
    SQLAlchemy 2.x execute() only supports one statement per call, so we split.
    """
    statements = [s.strip() for s in _CREATE_TABLES_SQL.split(";") if s.strip()]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))
    logger.info("Database tables created / verified")


# ---------------------------------------------------------------------------
# Real async DB helpers — used by visits/doctor dashboard
# ---------------------------------------------------------------------------

import json as _json

async def save_triage_case(data: dict) -> None:
    """Insert or replace a triage case (visit) in PostgreSQL."""
    case_id    = data.get("visit_id") or data.get("id")
    patient_id = data.get("patient_id", "unknown")
    severity   = data.get("severity_score") or data.get("risk_level", "LOW")
    visit_status = data.get("status", "pending")

    sql = text("""
        INSERT INTO triage_cases (id, patient_id, severity_score, status, data, created_at, updated_at)
        VALUES (:id, :patient_id, :severity_score, :status, CAST(:data_json AS jsonb), NOW(), NOW())
        ON CONFLICT (id) DO UPDATE
        SET severity_score = EXCLUDED.severity_score,
            status         = EXCLUDED.status,
            data           = EXCLUDED.data,
            updated_at     = NOW()
    """)
    async with engine.begin() as conn:
        await conn.execute(sql, {
            "id":            case_id,
            "patient_id":    patient_id,
            "severity_score": severity,
            "status":        visit_status,
            "data_json":     _json.dumps(data),
        })
    logger.info("Saved triage case %s", case_id)


async def fetch_triage_cases(clinic_id: str, limit: int = 50) -> list:
    """Return all triage cases as dicts, newest first."""
    sql = text("""
        SELECT data, created_at
        FROM triage_cases
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    async with AsyncSessionLocal() as session:
        result = await session.execute(sql, {"limit": limit})
        rows = result.fetchall()

    cases = []
    for row in rows:
        try:
            rec = row[0] if isinstance(row[0], dict) else _json.loads(row[0])
            if not rec.get("created_at"):
                rec["created_at"] = row[1].isoformat() if row[1] else ""
            cases.append(rec)
        except Exception:
            pass
    return cases


async def fetch_triage_case(visit_id: str) -> dict | None:
    """Return a single triage case by visit_id, or None."""
    sql = text("SELECT data FROM triage_cases WHERE id = :id")
    async with AsyncSessionLocal() as session:
        result = await session.execute(sql, {"id": visit_id})
        row = result.fetchone()
    if not row:
        return None
    rec = row[0] if isinstance(row[0], dict) else _json.loads(row[0])
    return rec


# ---------------------------------------------------------------------------
# Kept for backward compat — callers that import db_client get a no-op stub
# ---------------------------------------------------------------------------

class _NoOpDBClient:
    """Stub so that any stray `from app.core.db import db_client` doesn't crash.
    Returns empty/safe values so routes that still call db_client don't 500.
    Real data access should go through save_triage_case / fetch_triage_cases.
    """
    class _NoOpCallable:
        def __call__(self, *args, **kwargs):
            return []
        def __iter__(self):
            return iter([])

    def __getattr__(self, name):
        return self._NoOpCallable()


db_client = _NoOpDBClient()
# END OF FILE


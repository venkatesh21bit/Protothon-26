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
    """Create all tables (idempotent — safe to call on every startup)."""
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_TABLES_SQL))
    logger.info("Database tables created / verified")


# ---------------------------------------------------------------------------
# Kept for backward compat — callers that import db_client get a no-op stub
# ---------------------------------------------------------------------------

class _NoOpDBClient:
    """Stub so that any stray `from app.core.db import db_client` doesn't crash."""
    def __getattr__(self, name):  # noqa: D105
        raise AttributeError(
            f"DynamoDB client was removed. Use AsyncSessionLocal instead. "
            f"Attribute requested: {name}"
        )


db_client = _NoOpDBClient()
# END OF FILE — original DynamoDB code removed


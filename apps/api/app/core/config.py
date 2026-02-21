"""
Core Configuration Module
Manages environment variables and application settings
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application Settings"""

    # Application
    APP_NAME: str = "Nidaan.ai"
    APP_VERSION: str = "1.0.0"
    ENV: str = "development"
    DEBUG: bool = True
    APP_BASE_URL: str = "http://localhost:3000"  # Frontend URL for survey links

    # API
    API_V1_PREFIX: str = "/api/v1"

    # Security
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24  # 24 hours

    # ==================== Google Gemini (LLM + STT + NLU) ====================
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3-flash-preview"

    # ==================== PostgreSQL Database ====================
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nidaan"

    # ==================== Local File Storage ====================
    STORAGE_PATH: str = "./uploads"  # Local directory for uploaded audio files

    # ==================== Email Configuration (SMTP) ====================
    # Using Gmail SMTP for patient outreach
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_EMAIL: str = ""  # set via SMTP_EMAIL env var
    SMTP_PASSWORD: str = ""  # set via SMTP_PASSWORD env var — never commit real passwords

    # Nurse Station Alert Email
    NURSE_STATION_EMAIL: str = "nurse.station@hospital.com"

    # ==================== Redis ====================
    REDIS_URL: str = "redis://localhost:6379"

    # ==================== CORS ====================
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://nidaan.ai",
    ]

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

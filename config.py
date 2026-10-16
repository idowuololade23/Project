from datetime import timedelta
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development").lower()
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'instance' / 'analyses.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024
    MAX_TEXT_LENGTH = 100_000
    MAX_EXTRACTED_LENGTH = 100_000
    REQUEST_TIMEOUT = (5, 15)
    MAX_REDIRECTS = 5
    DYNAMIC_EXTRACTION_ENABLED = os.environ.get("DYNAMIC_EXTRACTION_ENABLED", "true").lower() == "true"
    DYNAMIC_EXTRACTION_MIN_WORDS = 40
    DYNAMIC_EXTRACTION_TIMEOUT_MS = 15_000
    PERMANENT_SESSION_LIFETIME = timedelta(days=400)
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    ANALYSIS_RATE_LIMIT = os.environ.get("ANALYSIS_RATE_LIMIT", "10 per hour")
    RATELIMIT_HEADERS_ENABLED = True
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
    MAX_FORM_MEMORY_SIZE = 1 * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get(
        "COOKIE_SECURE", "true" if APP_ENV == "production" else "false"
    ).lower() == "true"


class TestingConfig(Config):
    TESTING = True
    APP_ENV = "testing"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    DYNAMIC_EXTRACTION_ENABLED = False

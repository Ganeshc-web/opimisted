import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CACHE_TYPE = "SimpleCache"
    API_VERSION = "1.0.0"
    REPORTS_FOLDER = os.environ.get("REPORTS_FOLDER", "reports/")

    # SMTP (report email) — set via environment variables
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    try:
        SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    except (TypeError, ValueError):
        SMTP_PORT = 587
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    EMAIL_FROM = os.environ.get("EMAIL_FROM") or os.environ.get("SMTP_USER")

    # Daily cap on client report emails (download/generate with consent)
    try:
        REPORT_EMAIL_DAILY_LIMIT = int(os.environ.get("REPORT_EMAIL_DAILY_LIMIT", "499"))
    except (TypeError, ValueError):
        REPORT_EMAIL_DAILY_LIMIT = 499
    REPORT_EMAIL_QUOTA_TZ = os.environ.get("REPORT_EMAIL_QUOTA_TZ", "Asia/Kolkata")

    # S3 report storage (Lightsail production + optional Vercel interim)
    AWS_S3_BUCKET = os.environ.get("AWS_S3_BUCKET")
    AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
    AWS_S3_REPORT_PREFIX = os.environ.get("AWS_S3_REPORT_PREFIX", "reports")


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///financial.db"


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    # Lightsail: persistent disk path for generated reports (before S3 upload)
    REPORTS_FOLDER = os.environ.get("REPORTS_FOLDER", "/var/www/financial_api/reports")
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    }


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}

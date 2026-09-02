import os
import sys
from decimal import Decimal
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-secret-key")
DEBUG = False
ALLOWED_HOSTS = [
    value.strip()
    for value in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if value.strip()
]
CSRF_TRUSTED_ORIGINS = [
    value.strip()
    for value in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if value.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "storages",
    "core",
    "accounts",
    "recruitment",
    "analysis",
    "reviews",
    "talent_pool",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.SessionVersionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation_counts",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=int(os.getenv("CONN_MAX_AGE", "60")),
        conn_health_checks=True,
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("timeout", 30)
    DATABASES["default"]["OPTIONS"].setdefault(
        "init_command", "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=30000"
    )

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.LockoutModelBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
INITIAL_REFERENCE_DOCUMENT_PATH = os.getenv(
    "INITIAL_REFERENCE_DOCUMENT_PATH",
    str(BASE_DIR / "docs" / "招聘信息汇总.docx"),
)

if os.getenv("USE_S3_STORAGE", "false").lower() == "true":
    from botocore.config import Config

    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "us-east-1")
    AWS_S3_ADDRESSING_STYLE = "path"
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 300
    AWS_DEFAULT_ACL = None
    AWS_S3_CLIENT_CONFIG = Config(
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=10,
        read_timeout=30,
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "智筛招聘 <smart-screening@example.com>"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "false").lower() == "true"
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "true").lower() == "true"
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TIMEZONE = TIME_ZONE
LOCAL_BACKGROUND_TASKS = (
    os.getenv("LOCAL_BACKGROUND_TASKS", "false").lower() == "true"
    and "test" not in sys.argv
)
CELERY_BEAT_SCHEDULE = {
    "incremental-resume-sync-every-10-minutes": {
        "task": "recruitment.tasks.schedule_incremental_sync",
        "schedule": 600.0,
    },
    "position-sync-hourly": {
        "task": "recruitment.tasks.schedule_position_sync",
        "schedule": 3600.0,
    },
    "daily-reconciliation": {
        "task": "recruitment.tasks.schedule_reconciliation_sync",
        "schedule": 86400.0,
    },
    "daily-data-cleanup": {
        "task": "recruitment.tasks.purge_deleted_applications_task",
        "schedule": 86400.0,
    },
}

PUBLIC_REVIEW_BASE_URL = os.getenv("PUBLIC_REVIEW_BASE_URL", "http://localhost:8000")
ITALENT_BASE_URL = os.getenv("ITALENT_BASE_URL", "https://openapi.italent.cn")
ITALENT_APP_KEY = os.getenv("ITALENT_APP_KEY", "")
ITALENT_APP_SECRET = os.getenv("ITALENT_APP_SECRET", "")
ITALENT_APPLICATIONS_ENDPOINT = os.getenv(
    "ITALENT_APPLICATIONS_ENDPOINT",
    "/RecruitV6/api/v1/Apply/GetApplyListByApplicantId",
)
ITALENT_POSITIONS_ENDPOINT = os.getenv(
    "ITALENT_POSITIONS_ENDPOINT",
    "/RecruitV6/api/v1/Job/GetJobListByIds",
)
ITALENT_REQUIREMENTS_ENDPOINT = os.getenv("ITALENT_REQUIREMENTS_ENDPOINT", "")
ITALENT_APPLICATION_FIELDS = [
    value.strip()
    for value in os.getenv(
        "ITALENT_APPLICATION_FIELDS",
        (
            "InitialSubmissionDate,InitialSubmissionChannel,"
            "InitialSubmissionMedium,BelongSubmissionDate,"
            "BelongSubmissionChannel,LastSubmissionDate,"
            "LastSubmissionChannel,CreatedTime,Status,RecruitRequirementId"
        ),
    ).split(",")
    if value.strip()
]
ITALENT_RESUME_MODULES = [
    value.strip()
    for value in os.getenv(
        "ITALENT_RESUME_MODULES",
        (
            "ApplicantObjective,ApplicantEducation,ApplicantWorkExperience,"
            "ApplicantProject,ApplicantInternship,Train,Skill,Lang,"
            "Certificate,ApplicantAwards"
        ),
    ).split(",")
    if value.strip()
]

MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "")
MODEL_NAME = os.getenv("MODEL_NAME", "")
MODEL_REQUEST_TIMEOUT = float(os.getenv("MODEL_REQUEST_TIMEOUT", "90"))
AUTO_GENERATE_INITIAL_RULES = (
    os.getenv("AUTO_GENERATE_INITIAL_RULES", "true").lower() == "true"
    and "test" not in sys.argv
)
MODEL_INPUT_COST_PER_MILLION = Decimal(
    os.getenv("MODEL_INPUT_COST_PER_MILLION", "0")
)
MODEL_OUTPUT_COST_PER_MILLION = Decimal(
    os.getenv("MODEL_OUTPUT_COST_PER_MILLION", "0")
)

TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    "loggers": {
        "httpx": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "httpcore": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

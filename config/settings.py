"""
Django settings for the travel app.

All deployment-specific values come from environment variables (see .env.example),
so the same code runs locally and on the live server.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
TESTING = "test" in sys.argv[1:2]


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "django-insecure-dev-only-key"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Absolute base URL used in emails and WhatsApp replies.
SITE_URL = os.environ.get("SITE_URL", "https://trips.aquiles.me").rstrip("/")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_tasks_db",
    "allauth",
    "allauth.account",
    "allauth.headless",
    "accounts",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every view needs a login unless marked @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "allauth.account.middleware.AccountMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database: Postgres, configured via DATABASE_URL (built in compose.yaml).

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Database cache (parsed GPX tracks). Table created by `createcachetable`.
CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.locmem.LocMemCache"
            if TESTING
            else "django.core.cache.backends.db.DatabaseCache"
        ),
        "LOCATION": "django_cache",
        "TIMEOUT": 60 * 60 * 24 * 30,
    }
}


# Background tasks: stored in Postgres, run by the `worker` container.

TASKS = {
    "default": {
        "BACKEND": (
            "django.tasks.backends.immediate.ImmediateBackend"
            if TESTING
            else "django_tasks_db.DatabaseBackend"
        ),
    }
}


# Authentication

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",  # admin
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# django-allauth: email login, invite-only (no public signup), reset by email link.
ACCOUNT_ADAPTER = "accounts.adapter.AccountAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = False
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Trips] "
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

# allauth headless API for the iPhone app: /_allauth/app/v1/... with session tokens
# (X-Session-Token header). Browser pages keep using the normal allauth views.
HEADLESS_CLIENTS = ("app",)
HEADLESS_ONLY = False


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Europe/Amsterdam")
USE_I18N = True
USE_TZ = True


# Static files, served by WhiteNoise from inside the web container.

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Media lives on the `media` volume. It is never served directly: views check
# access, then hand the file to nginx via X-Accel-Redirect.
MEDIA_URL = "/protected/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_ACCEL_REDIRECT = env_bool("MEDIA_ACCEL_REDIRECT", not DEBUG)
BACKUP_DIR = MEDIA_ROOT / "backups"
BACKUP_KEEP = 14

# Upload limits.
UPLOAD_CHUNK_MAX_BYTES = 50 * 1024 * 1024
GPX_MAX_BYTES = 50 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = GPX_MAX_BYTES + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024


# Email (Mailgun SMTP in production, console when debugging).

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Trips <trips@localhost>")
if os.environ.get("EMAIL_HOST") and not DEBUG:
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": os.environ["EMAIL_HOST"],
                "port": int(os.environ.get("EMAIL_PORT", "587")),
                "username": os.environ.get("EMAIL_HOST_USER", ""),
                "password": os.environ.get("EMAIL_HOST_PASSWORD", ""),
                "use_tls": env_bool("EMAIL_USE_TLS", True),
                "timeout": 30,
            },
        },
    }
else:
    MAILERS = {
        "default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"},
    }


# WhatsApp via Twilio.

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")  # e.g. whatsapp:+14155238886
# The exact URL configured in Twilio; used to verify request signatures.
TWILIO_WEBHOOK_URL = os.environ.get("TWILIO_WEBHOOK_URL", f"{SITE_URL}/hooks/twilio/whatsapp/")
WHATSAPP_GROUP_MINUTES = 10
WHATSAPP_MEDIA_MAX_BYTES = 25 * 1024 * 1024


# Scheduler (times are Europe/Amsterdam).

SCHEDULE_TIME_ZONE = "Europe/Amsterdam"
SCHEDULE = [
    # (name, "HH:MM", task import path)
    ("nightly_backup", "03:00", "trips.tasks.nightly_backup"),
    ("daily_digests", "20:00", "trips.tasks.send_daily_digests"),
]


# Behind the Cloudflare tunnel: TLS ends at Cloudflare, which forwards the
# original scheme in X-Forwarded-Proto.

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

"""Settings for the WEPL money core.

Configuration comes from the environment. There is deliberately no Redis, no
Celery and no second database: see docs/architecture.md.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

if not DEBUG and SECRET_KEY == "dev-only-not-secret":
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is off.")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "platform_core",
    "parties",
    "ledger",
    "governance",
    "connectivity",
    # The simulated I&M bank, for tests and the investor demo. Its data lives in
    # its own tables and production code never imports it.
    "simulator",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "wepl.urls"
WSGI_APPLICATION = "wepl.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "wepl"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "ATOMIC_REQUESTS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Africa/Nairobi"
LANGUAGE_CODE = "en"

# Where member notifications go. SMS is on hold while a provider is chosen, so
# the default backend writes to the log and the outbox keeps every message.
WEPL_NOTIFIER = os.environ.get("WEPL_NOTIFIER", "platform_core.notify.LogNotifier")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# How to fetch statements for each ExternalAccount.connector value. Loaded by
# name so production modules never import the simulator.
WEPL_CONNECTORS = {
    "im_simulator": "simulator.bank.SimulatorConnector",
}

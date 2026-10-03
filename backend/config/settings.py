"""Django settings. Django is the framework at the edges (ADR-0001); the
business architecture lives in ``contexts``.

Configuration comes from the environment. There is deliberately no Redis and
no Celery: see ADR-0001.
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
    "contexts.audit.infrastructure.apps.AuditConfig",
    "contexts.tenancy.infrastructure.apps.TenancyConfig",
    "contexts.notifications.infrastructure.apps.NotificationsConfig",
    "contexts.identity.infrastructure.apps.IdentityConfig",
    "contexts.communities.infrastructure.apps.CommunitiesConfig",
    "contexts.ledger.infrastructure.apps.LedgerConfig",
    "contexts.governance.infrastructure.apps.GovernanceConfig",
    "contexts.custody.infrastructure.apps.CustodyConfig",
]

# The simulated custodian bank, for tests and the investor demo. No context imports
# it. It fakes a bank, so it must never run beside real money: with DEBUG off
# the process refuses to start unless WEPL_ENABLE_SIMULATOR=0.
WEPL_ENABLE_SIMULATOR = os.environ.get("WEPL_ENABLE_SIMULATOR", "1") == "1"
if not DEBUG and WEPL_ENABLE_SIMULATOR:
    raise RuntimeError("WEPL_ENABLE_SIMULATOR must be 0 when DEBUG is off.")
if WEPL_ENABLE_SIMULATOR:
    INSTALLED_APPS.append("simulators.custodian_bank.apps.CustodianBankSimulatorConfig")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "wepl"),
        # A role that is neither superuser nor BYPASSRLS, or row-level security
        # would not apply (ADR-0009). The tenancy system check refuses otherwise.
        "USER": os.environ.get("DB_USER", "wepl_app"),
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
WEPL_NOTIFIER = os.environ.get("WEPL_NOTIFIER", "contexts.notifications.infrastructure.notifiers.LogNotifier")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# Which connector fetches statements for each custodian account's connector
# name. Loaded by name so no context imports a particular integration.
WEPL_CONNECTORS = {}
if WEPL_ENABLE_SIMULATOR:
    WEPL_CONNECTORS["bank_simulator"] = "simulators.custodian_bank.connector.SimulatorConnector"

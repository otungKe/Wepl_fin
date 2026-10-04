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
    "contexts.operations.infrastructure.apps.OperationsConfig",
    "contexts.operators.infrastructure.apps.OperatorsConfig",
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

# The bank's collections service on each group's own account (ADR-0019). Its
# endpoints are off unless the secret is set; the secret signs every request.
WEPL_COLLECTIONS_SECRET = os.environ.get("WEPL_COLLECTIONS_SECRET", "")
if WEPL_COLLECTIONS_SECRET and len(WEPL_COLLECTIONS_SECRET) < 32:
    raise RuntimeError("WEPL_COLLECTIONS_SECRET must be at least 32 characters.")

# The operations digest (contexts/operations). Sent nightly to this address;
# without one it is only logged. Email settings follow Django's EMAIL_*.
WEPL_OPERATIONS_EMAIL = os.environ.get("WEPL_OPERATIONS_EMAIL", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "WEPL operations <operations@localhost>")
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
if not DEBUG and WEPL_OPERATIONS_EMAIL and EMAIL_BACKEND.rsplit(".", 2)[-2] in ("console", "locmem", "dummy"):
    raise RuntimeError("WEPL_OPERATIONS_EMAIL is set but EMAIL_BACKEND would not send it.")

# Operator sign-in (ADR-0021). Authenticator secrets are encrypted with this
# key (a Fernet key: 32 random bytes, url-safe base64). Development derives
# one from SECRET_KEY; production refuses to boot without its own.
WEPL_OPERATOR_KEY = os.environ.get("WEPL_OPERATOR_KEY", "")
if not DEBUG and not WEPL_OPERATOR_KEY:
    raise RuntimeError("WEPL_OPERATOR_KEY must be set when DEBUG is off.")


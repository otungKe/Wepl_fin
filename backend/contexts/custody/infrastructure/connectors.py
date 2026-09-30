"""Which connector fetches statements for an account, by configuration, so
this context never imports a particular custodian integration."""
from django.conf import settings
from django.utils.module_loading import import_string

from ..domain.statement import Connector


def connector_for(connector_name: str, **options) -> Connector | None:
    path = settings.WEPL_CONNECTORS.get(connector_name)
    return import_string(path)(**options) if path else None

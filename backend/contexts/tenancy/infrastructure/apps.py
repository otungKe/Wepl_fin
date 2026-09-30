from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = "contexts.tenancy.infrastructure"
    label = "tenancy"
    verbose_name = "Tenancy"

    def ready(self):
        from . import checks  # noqa: F401  registers the database-role check

from dataclasses import dataclass

from .domain.scope import TenancyError, TenantScope

__all__ = ["TenancyError", "TenantScope", "TenantView"]


@dataclass(frozen=True)
class TenantView:
    id: int
    name: str

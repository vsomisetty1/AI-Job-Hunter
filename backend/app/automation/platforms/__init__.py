"""ATS adapters by platform name (the `companies.source` value)."""

from app.automation.platforms.ashby import AshbyAdapter
from app.automation.platforms.base import PlatformAdapter
from app.automation.platforms.greenhouse import GreenhouseAdapter
from app.automation.platforms.lever import LeverAdapter

ADAPTERS: dict[str, PlatformAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
}


def adapter_for(platform: str) -> PlatformAdapter | None:
    return ADAPTERS.get(platform)


__all__ = ["ADAPTERS", "PlatformAdapter", "adapter_for"]

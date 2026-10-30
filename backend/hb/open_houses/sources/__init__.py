"""Open-house source registry. Adding a source = one module implementing
`OpenHouseSource` + one line here; enable it with OPEN_HOUSE_SOURCES."""

from hb.config import settings
from hb.open_houses.sources.base import OpenHouseRecord, OpenHouseSource
from hb.open_houses.sources.realtor import RealtorOpenHouses
from hb.open_houses.sources.redfin import RedfinOpenHouses

REGISTRY: dict[str, type] = {
    "realtor": RealtorOpenHouses,
    "redfin": RedfinOpenHouses,
}


def enabled_sources() -> list[OpenHouseSource]:
    unknown = [n for n in settings.open_house_sources if n not in REGISTRY]
    if unknown:
        raise ValueError(f"unknown open-house source(s): {', '.join(unknown)} "
                         f"(known: {', '.join(REGISTRY)})")
    return [REGISTRY[name]() for name in settings.open_house_sources]


__all__ = ["OpenHouseRecord", "OpenHouseSource", "REGISTRY", "enabled_sources"]

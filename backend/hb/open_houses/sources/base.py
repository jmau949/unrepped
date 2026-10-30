"""The open-house source contract (docs/05 §4c "Adding an open-house source")."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo


# (west, south, east, north) lon/lat envelope of one city's stored active homes
BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class OpenHouseRecord:
    """One open-house slot as a source reports it.

    The pipeline attaches the slot to a stored listing by `listing_source` +
    `source_listing_id` (a stored listing's `(source, source_listing_id)`) when
    the source shares the scan's ids, else by `mls_id` + `zip` (the MLS number
    every portal syndicates, matched against `listings.raw.mls_id`).
    `start_at` / `end_at` are timezone-aware.
    """

    start_at: datetime
    end_at: datetime
    listing_source: str | None = None
    source_listing_id: str | None = None
    mls_id: str | None = None
    zip: str | None = None
    description: str | None = None
    href: str | None = None
    methods: list[str] = field(default_factory=list)


class OpenHouseSource(Protocol):
    name: str

    def fetch(self, city: str, bbox: BBox | None) -> Iterable[OpenHouseRecord]:
        """Every currently scheduled slot for active homes in `city`.

        `bbox` is the envelope of the city's stored active homes (None when
        none have coordinates) for sources that search by area. Raise to fail
        the whole city; the pipeline records it per city and skips the
        cancellation sweep for the run.
        """
        ...


# US zone abbreviations as listing feeds print them. Standard and daylight
# spellings map to the same IANA zone, which decides DST from the date itself.
ZONE_ABBREVIATIONS = {
    "HST": "Pacific/Honolulu", "HDT": "Pacific/Honolulu",
    "AKST": "America/Anchorage", "AKDT": "America/Anchorage",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "MST": "America/Denver", "MDT": "America/Denver",
    "CST": "America/Chicago", "CDT": "America/Chicago",
    "EST": "America/New_York", "EDT": "America/New_York",
}


def localize(wall_clock: datetime, zone: str | None, default_zone: str) -> datetime:
    """A naive wall-clock time -> aware UTC. `zone` is an abbreviation or an
    IANA name; unknown or missing falls back to `default_zone`."""
    if wall_clock.tzinfo is not None:
        return wall_clock.astimezone(timezone.utc)
    name = ZONE_ABBREVIATIONS.get((zone or "").upper(), zone or default_zone)
    try:
        tz = ZoneInfo(name)
    except (KeyError, ValueError):
        tz = ZoneInfo(default_zone)
    return wall_clock.replace(tzinfo=tz).astimezone(timezone.utc)

"""Realtor.com open houses via HomeHarvest — the shipped source.

HomeHarvest's search query already asks Realtor for `open_houses`, but its
pandas output drops the column, so this source asks for the pydantic models
instead. Same query shape as `listing-scan` (single family, for sale, per
city), and the same listing-id precedence, so every slot keys onto a listing
the scan stored. Realtor reports naive local wall-clock times plus a zone
abbreviation ("PST" year-round, with a separate `dst` flag), which
`localize` resolves to an IANA zone.
"""

from hb.config import settings
from hb.open_houses.sources.base import BBox, OpenHouseRecord, localize
from hb.pipelines.listing_scan import _source_listing_id


def fetch_properties(city: str) -> list:
    """Seam for tests: HomeHarvest `Property` models for one city."""
    from homeharvest import scrape_property

    return scrape_property(location=f"{city}, {settings.geo.state}", listing_type="for_sale",
                           property_type=["single_family"], return_type="pydantic")


class RealtorOpenHouses:
    name = "realtor"

    def fetch(self, city: str, bbox: BBox | None) -> list[OpenHouseRecord]:
        records = []
        for prop in fetch_properties(city):
            slots = getattr(prop, "open_houses", None) or []
            if not slots:
                continue
            listing_id = _source_listing_id({
                "listing_id": prop.listing_id, "mls_id": prop.mls_id,
                "property_id": prop.property_id,
            })
            if listing_id is None:
                continue
            for oh in slots:
                if oh.start_date is None or oh.end_date is None:
                    continue
                records.append(OpenHouseRecord(
                    listing_source=self.name,
                    source_listing_id=listing_id,
                    start_at=localize(oh.start_date, oh.time_zone, settings.timezone),
                    end_at=localize(oh.end_date, oh.time_zone, settings.timezone),
                    description=(oh.description or "").strip() or None,
                    href=str(oh.href) if oh.href else None,
                    methods=list(oh.methods or []),
                ))
        return records

"""Data-source registries for the `us` base pack: hazard polygon layers and
school-rating sources that exist for every state."""

from hb.packs.types import HazardLayer, RatingSource


def _fema_query(geo) -> dict:
    """NFHL flood zones for the geography's counties: SFHA zones plus the
    0.2%-annual-chance shaded X subtype. DFIRM ids are `<state fips><county
    fips>C` (docs/03 §1.4)."""
    ids = ", ".join(f"'{d}'" for d in geo.dfirm_ids)
    return {
        "where": f"DFIRM_ID IN ({ids}) AND (SFHA_TF='T' OR ZONE_SUBTY LIKE '0.2 PCT%')",
        "outFields": "FLD_ZONE,ZONE_SUBTY,DFIRM_ID",
    }


def _fema_zone(p: dict) -> str:
    return ((p.get("FLD_ZONE") or "")
            + (f" ({p['ZONE_SUBTY']})" if p.get("ZONE_SUBTY") else "")).strip()


FEMA_FLOOD = HazardLayer(
    key="fema_flood",
    label="flood",
    tone="sky",
    url="https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query",
    query=_fema_query,
    zone_value=_fema_zone,
)

HAZARDS: tuple[HazardLayer, ...] = (FEMA_FLOOD,)

SCHOOLDIGGER = RatingSource(
    key="schooldigger",
    label="SchoolDigger",
    blurb=("statewide rank from schooldigger.com, badged as a 1–10 percentile"),
)

RATING_SOURCES: tuple[RatingSource, ...] = (SCHOOLDIGGER,)

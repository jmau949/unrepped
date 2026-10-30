"""Data-source registries for the `ca` pack: the CAL FIRE and CGS hazard layers
on top of FEMA flood, and CAASPP as the primary school-rating source.

Endpoints verified 2026-07. The official combined CAL FIRE FHSZ service is
token-gated; the public `fhsz24_1` layer on the same org carries the combined
SRA/LRA 2024 classes. The state CGS server (gis.conservation.ca.gov) is
unreliable; the AGOL-hosted CGS layers are public. The CGS layers carry no
severity attribute, so the quad name stands in — the flag itself is
presence-based.
"""

from hb.packs.types import HazardLayer, RatingSource
from hb.packs.us import sources as us


def _bbox_query(fields: str):
    """Envelope query over the geography's `[market].hazard_bbox`."""

    def query(geo) -> dict:
        bbox = geo.market.hazard_bbox
        if bbox is None:
            raise ValueError(
                "geography [market].hazard_bbox is required for the ca pack's CAL FIRE / "
                "CGS hazard layers (lon_min, lat_min, lon_max, lat_max)"
            )
        return {
            "where": "1=1",
            "outFields": fields,
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }

    return query


CALFIRE_FHSZ = HazardLayer(
    key="calfire_fhsz",
    label="wildfire",
    tone="orange",
    url=("https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
         "fhsz24_1/FeatureServer/0/query"),
    query=_bbox_query("FHSZ_6Class,FHSZ_Description,SRA"),
    zone_value=lambda p: p.get("FHSZ_6Class") or p.get("FHSZ_Description") or "",
)

LIQUEFACTION = HazardLayer(
    key="liquefaction",
    label="liquefaction",
    tone="amber",
    url=("https://services2.arcgis.com/zr3KAIbsRSUyARHG/arcgis/rest/services/"
         "CGS_Liquefaction_Zones/FeatureServer/0/query"),
    query=_bbox_query("QUAD_NAME,RELEASED"),
    zone_value=lambda p: p.get("QUAD_NAME") or "",
)

FAULT_ZONE = HazardLayer(
    key="fault_zone",
    label="fault zone",
    tone="purple",
    url=("https://services2.arcgis.com/zr3KAIbsRSUyARHG/arcgis/rest/services/"
         "CGS_Alquist_Priolo_Fault_Zones/FeatureServer/0/query"),
    query=_bbox_query("QUAD_NAME,ZN_RELEASED"),
    zone_value=lambda p: p.get("QUAD_NAME") or "",
)

HAZARDS: tuple[HazardLayer, ...] = (us.FEMA_FLOOD, CALFIRE_FHSZ, LIQUEFACTION, FAULT_ZONE)

CAASPP = RatingSource(
    key="caaspp",
    label="CAASPP",
    blurb=("share of students meeting/exceeding the state-test standard, badged as a "
           "1–10 statewide decile"),
)

RATING_SOURCES: tuple[RatingSource, ...] = (CAASPP, us.SCHOOLDIGGER)

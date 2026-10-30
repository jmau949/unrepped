"""Hazard-flag pipeline (docs/03 §1.4, docs/04 hazard_flags).

Reads the hazard polygon layers the pack declares (`packs.current().hazards`;
downloaded once by `hb pipeline hazards-fetch` to data/raw/hazards/{key}.geojson
— NOT date-dirred; they are reference data) and point-in-polygon tests every
property with coordinates, upserting presence-based `hazard_flags` rows keyed
(property_id, hazard).

Daily-safe: the run's content hash is a digest over the layer files' sha256s.
Unchanged files ⇒ only properties with zero hazard_flags rows are processed
(new properties since the last run); none ⇒ noop. Changed files ⇒ full
reprocess. `checked_at` is deliberately excluded from upsert values so an
unchanged re-run touches zero rows (invariant D1).
"""

import hashlib
import json
import logging
from pathlib import Path

from shapely import STRtree
from shapely.geometry import Point, shape
from sqlalchemy import select
from sqlalchemy.engine import Engine

from hb import packs
from hb.config import settings
from hb.db.engine import make_session
from hb.db.models import HazardFlag, Property
from hb.db.upsert import upsert
from hb.packs.types import HazardLayer
from hb.pipelines.base import JobRunner

log = logging.getLogger(__name__)


def hazard_dir() -> Path:
    return settings.raw_dir / "hazards"


def layer_path(layer: HazardLayer) -> Path:
    return hazard_dir() / f"{layer.key}.geojson"


def _files_digest(paths: list[Path]) -> str:
    """Combined digest: sha256 over each file's sha256, in layer order."""
    outer = hashlib.sha256()
    for p in paths:
        outer.update(hashlib.sha256(p.read_bytes()).hexdigest().encode())
    return outer.hexdigest()


def _load_layer(layer: HazardLayer, path: Path) -> tuple[STRtree, list]:
    """Parse one GeoJSON layer into an STRtree + parallel zone_value list."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    geoms, values = [], []
    for feat in doc.get("features", []):
        if not feat.get("geometry"):
            continue
        geoms.append(shape(feat["geometry"]))
        values.append(layer.zone_value(feat.get("properties") or {}))
    return STRtree(geoms), values


def flags_for_point(layers: dict[str, tuple[STRtree, list]],
                    lon: float, lat: float) -> dict[str, str]:
    """hazard -> zone_value for every layer whose polygons cover the point."""
    point = Point(lon, lat)
    hits: dict[str, str] = {}
    for hazard, (tree, values) in layers.items():
        for idx in tree.query(point, predicate="covered_by"):
            hits[hazard] = values[int(idx)]
            break  # presence-based: first covering polygon is enough
    return hits


def run(engine: Engine | None = None) -> str:
    with JobRunner("hazards", engine) as runner:
        layers_spec = packs.current().hazards
        paths = [layer_path(layer) for layer in layers_spec]
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"hazard polygon files missing ({', '.join(missing)}) — run "
                f"`hb pipeline hazards-fetch` once to download them"
            )
        digest = _files_digest(paths)
        runner.content_hash = digest
        unchanged = digest == runner.last_content_hash()

        session = make_session(runner.engine)
        try:
            stmt = select(Property).where(
                Property.lat.is_not(None), Property.lon.is_not(None)
            )
            if unchanged:
                # only properties never checked (no flags yet); flagless-but-
                # checked ones are indistinguishable, and re-checking them
                # against identical polygons upserts zero rows anyway
                flagged = select(HazardFlag.property_id).distinct()
                stmt = stmt.where(Property.id.not_in(flagged))
            props = session.execute(stmt).scalars().all()
            if unchanged and not props:
                runner.mark_noop()
            else:
                layers = {layer.key: _load_layer(layer, path)
                          for layer, path in zip(layers_spec, paths)}
                log.info("hazards: checking %d properties against %s polygons",
                         len(props),
                         {h: len(v[1]) for h, v in layers.items()})
                for prop in props:
                    with runner.item(prop.address_norm):
                        for hazard, zone_value in flags_for_point(
                                layers, prop.lon, prop.lat).items():
                            _, changed = upsert(
                                session, HazardFlag,
                                {"property_id": prop.id, "hazard": hazard,
                                 "zone_value": zone_value},
                                key_cols=["property_id", "hazard"],
                            )
                            if changed:
                                runner.items_upserted += 1
                session.commit()
                if unchanged and runner.items_upserted == 0:
                    runner.mark_noop()
        finally:
            session.close()
    # after the with-block: JobRunner.__exit__ has finalized the status
    return runner.status

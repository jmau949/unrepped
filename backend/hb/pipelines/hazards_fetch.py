"""hazards-fetch pipeline — download the pack's hazard polygon layers once
(docs/03 §1.4, docs/05).

Each `HazardLayer` on the current pack names a public ArcGIS REST query endpoint
and a `query(geo)` that scopes it to the configured geography (FEMA by DFIRM id
per county; the `ca` pack's CAL FIRE / CGS layers by `[market].hazard_bbox`).
Features are paged out and written to stable paths the `hazards` job reads:

    data/raw/hazards/{key}.geojson

Standalone (`hb pipeline hazards-fetch`), NOT in the daily sequence: the
polygons are reference data that change when the state re-releases zones, not
daily. Re-running is safe — a layer whose features are byte-identical to the
file on disk is left untouched, and the run is a noop if nothing changed.

`fetch_layer(url, params)` is the network seam tests monkeypatch.
"""

import json
import logging
import random
import time

import httpx
from sqlalchemy.engine import Engine

from hb import packs
from hb.config import settings
from hb.pipelines.base import JobRunner
from hb.pipelines.hazards import hazard_dir, layer_path

log = logging.getLogger(__name__)

PAGE_SIZE = 2000


def fetch_layer(url: str, params: dict) -> list[dict]:
    """Page through an ArcGIS REST query (resultOffset) until a short page."""
    features: list[dict] = []
    offset = 0
    while True:
        page_params = {
            **params,
            "outSR": "4326",
            "geometryPrecision": "6",
            "orderByFields": "OBJECTID",
            "resultOffset": str(offset),
            "resultRecordCount": str(PAGE_SIZE),
            "f": "geojson",
        }
        resp = httpx.get(url, params=page_params, timeout=120)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"{url} -> {body['error']}")
        page = body.get("features", [])
        features.extend(page)
        log.info("hazards-fetch: offset %d: %d features", offset, len(page))
        if len(page) < PAGE_SIZE:
            return features
        offset += PAGE_SIZE
        time.sleep(1.0 + random.random() * 0.5)  # etiquette: ~1 req/s jittered


def run(engine: Engine | None = None, *, missing_only: bool = False) -> str:
    """`missing_only` (what `make load` passes) leaves a layer alone when its
    file is already on disk, so a first run gets every layer and a later run
    costs nothing; a plain run re-fetches to pick up a re-released zone."""
    with JobRunner("hazards-fetch", engine) as runner:
        geo = settings.geo
        hazard_dir().mkdir(parents=True, exist_ok=True)
        for layer in packs.current().hazards:
            out = layer_path(layer)
            if missing_only and out.exists():
                log.info("hazards-fetch: %s already on disk, skipped", layer.key)
                continue
            with runner.item(layer.key):
                params = layer.query(geo)
                features = fetch_layer(layer.url, params)
                payload = json.dumps({"type": "FeatureCollection", "features": features})
                if out.exists() and out.read_text(encoding="utf-8") == payload:
                    log.info("hazards-fetch: %s unchanged (%d features)",
                             layer.key, len(features))
                    continue
                out.write_text(payload, encoding="utf-8")
                runner.items_upserted += 1
                log.info("hazards-fetch: %s wrote %d features -> %s",
                         layer.key, len(features), out)
        if runner.items_upserted == 0:
            runner.mark_noop()
    return runner.status

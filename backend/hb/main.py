"""FastAPI app — component 2 of docs/02-architecture.md §0.

Serves the JSON API under /api, downloaded listing photos under /photos,
and the built SPA (frontend/dist) at / with an SPA fallback. Importable
without the frontend built (the SPA mount is guarded).
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from hb.api import (
    affordability,
    alerts,
    cma,
    compare,
    config,
    contacts,
    deals,
    guide,
    listings,
    market,
    offer,
    open_houses,
    ops,
    overbid,
    prep,
    tours,
    tracker,
    watchlist,
)
from hb.config import settings

app = FastAPI(title="home-buying", version="0.1.0")
app.include_router(ops.router)
app.include_router(config.router)
app.include_router(guide.router)
app.include_router(market.router)
app.include_router(listings.router)
app.include_router(open_houses.router)
app.include_router(contacts.router)
app.include_router(tracker.router)
app.include_router(watchlist.router)
app.include_router(tours.router)
app.include_router(deals.router)
app.include_router(prep.router)
app.include_router(alerts.router)
app.include_router(affordability.router)
app.include_router(cma.router)
app.include_router(overbid.router)
app.include_router(offer.router)
app.include_router(compare.router)

# check_dir=False: `hb serve` and the photo-saving pipelines create the directory,
# so importing the app (tests, tooling) writes nothing to disk.
app.mount("/photos", StaticFiles(directory=settings.photos_dir, check_dir=False),
          name="photos")

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _dist_file(dist: Path, full_path: str) -> Path | None:
    """The file under `dist` that `full_path` names, or None. Resolved, then required to
    stay inside `dist`, so `..` segments or an absolute path can never reach the host."""
    if not full_path:
        return None
    root = dist.resolve()
    try:
        candidate = (root / full_path).resolve()
    except (OSError, ValueError):  # e.g. an embedded NUL
        return None
    if candidate.is_relative_to(root) and candidate.is_file():
        return candidate
    return None


if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if (file := _dist_file(_DIST, full_path)) is not None:
            return FileResponse(file)
        # A missing *file* (anything with an extension: an old build's chunk, a
        # service worker a browser still polls for) is a 404, never the HTML
        # shell; only extension-less deep links fall back to the SPA.
        if "." in full_path.rsplit("/", 1)[-1]:
            raise HTTPException(404)
        return FileResponse(_DIST / "index.html")  # SPA fallback for deep links
else:
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_not_built(full_path: str) -> PlainTextResponse:
        """A checkout before its first `make build`: say what to do instead of a
        bare 404 (the API under /api is up regardless)."""
        return PlainTextResponse(
            "The web app has not been built yet. Run `make build` (or `make serve`, which "
            "builds it when it is missing), then reload this page. The API is running: "
            "/api/ops/health",
            status_code=503)

"""LAN server entrypoint — the FastAPI app on one plain-HTTP listener.

`hb serve` binds 0.0.0.0 on `HB_HTTP_PORT` (18800 by default): the API plus the
built SPA, reachable from any device on the wifi with nothing to install. The
bind is deliberately wide; the firewall rule (`ops/windows-lan.ps1`: Private
profile + LocalSubnet) is what scopes reachability, not the address.

One process, one event loop, one SQLAlchemy engine — a second uvicorn process
would mean two writers against the same SQLite file.
"""

from __future__ import annotations

import logging
import socket

import uvicorn

from hb.config import settings

HOST = "0.0.0.0"  # firewall scopes reachability (Private + LocalSubnet), not the bind


class _BannerShowsLocalhost(logging.Filter):
    """uvicorn's startup line names the bind address, and a browser will not open
    http://0.0.0.0 (Chrome: ERR_ADDRESS_INVALID) — a first-time user clicking the
    line in the terminal sees a dead page. Show the address that works instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and HOST in record.args:
            record.args = tuple("localhost" if a == HOST else a for a in record.args)
        return True


def build_config() -> uvicorn.Config:
    """The one listener: plain HTTP on `settings.http_port`."""
    from hb.main import app  # importing mounts /photos + the SPA; keep it lazy

    return uvicorn.Config(app, host=HOST, port=settings.http_port)


def urls(port: int) -> tuple[str, str]:
    """(this computer, other devices on the wifi) — the two addresses that open the app."""
    return (f"http://localhost:{port}",
            f"http://{socket.gethostname().lower()}.local:{port}")


def run() -> None:
    settings.photos_dir.mkdir(parents=True, exist_ok=True)  # /photos mount target
    config = build_config()  # also installs uvicorn's logging config
    logging.getLogger("uvicorn.error").addFilter(_BannerShowsLocalhost())
    here, wifi = urls(config.port)
    print(f"serve: open {here}  (other devices on your wifi: {wifi})", flush=True)
    from hb import scheduler

    hourly = scheduler.start()
    try:
        uvicorn.Server(config).run()
    finally:
        if hourly is not None:
            hourly.stop()


if __name__ == "__main__":
    run()

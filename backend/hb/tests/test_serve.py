"""The LAN listener (hb/serve.py): one plain-HTTP port, taken from settings."""

import logging

from hb import serve
from hb.config import settings


def test_serves_plain_http_on_the_configured_port():
    config = serve.build_config()

    assert (config.host, config.port) == (serve.HOST, settings.http_port)
    assert config.ssl_certfile is None and config.ssl_keyfile is None


def test_http_port_override_is_honoured(monkeypatch):
    """HB_HTTP_PORT lands in settings.http_port; the listener must follow it."""
    monkeypatch.setattr(settings, "http_port", 28800)

    assert serve.build_config().port == 28800


def test_startup_banner_names_an_address_a_browser_can_open():
    """uvicorn logs 'running on http://0.0.0.0:…'; clicked, that is a dead page
    in Chrome. The filter swaps the bind address for localhost and leaves the
    rest of the record alone."""
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 0,
                               "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
                               ("http", serve.HOST, 18800), None)
    assert serve._BannerShowsLocalhost().filter(record) is True
    assert record.getMessage() == "Uvicorn running on http://localhost:18800 (Press CTRL+C to quit)"

    other = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 0, "Started %s", ("x",), None)
    serve._BannerShowsLocalhost().filter(other)
    assert other.getMessage() == "Started x"


def test_urls_are_clickable_and_follow_the_port(monkeypatch):
    monkeypatch.setattr(serve.socket, "gethostname", lambda: "My-PC")
    assert serve.urls(18800) == ("http://localhost:18800", "http://my-pc.local:18800")

"""Application settings.

Secrets, paths and knobs come from environment variables / .env (docs/11 §4).
The target geography — cities, ZIPs, counties, tax rates, time zone, price
band — comes from a TOML file resolved by `hb.geography.load` (docs/02 §3) and
is exposed here as `settings.geo`; the `target_*`/`timezone` properties are
read-through views of it for the many call sites that only need the lists.
"""

from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, PrivateAttr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from hb import geography
from hb.geography import Geography

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    # Load .env from the repo root (canonical, docs/11) and backend/ (fallback),
    # regardless of the process working directory. Later files win.
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Relative paths resolve against backend/, not the process CWD, so `hb` run
    # from the repo root and the server run from backend/ share one DB.
    data_dir: Path = _BACKEND_DIR / "data"
    database_path: Path | None = None

    # Geography: GEOGRAPHY_FILE wins, then <repo-root>/geography.toml, then the
    # packaged example named by GEOGRAPHY (hb/geographies/<name>.toml).
    geography_file: Path | None = None
    geography: str = "sf_peninsula"
    _geo: Geography | None = PrivateAttr(default=None)

    # Open houses (docs/05 §4c). home_address only SEEDS the distance origin —
    # the live value is edited on the Open Houses page and kept in the
    # `settings` row `home_location`. Sources are names in
    # hb.open_houses.sources.REGISTRY; the route planner estimates drive time
    # as straight-line miles x detour factor at the average speed.
    home_address: str = ""
    open_house_sources: Annotated[list[str], NoDecode] = ["realtor", "redfin"]
    route_avg_mph: float = 25.0
    route_detour_factor: float = 1.3

    # Schedule slots, local wall-clock in the geography's timezone (docs/05 §2).
    # The scheduled tasks fire hourly with `--catch-up`, which runs a job only
    # when its latest slot has no completed run yet — so a slot missed to sleep,
    # a crash or a failed run is retried on the next hour.
    scan_times: Annotated[list[str], NoDecode] = ["05:00", "15:00"]
    daily_times: Annotated[list[str], NoDecode] = ["04:00"]

    # Raw-cache retention (docs/05 §2). Every download lands in a new dated
    # folder under data/raw/<source>/ and upstream restates its history each
    # release, so folders older than this many days are deleted at the tail of
    # `hb pipeline daily` (and by `hb prune-raw`). 0 keeps everything.
    raw_keep_days: int = 90

    # Zillow research CSV URLs — they drift occasionally (docs/03 §1.2).
    # ZORI has no single-family-only ZIP cut; sfrcondomfr (all homes) is the
    # finest available.
    zillow_zhvi_zip_url: str = (
        "https://files.zillowstatic.com/research/public_csvs/zhvi/"
        "Zip_zhvi_uc_sfr_tier_0.33_0.67_sm_sa_month.csv"
    )
    zillow_zhvi_city_url: str = (
        "https://files.zillowstatic.com/research/public_csvs/zhvi/"
        "City_zhvi_uc_sfr_tier_0.33_0.67_sm_sa_month.csv"
    )
    zillow_zori_zip_url: str = (
        "https://files.zillowstatic.com/research/public_csvs/zori/"
        "Zip_zori_uc_sfrcondomfr_sm_month.csv"
    )

    fred_api_key: str = ""
    rentcast_api_key: str = ""
    rentcast_monthly_limit: int = 45

    # SchoolDigger ratings API — free developer plan at developer.schooldigger.com
    # The free plan is hard-capped at 20 calls/DAY (x-dayrate-limit headers);
    # the pipeline converges across daily runs. 18 leaves slack for manual tests.
    schooldigger_app_id: str = ""
    schooldigger_app_key: str = ""
    schooldigger_daily_limit: int = 18
    # CAASPP results year (California only; the school-ratings job no-ops elsewhere)
    caaspp_year: int = 2024

    zillow_wrapper_enabled: bool = False
    rapidapi_key: str = ""

    save_photos: bool = True

    alert_channels: str = "toast,log"  # toast is Windows-only; log works everywhere
    # Pushover phone push (docs/09 §4): an application token can only send to
    # its user key, so the pair is worth nothing to an attacker beyond paging you.
    pushover_token: str = ""
    pushover_user: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""
    app_base_url: str = "http://localhost:18800"

    # LAN server (hb serve): plain HTTP on this port, bound on 0.0.0.0.
    http_port: int = Field(18800, validation_alias=AliasChoices("HB_HTTP_PORT", "http_port"))
    # The hourly catch-up check inside `hb serve` (hb/scheduler.py): runs a job
    # whose slot has no run yet while the app is open. Off on the home server,
    # whose systemd timers run the same jobs.
    serve_scheduler: bool = Field(
        True, validation_alias=AliasChoices("HB_SERVE_SCHEDULER", "serve_scheduler"))

    @field_validator("open_house_sources", "scan_times", "daily_times", mode="before")
    @classmethod
    def _split_csv(cls, v):
        # .env spells lists comma-separated ("realtor,redfin"), not as JSON
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        return v

    @field_validator("data_dir", "database_path", "geography_file", mode="after")
    @classmethod
    def _anchor_to_backend(cls, p: Path | None) -> Path | None:
        if p is None or p.is_absolute():
            return p
        return _BACKEND_DIR / p

    @property
    def geo(self) -> Geography:
        # Loaded on first use, not at import, so `hb setup` can still run (and
        # replace the file) when a hand-edited geography.toml no longer parses.
        if self._geo is None:
            self._geo = geography.load(self.geography_file, self.geography, _REPO_ROOT)
        return self._geo

    @property
    def geo_is_example(self) -> bool:
        """True when no geography of the user's own exists and the packaged
        example is in use — `hb serve` and `hb pipeline daily` warn about it."""
        return self.geography_file is None and not (_REPO_ROOT / "geography.toml").is_file()

    @property
    def target_cities(self) -> list[str]:
        return self.geo.city_names

    @property
    def target_zips(self) -> list[str]:
        return self.geo.zips

    @property
    def target_price_min(self) -> int:
        return self.geo.price_band.min

    @property
    def target_price_max(self) -> int:
        return self.geo.price_band.max

    @property
    def timezone(self) -> str:
        return self.geo.timezone

    @property
    def db_path(self) -> Path:
        return self.database_path or self.data_dir / "hb.sqlite3"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"


settings = Settings()

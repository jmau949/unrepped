"""Target geography — the one place that knows which cities, ZIPs and counties
this instance tracks (docs/02 §3).

Everything geo-scoped reads from here via `settings.geo`: the scan's city list,
the ZIP→city→county fallback for thin market data, effective property-tax
rates, the map's home view, the time zone the open-house clocks run in, the
shopping price band, and the state code every scraper is asked for.

The data comes from a TOML file, never from code constants. `load()` resolves:
  1. GEOGRAPHY_FILE=<path>                         (explicit)
  2. <repo-root>/geography.toml                   (gitignored, next to .env)
  3. hb/geographies/<GEOGRAPHY>.toml              (packaged example; GEOGRAPHY
                                                   defaults to "sf_peninsula")
No imports from the rest of `hb`: `hb.config` imports this module.
"""

from __future__ import annotations

import tomllib
from functools import cached_property
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

PACKAGE = "hb.geographies"


class County(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # must equal the county's Redfin region name minus ", <state>"
    fips: str = Field(pattern=r"^\d{3}$")  # 3-digit county FIPS; the state FIPS is on Geography
    effective_tax_rate: float = Field(gt=0, lt=0.1)  # all-in, incl. typical parcel taxes
    assessor_label: str = ""
    assessor_url: str = ""
    transfer_tax_note: str = ""


class City(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    county: str
    zips: list[str] = Field(min_length=1)
    tax_rate: float | None = Field(default=None, gt=0, lt=0.1)  # overrides the county rate
    flags: list[str] = []  # pack-interpreted, e.g. "sewer_lateral_pos"

    @field_validator("zips")
    @classmethod
    def _zip5(cls, zips: list[str]) -> list[str]:
        bad = [z for z in zips if not (len(z) == 5 and z.isdigit())]
        if bad:
            raise ValueError(f"ZIPs must be five digits: {', '.join(bad)}")
        if len(set(zips)) != len(zips):
            raise ValueError("duplicate ZIP within one city")
        return zips


class MapView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    center: tuple[float, float]  # [lon, lat]
    zoom: float = 9


class PriceBand(BaseModel):
    """Shopping band — alert matching and default UI filters only, never an
    ingestion filter (docs/05 §4)."""

    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=0)
    max: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> PriceBand:
        if self.max <= self.min:
            raise ValueError("price_band.max must exceed price_band.min")
        return self


class Market(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_shiller_fred_id: str | None = None  # e.g. SFXRSA; omit where FRED has no metro index
    hazard_bbox: tuple[float, float, float, float] | None = None  # lon_min, lat_min, lon_max, lat_max


class CostOverrides(BaseModel):
    """Optional metro-level overrides of a pack's repair/closing cost books."""

    model_config = ConfigDict(extra="forbid")

    year: int | None = None
    label: str | None = None
    tour: dict[str, tuple[int, int]] = {}
    closing: dict[str, tuple[int, int]] = {}


class Geography(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: int = Field(default=1, alias="schema")
    name: str  # metro label for UI copy
    state: str = Field(pattern=r"^[A-Z]{2}$")
    state_fips: str = Field(pattern=r"^\d{2}$")
    timezone: str
    pack: str | None = None  # state pack key; defaults to the lower-cased state
    map: MapView
    price_band: PriceBand
    market: Market = Market()
    costs: CostOverrides = CostOverrides()
    counties: list[County] = Field(min_length=1)
    cities: list[City] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def _iana(cls, tz: str) -> str:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown IANA time zone {tz!r}") from e
        return tz

    @model_validator(mode="after")
    def _consistent(self) -> Geography:
        counties = [c.name for c in self.counties]
        if len(set(counties)) != len(counties):
            raise ValueError("duplicate county name")
        names = [c.name for c in self.cities]
        if len(set(names)) != len(names):
            raise ValueError("duplicate city name")
        for city in self.cities:
            if city.county not in counties:
                raise ValueError(
                    f"city {city.name!r} names county {city.county!r}, "
                    f"which is not in [[counties]] ({', '.join(counties)})"
                )
        seen: dict[str, str] = {}
        for city in self.cities:
            for z in city.zips:
                if z in seen:
                    raise ValueError(
                        f"ZIP {z} is listed under both {seen[z]!r} and {city.name!r}"
                    )
                seen[z] = city.name
        return self

    # --- derived views (cached; a loaded geography is never mutated) ----------

    @cached_property
    def city_names(self) -> list[str]:
        return [c.name for c in self.cities]

    @cached_property
    def zips(self) -> list[str]:
        return [z for c in self.cities for z in c.zips]

    @cached_property
    def county_names(self) -> list[str]:
        return [c.name for c in self.counties]

    @cached_property
    def zip_to_city(self) -> dict[str, str]:
        return {z: c.name for c in self.cities for z in c.zips}

    @cached_property
    def city_to_county(self) -> dict[str, str]:
        return {c.name: c.county for c in self.cities}

    @cached_property
    def _cities_ci(self) -> dict[str, City]:
        return {c.name.casefold(): c for c in self.cities}

    @cached_property
    def _counties(self) -> dict[str, County]:
        return {c.name: c for c in self.counties}

    def city(self, name: str | None) -> City | None:
        return self._cities_ci.get(name.strip().casefold()) if name else None

    def county_of(self, city: str | None) -> County | None:
        c = self.city(city)
        return self._counties.get(c.county) if c else None

    def zips_in_city(self, city: str | None) -> list[str]:
        c = self.city(city)
        return list(c.zips) if c else []

    def sibling_zips(self, zip5: str) -> list[str]:
        """Every ZIP of the city this ZIP belongs to, or just the ZIP itself."""
        city = self.zip_to_city.get(zip5)
        return self.zips_in_city(city) if city else [zip5]

    def tax_rate_for(self, city: str | None) -> float | None:
        """City override, then the county rate, else None (the caller picks a default)."""
        c = self.city(city)
        if c is None:
            return None
        if c.tax_rate is not None:
            return c.tax_rate
        return self._counties[c.county].effective_tax_rate

    def cities_with_flag(self, flag: str) -> list[str]:
        return [c.name for c in self.cities if flag in c.flags]

    @cached_property
    def dfirm_ids(self) -> list[str]:
        """FEMA NFHL DFIRM ids, one per county: <state FIPS><county FIPS>C."""
        return [f"{self.state_fips}{c.fips}C" for c in self.counties]

    @property
    def pack_key(self) -> str:
        return self.pack or self.state.lower()


# --- loading -----------------------------------------------------------------


def parse(text: str, source: str) -> Geography:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{source}: not valid TOML — {e}") from e
    try:
        return Geography.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"{source}: invalid geography\n{e}") from e


def packaged_names() -> list[str]:
    return sorted(
        p.name[: -len(".toml")]
        for p in resources.files(PACKAGE).iterdir()
        if p.name.endswith(".toml")
    )


def load_packaged(name: str) -> Geography:
    ref = resources.files(PACKAGE) / f"{name}.toml"
    try:
        text = ref.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"no packaged geography {name!r} (known: {', '.join(packaged_names())}); "
            f"set GEOGRAPHY to one of those or GEOGRAPHY_FILE to your own TOML"
        ) from e
    return parse(text, f"{PACKAGE}/{name}.toml")


def load(explicit: Path | None, name: str, repo_root: Path) -> Geography:
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"GEOGRAPHY_FILE={path} does not exist")
        return parse(path.read_text(encoding="utf-8"), str(path))
    local = repo_root / "geography.toml"
    if local.is_file():
        return parse(local.read_text(encoding="utf-8"), str(local))
    return load_packaged(name)

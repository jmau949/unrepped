"""SQLAlchemy models — the entire schema, per docs/04-data-model.md.

Conventions (docs/02-architecture.md §3): TEXT UUID4 PKs, UTC ISO-8601 TEXT
timestamps, integer dollars, REAL ratios. Every natural unique key is declared
as a UniqueConstraint — these are the UPSERT keys that guarantee duplicate-free
re-runs. No SQLite-only constructs here (Postgres escape hatch).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid4_str() -> str:
    return str(uuid.uuid4())


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    type_annotation_map = {str: Text, int: Integer, float: Float}


def _default_state() -> str:
    """The geography's state, for records that arrive without one."""
    from hb.config import settings  # lazy: keeps the schema module import-light

    return settings.geo.state


class Property(Base):
    """Canonical physical home — entity-resolution target."""

    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("address_norm", "zip", "unit", name="uq_properties_address"),
        Index("ix_properties_zip", "zip"),
        Index("ix_properties_lat_lon", "lat", "lon"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    address_norm: Mapped[str]
    # '' (not NULL) when no unit, so the unique constraint treats "no unit" as one value
    unit: Mapped[str] = mapped_column(default="")
    street: Mapped[str | None]
    city: Mapped[str | None]
    state: Mapped[str] = mapped_column(default=_default_state)
    zip: Mapped[str]
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    beds: Mapped[int | None]
    baths: Mapped[float | None]
    sqft: Mapped[int | None]
    lot_sqft: Mapped[int | None]
    year_built: Mapped[int | None]
    property_type: Mapped[str] = mapped_column(default="single_family")
    apn: Mapped[str | None]
    assessor_sqft: Mapped[int | None]
    condition_tag: Mapped[str | None]  # renovated | dated | fixer
    condition_notes: Mapped[str | None]
    source_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    # Realtor.com sale/listing history, lazily fetched + cached (price_history.py).
    # NULL fetched_at = never fetched; [] = fetched, no history available.
    price_history: Mapped[list | None] = mapped_column(JSON, default=list)
    price_history_fetched_at: Mapped[str | None]
    # the Watchlist (docs/08 §5b): a home is on it when watched_at is set (the
    # Watch button, adding it to the tracker, or logging a tour); Remove clears it
    watched_at: Mapped[str | None]
    created_at: Mapped[str] = mapped_column(default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class Listing(Base):
    """One marketing episode of a property on one source."""

    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source", "source_listing_id", name="uq_listings_source_id"),
        Index("ix_listings_property_id", "property_id"),
        Index("ix_listings_status", "status"),
        Index("ix_listings_listing_group_id", "listing_group_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    listing_group_id: Mapped[str | None] = mapped_column(ForeignKey("listing_groups.id"))
    source: Mapped[str]  # realtor | redfin | manual
    source_listing_id: Mapped[str]
    url: Mapped[str | None]
    status: Mapped[str]  # active | pending | sold | delisted
    list_price: Mapped[int | None]
    original_list_price: Mapped[int | None]
    list_date: Mapped[str | None]
    pending_date: Mapped[str | None]
    sold_date: Mapped[str | None]
    delist_date: Mapped[str | None]
    sold_price: Mapped[int | None]
    dom_source: Mapped[int | None]
    offer_due_at: Mapped[str | None]
    photo_urls: Mapped[list] = mapped_column(JSON, default=list)
    photo_paths: Mapped[list] = mapped_column(JSON, default=list)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    # when the user last opened this listing's detail page in its current
    # status (docs/08 §2b); NULL = unread. Stamped by the detail endpoint and
    # cleared again when the listing-scan sees the home close.
    viewed_at: Mapped[str | None]
    first_seen: Mapped[str] = mapped_column(default=utcnow_iso)
    last_seen: Mapped[str] = mapped_column(default=utcnow_iso)


class OpenHouse(Base):
    """One scheduled open house for a listing (docs/05 §4c), one row per slot
    however many sources report it; `source` names the first configured source
    that did.

    Future rows are replaced by each `open-houses` run (a slot that vanishes
    upstream was cancelled); past rows stay as the record of what was held.
    A slot the buyer put on their schedule is never swept: it is stamped
    `cancelled_at` instead, so the schedule can say so.
    """

    __tablename__ = "open_houses"
    __table_args__ = (
        UniqueConstraint("listing_id", "start_at", name="uq_open_houses_slot"),
        Index("ix_open_houses_start_at", "start_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    source: Mapped[str]  # an hb.open_houses.sources.REGISTRY name
    start_at: Mapped[str]  # UTC ISO-8601
    end_at: Mapped[str]    # UTC ISO-8601
    description: Mapped[str | None]
    href: Mapped[str | None]  # virtual-tour / event link when the source has one
    methods: Mapped[list] = mapped_column(JSON, default=list)  # in_person | virtual
    scheduled_at: Mapped[str | None]  # set = on the buyer's open-house schedule
    # the buyer's visiting order across the schedule (a day reads its slots in
    # this order); set with scheduled_at, new slots go last
    schedule_position: Mapped[int | None]
    cancelled_at: Mapped[str | None]  # set = upstream stopped listing a scheduled slot
    first_seen: Mapped[str] = mapped_column(default=utcnow_iso)
    last_seen: Mapped[str] = mapped_column(default=utcnow_iso)


class ListingEvent(Base):
    """Append-only diff log; drives alerts and the detail-page timeline."""

    __tablename__ = "listing_events"
    __table_args__ = (
        UniqueConstraint(
            "listing_id", "event_type", "observed_at", "new_value", name="uq_listing_events"
        ),
        Index("ix_listing_events_listing_observed", "listing_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    event_type: Mapped[str]  # new | price_change | status_change | pending | back_on_market | delisted | relisted | sold
    old_value: Mapped[str | None]
    new_value: Mapped[str | None]
    observed_at: Mapped[str]


class ListingGroup(Base):
    """Relist stitching — true cumulative DOM across delist/relist cycles."""

    __tablename__ = "listing_groups"

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    first_list_date: Mapped[str | None]
    cumulative_dom: Mapped[int | None]
    episode_count: Mapped[int] = mapped_column(default=1)
    ended_by: Mapped[str] = mapped_column(default="open")  # sale | withdrawn | open


class Sale(Base):
    """Closed transaction used as a comp."""

    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("property_id", "sale_date", name="uq_sales_property_date"),
        Index("ix_sales_sale_date", "sale_date"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    listing_id: Mapped[str | None] = mapped_column(ForeignKey("listings.id"))
    sale_date: Mapped[str]
    sale_price: Mapped[int]
    list_price_at_sale: Mapped[int | None]
    original_list_price: Mapped[int | None]
    sp_lp: Mapped[float | None]  # always vs original_list_price
    dom: Mapped[int | None]
    cumulative_dom: Mapped[int | None]
    had_price_cut: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(default="realtor_sold_scan")  # | rentcast | manual | assessor


class MarketMetric(Base):
    """Tidy geo time series."""

    __tablename__ = "market_metrics"
    __table_args__ = (
        UniqueConstraint(
            "geo_type", "geo_id", "period_start", "period", "metric", "source",
            name="uq_market_metrics",
        ),
        Index("ix_market_metrics_lookup", "geo_type", "geo_id", "metric", "period_start"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    geo_type: Mapped[str]  # zip | neighborhood | city | county
    geo_id: Mapped[str]
    period_start: Mapped[str]
    period: Mapped[str]  # monthly | 3m (Redfin's rolling-3-month tracker rows)
    metric: Mapped[str]
    value: Mapped[float]
    source: Mapped[str]  # redfin | zillow | car | derived


class PriceIndex(Base):
    """Monthly per-geo price index for CMA time adjustments."""

    __tablename__ = "price_index"
    __table_args__ = (
        UniqueConstraint("geo_type", "geo_id", "month", "source", name="uq_price_index"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    geo_type: Mapped[str]
    geo_id: Mapped[str]
    month: Mapped[str]  # YYYY-MM
    index_value: Mapped[float]
    source: Mapped[str]  # zhvi | redfin_ppsf | blend


class AvmSnapshot(Base):
    __tablename__ = "avm_snapshots"
    __table_args__ = (
        UniqueConstraint("property_id", "source", "as_of", name="uq_avm_snapshots"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    source: Mapped[str]  # own_cma | realtor_estimate | zestimate | rentcast
    value: Mapped[int]
    low: Mapped[int | None]
    high: Mapped[int | None]
    as_of: Mapped[str]  # date granularity: one snapshot per source per day


class CmaRun(Base):
    __tablename__ = "cma_runs"

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    created_at: Mapped[str] = mapped_column(default=utcnow_iso)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    estimate: Mapped[int | None]
    low: Mapped[int | None]
    high: Mapped[int | None]
    confidence: Mapped[str | None]  # low | medium | high
    index_source: Mapped[str | None]


class CmaComp(Base):
    __tablename__ = "cma_comps"
    __table_args__ = (
        UniqueConstraint("cma_run_id", "sale_id", name="uq_cma_comps"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    cma_run_id: Mapped[str] = mapped_column(ForeignKey("cma_runs.id"))
    sale_id: Mapped[str] = mapped_column(ForeignKey("sales.id"))
    similarity_score: Mapped[float]
    auto_selected: Mapped[bool] = mapped_column(default=True)
    included: Mapped[bool] = mapped_column(default=True)
    time_adj_factor: Mapped[float | None]
    adjustments: Mapped[dict] = mapped_column(JSON, default=dict)
    adjusted_price: Mapped[int | None]


class TrackedListing(Base):
    __tablename__ = "tracked_listings"
    __table_args__ = (
        UniqueConstraint("listing_id", name="uq_tracked_listings_listing"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    stage: Mapped[str] = mapped_column(default="saved")
    # saved | toured | disclosures | offer_prep | offered | won | lost | passed
    notes: Mapped[str | None]
    disclosure_checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    my_max_bid: Mapped[int | None]
    created_at: Mapped[str] = mapped_column(default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class PropertyTour(Base):
    """One visit to one home — the buyer's own observations (docs/13)."""

    __tablename__ = "property_tours"
    __table_args__ = (
        # You don't tour the same house twice in a day. Keying on the date (not
        # a surrogate) is what makes offline-kit re-import idempotent.
        UniqueConstraint("property_id", "toured_on", name="uq_property_tours_visit"),
        Index("ix_property_tours_property_id", "property_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    # Keyed on the property, not the listing: a home toured during a delisted
    # episode that comes back on market is the same home, and the same tour.
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    listing_id: Mapped[str | None] = mapped_column(ForeignKey("listings.id"))
    toured_on: Mapped[str]  # local date, YYYY-MM-DD
    kind: Mapped[str] = mapped_column(default="open_house")
    # open_house | private | drive_by | second_visit
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)  # {item_key: value}
    agent_answers: Mapped[dict] = mapped_column(JSON, default=dict)  # {index: answer}
    gut_score: Mapped[int | None]  # 1-5
    verdict: Mapped[str | None]  # offer | maybe | pass
    notes: Mapped[str | None]
    # Overrides of the hb.tour_spec.evaluate() roll-up when the user has a real quote.
    repair_low: Mapped[int | None]
    repair_high: Mapped[int | None]
    source: Mapped[str] = mapped_column(default="app")  # app | offline_kit
    created_at: Mapped[str] = mapped_column(default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class Deal(Base):
    """One accepted offer, from Acceptance to keys (docs/14-closing-playbook.md).

    Holds only the numbers read off the contract; every task date is derived from
    them by hb.closing_spec. A NULL contingency day-count means that contingency was
    **waived**, which prunes its anchor and every task hanging off it.
    """

    __tablename__ = "deals"
    __table_args__ = (
        # Same key as tracked_listings: a deal is the continuation of a tracked row.
        UniqueConstraint("listing_id", name="uq_deals_listing"),
        Index("ix_deals_status", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    accepted_on: Mapped[str]  # local date, YYYY-MM-DD — the anchor for every clock
    purchase_price: Mapped[int | None]
    emd_amount: Mapped[int | None]
    emd_sent_on: Mapped[str | None]
    emd_business_days: Mapped[int | None]
    close_of_escrow_on: Mapped[str | None]
    # NULL = waived, not "unset". Defaults (17/17/21) are applied on create by the API.
    investigation_days: Mapped[int | None]
    appraisal_days: Mapped[int | None]
    loan_days: Mapped[int | None]
    financed: Mapped[int] = mapped_column(default=1)
    loan_type: Mapped[str | None]
    escrow_company: Mapped[str | None]
    escrow_number: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="open")  # open | closed | cancelled
    # {task_key: {done_on, note, waived, due_override}} — keys from hb/closing_spec.py
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None]
    created_at: Mapped[str] = mapped_column(default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_alerts_dedup_key"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    type: Mapped[str]
    listing_id: Mapped[str | None] = mapped_column(ForeignKey("listings.id"))
    tracked_listing_id: Mapped[str | None] = mapped_column(ForeignKey("tracked_listings.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=utcnow_iso)
    delivered_at: Mapped[str | None]
    channel: Mapped[str | None]


class RateSnapshot(Base):
    __tablename__ = "rate_snapshots"
    __table_args__ = (
        UniqueConstraint("date", "series", name="uq_rate_snapshots"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    date: Mapped[str]
    series: Mapped[str]  # MORTGAGE30US | MORTGAGE15US | CASESHILLER (metro index, if set)
    value: Mapped[float]


class BuyerProfile(Base):
    """Single row, id='default'."""

    __tablename__ = "buyer_profile"

    id: Mapped[str] = mapped_column(primary_key=True, default="default")
    cash_available: Mapped[int] = mapped_column(default=0)
    down_payment: Mapped[int] = mapped_column(default=0)  # dollars, not a percentage
    rate_assumption: Mapped[float | None]  # NULL => latest MORTGAGE30US
    appraisal_gap_tolerance_pct: Mapped[float] = mapped_column(default=0.05)
    insurance_monthly_est: Mapped[int] = mapped_column(default=250)
    include_earthquake_ins: Mapped[bool] = mapped_column(default=False)
    target_zips: Mapped[list] = mapped_column(JSON, default=list)
    annual_income: Mapped[int] = mapped_column(default=0)  # gross $/yr; 0 = not entered
    monthly_debts: Mapped[int] = mapped_column(default=0)  # other debt payments $/mo
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class School(Base):
    """A public school in the geography's state, from the NCES Common Core of Data
    (loaded by the `schools` pipeline). Listing detail assigns one school per level via the
    property's district polygon (schools_match.py); `leaid` is the exact join
    key to school_districts.geoid. `rating`/`pct_met` are the CAASPP fast-path
    columns; per-source ratings live in school_rating_snapshots."""

    __tablename__ = "schools"
    __table_args__ = (
        Index("ix_schools_lat_lon", "lat", "lon"),
        Index("ix_schools_level", "level"),
        Index("ix_schools_leaid", "leaid"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    nces_id: Mapped[str] = mapped_column(unique=True)  # NCES school id (NCESSCH)
    name: Mapped[str]
    level: Mapped[str]  # elementary | middle | high
    lat: Mapped[float]
    lon: Mapped[float]
    district: Mapped[str | None]
    county: Mapped[str | None]
    zip: Mapped[str | None]
    leaid: Mapped[str | None]  # NCES LEA id (7-char) == school_districts.geoid
    is_charter: Mapped[bool] = mapped_column(default=False)  # charters are not zoned
    rating: Mapped[int | None]  # CAASPP proficiency decile 1-10; NULL until rated
    pct_met: Mapped[float | None]  # raw CAASPP % met/exceeded standard (ELA+Math avg)
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class SchoolDistrict(Base):
    """A school district polygon from the NCES TIGER composite (loaded by the
    `school-districts` pipeline). CA has overlapping elementary + secondary
    districts alongside unified ones — `kind` distinguishes them so the matcher
    can pick the governing district per school level. Geometry is stored as
    GeoJSON text; the bbox columns are the SQL prefilter."""

    __tablename__ = "school_districts"
    __table_args__ = (
        Index("ix_school_districts_bbox",
              "bbox_lat_min", "bbox_lat_max", "bbox_lon_min", "bbox_lon_max"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    geoid: Mapped[str] = mapped_column(unique=True)  # NCES LEAID (STATEFP + LEA code)
    name: Mapped[str]
    kind: Mapped[str]  # elementary | secondary | unified
    lo_grade: Mapped[str | None]
    hi_grade: Mapped[str | None]
    geometry_json: Mapped[str]  # GeoJSON geometry (Polygon/MultiPolygon)
    bbox_lat_min: Mapped[float]
    bbox_lat_max: Mapped[float]
    bbox_lon_min: Mapped[float]
    bbox_lon_max: Mapped[float]
    school_year: Mapped[str | None]
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class SchoolRatingSnapshot(Base):
    """One rating for one school from one source (caaspp | schooldigger |
    greatschools), mirroring the avm_snapshots multi-source pattern. `rating_10`
    is normalized to a comparable 1-10 scale; `label` keeps the source-native
    display string (e.g. "#123 of 5,856 in CA")."""

    __tablename__ = "school_rating_snapshots"
    __table_args__ = (
        UniqueConstraint("school_id", "source", name="uq_school_rating_snapshots"),
        Index("ix_school_rating_snapshots_school", "school_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    school_id: Mapped[str] = mapped_column(ForeignKey("schools.id"))
    source: Mapped[str]
    rating_10: Mapped[float | None]
    label: Mapped[str | None]
    detail: Mapped[dict | None] = mapped_column(JSON)
    as_of: Mapped[str | None]
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class AppSetting(Base):
    """Small JSON key-value store: alert_rules, rentcast_budget (docs/04)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[str] = mapped_column(default=utcnow_iso)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_job_started", "job", "started_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    job: Mapped[str]
    started_at: Mapped[str] = mapped_column(default=utcnow_iso)
    finished_at: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="running")  # ok | noop | partial | failed
    items_seen: Mapped[int] = mapped_column(default=0)
    items_upserted: Mapped[int] = mapped_column(default=0)
    events_emitted: Mapped[int] = mapped_column(default=0)
    error_summary: Mapped[str | None]
    content_hash: Mapped[str | None]


class Contact(Base):
    """The deal team, the people behind a listing, and general contacts (docs/14 §1).

    `deal_id` set = a member of that deal's roster. `listing_id` set = saved from
    that listing's detail page before any offer exists — the listing agent reached
    in week one, or the owner of record found on the assessor roll (docs/08 §3 1c).
    A deal on that listing lists those rows in its team alongside its own, and they
    outlive the deal. Both NULL = a contact tied to nothing (a lender you're
    shopping, an inspector you liked).
    """

    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_deal_id", "deal_id"),
        Index("ix_contacts_listing_id", "listing_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    kind: Mapped[str]
    # escrow | title | lender | inspector | insurance | attorney | tc
    # | listing_agent | owner | contractor | other
    name: Mapped[str]
    deal_id: Mapped[str | None] = mapped_column(ForeignKey("deals.id"))
    listing_id: Mapped[str | None] = mapped_column(ForeignKey("listings.id"))
    company: Mapped[str | None]
    role: Mapped[str | None]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    notes: Mapped[str | None]


class Preapproval(Base):
    __tablename__ = "preapprovals"

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"))
    amount: Mapped[int]
    rate: Mapped[float | None]
    expires_on: Mapped[str | None]
    notes: Mapped[str | None]


class HazardFlag(Base):
    __tablename__ = "hazard_flags"
    __table_args__ = (
        UniqueConstraint("property_id", "hazard", name="uq_hazard_flags"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid4_str)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    hazard: Mapped[str]  # a pack hazard-layer key (hb/packs/<key>/sources.py): fema_flood, …
    zone_value: Mapped[str | None]
    checked_at: Mapped[str] = mapped_column(default=utcnow_iso)

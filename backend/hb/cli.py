"""`hb` CLI — the scheduler interface (docs/02-architecture.md §0 component 1).

Anything Windows Task Scheduler or cron can run lives here.
"""

import logging

import typer

app = typer.Typer(no_args_is_help=True, help="Home-buying platform CLI")
db_app = typer.Typer(help="Database maintenance")
pipeline_app = typer.Typer(no_args_is_help=True, help="Ingestion jobs (the daily sequence, the scans and standalone jobs)")
alerts_app = typer.Typer(help="Alert delivery")
schedule_app = typer.Typer(no_args_is_help=True,
                           help="The per-user OS schedule for the scans (docs/05 s.2)")
app.add_typer(db_app, name="db")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(alerts_app, name="alerts")
app.add_typer(schedule_app, name="schedule")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# alembic lists its autogenerate plugins at INFO on import — six lines in every
# scheduled run's log once the migration check is routine. Migrations themselves
# still log ("Running upgrade … -> 0005").
logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply alembic migrations to the configured database."""
    from hb.db.migrate import upgrade_db

    upgrade_db()
    typer.echo("database upgraded to head")


CATCH_UP_HELP = ("Run only if the latest scheduled slot (docs/05 s.2) has no completed "
                 "run yet (what the hourly scheduled task passes)")


def _warn_if_example() -> None:
    """Say so when no geography of the user's own exists: the packaged example
    would otherwise be downloaded and served without a word."""
    from hb.config import settings

    if settings.geo_is_example:
        typer.echo(f"Note: no geography.toml, so this uses the built-in {settings.geo.name} "
                   "example. Run `make setup` to choose your own area.", err=True)


def _ready_db() -> None:
    """Apply pending migrations to the configured database before touching it:
    what `hb serve` has always done, and now every pipeline and alert command
    too, so `make load` works on a fresh clone before the app has ever served.
    At head it costs one query."""
    from hb.db.engine import get_engine
    from hb.db.migrate import ensure_schema

    ensure_schema(get_engine())


def _caught_up(name: str) -> bool:
    """True (and says so) when `name`'s latest slot already has a completed run."""
    from hb.db.engine import make_session
    from hb.pipelines.schedule import needs_run

    with make_session() as session:
        if needs_run(session, name):
            return False
    typer.echo(f"{name}: up to date, skipping")
    return True


@pipeline_app.command("daily")
def pipeline_daily(
    catch_up: bool = typer.Option(False, "--catch-up", help=CATCH_UP_HELP),
) -> None:
    """Run the bulk sequence (redfin-market, zillow-research, fred,
    build-index, ...), then take the nightly DB backup and prune the raw cache."""
    from hb.db.backup import backup_db
    from hb.pipelines import run_daily

    _ready_db()
    if catch_up and _caught_up("daily"):
        return

    _warn_if_example()
    for job, status in run_daily().items():
        typer.echo(f"{job}: {status}")
    try:
        typer.echo(f"backup: {backup_db()}")
    except Exception as exc:  # noqa: BLE001 — backup failure shouldn't kill the run
        typer.echo(f"backup FAILED: {exc}", err=True)
    try:
        _prune_raw()
    except Exception as exc:  # noqa: BLE001 — nor should a prune failure
        typer.echo(f"raw cache prune FAILED: {exc}", err=True)


@db_app.command("backup")
def db_backup() -> None:
    """Back up the database to data/backups/ (14-day retention)."""
    from hb.db.backup import backup_db

    typer.echo(f"backup: {backup_db()}")


def _prune_raw() -> None:
    """Raw-cache retention (docs/05 §2): the tail of `pipeline daily` and the
    whole of `prune-raw`."""
    from hb.config import settings
    from hb.pipelines.raw_cache import prune_raw

    if settings.raw_keep_days <= 0:
        typer.echo("raw cache: retention off (RAW_KEEP_DAYS=0)")
        return
    removed = prune_raw()
    typer.echo(f"raw cache: pruned {len(removed)} dated folder(s) older than "
               f"{settings.raw_keep_days} days")


@app.command("prune-raw")
def prune_raw_cache() -> None:
    """Delete dated raw-cache folders (data/raw/<source>/<date>/) older than
    RAW_KEEP_DAYS — the same step `pipeline daily` runs in its tail."""
    _prune_raw()


def _register_pipeline_commands() -> None:
    from hb.pipelines import JOBS, run_job
    from hb.pipelines.schedule import CATCH_UP

    def make(job_name: str):
        def run() -> None:
            status = run_job(job_name)
            typer.echo(f"{job_name}: {status}")
            if status == "failed":
                raise typer.Exit(1)

        if job_name not in CATCH_UP:
            def cmd() -> None:
                _ready_db()
                run()
        else:
            def cmd(catch_up: bool = typer.Option(False, "--catch-up", help=CATCH_UP_HELP)) -> None:
                _ready_db()
                if catch_up and _caught_up(job_name):
                    return
                run()

        cmd.__doc__ = f"Run the {job_name} pipeline job."
        return cmd

    for name in JOBS:
        # take options — registered explicitly below
        if name in ("enrich", "backfill-sales", "price-history", "hazards-fetch"):
            continue
        pipeline_app.command(name)(make(name))


_register_pipeline_commands()


@pipeline_app.command("hazards-fetch")
def pipeline_hazards_fetch(
    if_missing: bool = typer.Option(
        False, "--if-missing",
        help="fetch only the layers with no file on disk yet (what `make load` passes)"),
) -> None:
    """Download the pack's hazard polygon layers for the geography to
    data/raw/hazards/ (docs/05 s.16). Standalone, not daily: rerun without
    --if-missing when a state re-releases its zones."""
    from hb.pipelines import hazards_fetch

    _ready_db()
    status = hazards_fetch.run(missing_only=if_missing)
    typer.echo(f"hazards-fetch: {status}")
    if status == "failed":
        raise typer.Exit(1)


@pipeline_app.command("enrich")
def pipeline_enrich(
    property_id: str = typer.Option(None, "--property-id", help="enrich one property"),
    all_tracked: bool = typer.Option(False, "--all-tracked", help="enrich all tracked listings"),
) -> None:
    """Enrich a property (or all tracked) via Realtor.com/RentCast/Zestimate."""
    from hb.pipelines import enrich

    if not property_id and not all_tracked:
        all_tracked = True  # default: refresh the tracked set
    _ready_db()
    status = enrich.run(property_id=property_id, all_tracked=all_tracked)
    typer.echo(f"enrich: {status}")
    if status == "failed":
        raise typer.Exit(1)


@pipeline_app.command("price-history")
def pipeline_price_history(
    limit: int = typer.Option(None, "--limit", help="max properties to fetch this run"),
) -> None:
    """Backfill Realtor sale/listing timelines across inventory + the comp pool,
    then replay them onto sales (price cuts, true original list, DOM/CDOM). A
    full pass is thousands of ~1 s scrapes — use --limit for resumable chunks."""
    from hb.pipelines import price_history

    _ready_db()
    status = price_history.run(limit=limit)
    typer.echo(f"price-history: {status}")
    if status == "failed":
        raise typer.Exit(1)


@pipeline_app.command("backfill-sales")
def pipeline_backfill_sales(
    months: int = typer.Option(24, help="how many months of sold history to pull"),
    date_from: str = typer.Option(None, "--date-from", help="ISO start date (overrides --months)"),
    date_to: str = typer.Option(None, "--date-to", help="ISO end date (default today)"),
) -> None:
    """One-time historical comp backfill: pull closed single-family sales over a
    wide date range so the golden backtest has prior comps to work with."""
    from hb.pipelines import backfill_sales

    _ready_db()
    status = backfill_sales.run(months=months, date_from=date_from, date_to=date_to)
    typer.echo(f"backfill-sales: {status}")
    if status == "failed":
        raise typer.Exit(1)


@alerts_app.command("send")
def alerts_send() -> None:
    """Check for failing listing scans, then deliver undelivered alerts via the configured
    channels (log/toast/pushover/email)."""
    from hb.alerts.channels import deliver_pending
    from hb.alerts.rules import check_scan_failure
    from hb.db.engine import make_session

    _ready_db()
    with make_session() as session:
        if check_scan_failure(session):
            session.commit()
        typer.echo(f"delivered: {deliver_pending(session)}")


@app.command()
def serve() -> None:
    """Run the LAN server (API + built SPA): plain HTTP on 18800, bound on
    0.0.0.0 (hb/serve.py; port via HB_HTTP_PORT). Applies pending migrations
    first, so a fresh clone serves a seeded database."""
    from hb.serve import run

    _warn_if_example()
    _ready_db()
    run()


def _choose(question: str, options: list[str]) -> int:
    """Print a numbered list and return the index picked — by number or by a
    unique part of the name ('central'), since people type either."""
    for i, option in enumerate(options, 1):
        typer.echo(f"  {i}) {option}")
    while True:
        raw = typer.prompt(question, default="1").strip().casefold()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        hits = [i for i, option in enumerate(options) if raw and raw in option.casefold()]
        if len(hits) == 1:
            return hits[0]
        typer.echo(f"  Type a number from 1 to {len(options)}.")


@app.command()
def setup(
    state: str | None = typer.Option(None, help="state, e.g. TX or Texas"),
    cities: str | None = typer.Option(None, help="comma-separated city names"),
    price: str | None = typer.Option(None, help="price range, e.g. 500k-800k or 1.2m-1.8m"),
    timezone: str | None = typer.Option(None, help="IANA time zone, for a state with several"),
    fred_key: str | None = typer.Option(None, help="free FRED API key (mortgage rates)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="take every default; ask nothing"),
) -> None:
    """Choose your area: asks for your state, cities and price range, fills in
    ZIPs, counties, tax rates and the map from Census data, and writes
    geography.toml (plus .env on a first run). docs/packs/README.md s.1."""
    import zipfile

    import httpx

    from hb import config, setup_geo
    from hb.config import settings

    def ask(text: str, given: str | None, flag: str) -> str:
        if given is not None:
            return given
        if yes:
            raise typer.BadParameter(f"--yes needs --{flag}")
        return typer.prompt(text)

    # --- state: 'TX', 'Texas', a typo with one close match, or a reason why not
    answer = ask("State (e.g. TX or Texas)", state, "state")
    all_states = setup_geo.states()
    while True:
        st, close, why = setup_geo.parse_state(answer, all_states)
        if st:
            break
        if len(close) == 1 and not yes and typer.confirm(
                f"  {why} Did you mean {close[0].name}?", default=True):
            st = close[0]
            break
        hint = (" Did you mean " + ", ".join(c.name for c in close) + "?") if close else ""
        if yes:
            raise typer.BadParameter(f"{why}{hint}")
        answer = typer.prompt(f"  {why}{hint}\nState")

    # --- cities: resolved right away against the Census files, so a typo or a
    # neighborhood is caught here, not after the other questions
    answer = ask("Cities or towns you're shopping in, comma-separated (e.g. Austin, Round Rock)",
                 cities, "cities")
    ref = None
    chosen: list[setup_geo.Place] = []
    while not chosen:
        names, rejected = setup_geo.split_cities(answer, st)
        for token, reason in rejected:
            typer.echo(f"  Skipping {token!r}: {reason}.")
        if names and ref is None:
            if setup_geo.needs_download():
                typer.echo("Downloading Census reference data (about 75 MB, first run only)...")
            try:
                ref = setup_geo.load_reference(st)
            except (httpx.HTTPError, OSError, zipfile.BadZipFile) as exc:
                typer.echo(f"Could not download the Census reference data ({exc}). Check your "
                           "internet connection and run `make setup` again; nothing was saved.",
                           err=True)
                raise typer.Exit(1) from exc
        for name in names:
            m = setup_geo.match_city(ref, name)
            if m.obvious or (m.candidates and yes):
                chosen.append(m.obvious or m.candidates[0])
            elif m.candidates:
                typer.echo(f"There is more than one {name} in {st.name}:")
                pick = _choose("Which one", [setup_geo.describe(ref, p) for p in m.candidates])
                chosen.append(m.candidates[pick])
            elif m.suggestions and not yes and typer.confirm(
                    f'  "{name}" is not a city or town in {st.name}. Did you mean '
                    f"{setup_geo.describe(ref, m.suggestions[0])}?", default=True):
                chosen.append(m.suggestions[0])
            else:
                hint = (" Close matches: " + ", ".join(p.name for p in m.suggestions) + "."
                        if m.suggestions else "")
                if yes:
                    raise typer.BadParameter(f"no city or town named {name!r} in {st.name}.{hint}")
                typer.echo(f"  Skipping {name}: no city or town by that name in {st.name}.{hint}"
                           " If it is a neighborhood, give its city; if it is in another state,"
                           " run `make setup` again for that state (one state per setup).")
        chosen = list(dict.fromkeys(chosen))
        if not chosen:
            if yes:
                raise typer.BadParameter("no city names given")
            answer = typer.prompt("  Type at least one city or town\nCities")

    # --- price range, as people write it; the summary echoes it in dollars
    if price is None and not yes:
        typer.echo("The price range sets alerts and default filters; every listing is still loaded.")
    answer = ask("Price range (e.g. 500k-800k or 1.2m-1.8m)", price, "price")
    band = None
    while band is None:
        try:
            band = setup_geo.parse_price_band(answer)
        except ValueError as exc:
            if yes:
                raise typer.BadParameter(str(exc)) from exc
            answer = typer.prompt(f"  {exc}\nPrice range")

    # --- time zone, only where the state has more than one
    zone = timezone or st.zones[0]
    if timezone is None and len(st.zones) > 1 and not yes:
        labels = setup_geo.zone_labels()
        typer.echo(f"{st.name} has more than one time zone:")
        zone = st.zones[_choose("Which one are your cities in",
                                [f"{labels.get(z, z)} ({z})" for z in st.zones])]

    # --- FRED key: optional; shown as typed, cleaned of quotes and a KEY= prefix
    env_path = config._REPO_ROOT / ".env"
    env_text = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    has_fred = bool(setup_geo.env_value(env_text, "FRED_API_KEY") or settings.fred_api_key)
    if fred_key is not None:
        fred_key, warning = setup_geo.clean_fred_key(fred_key)
        fred_key = fred_key or None
        if warning:
            typer.echo(f"  Note: {warning}", err=True)
    elif not has_fred and not yes:
        while True:
            typed = typer.prompt("FRED API key for mortgage rates, free at "
                                 "fred.stlouisfed.org/docs/api/api_key.html (Enter to skip)",
                                 default="", show_default=False)
            key, warning = setup_geo.clean_fred_key(typed)
            if not key:
                break
            if warning and not typer.confirm(f"  {warning} Save it anyway?", default=False):
                continue
            fred_key = key
            break

    # --- the plan, echoed back before anything is written
    try:
        plan = setup_geo.make_plan(ref, chosen, zone, *band)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    text = setup_geo.render(plan)

    typer.echo("")
    for line in setup_geo.summary(plan):
        typer.echo(line)
    target = settings.geography_file or config._REPO_ROOT / "geography.toml"
    replaced = target.is_file()  # running setup is the decision; no second question
    target.write_text(text, encoding="utf-8")
    typer.echo(f"{'Replaced' if replaced else 'Saved'} {target}.")
    done = setup_geo.write_env(config._REPO_ROOT, fred_key)
    if done:
        typer.echo(done)
    typer.echo("Next: make start  (the first run takes an hour or more; it prints its progress)")


@schedule_app.command("install")
def schedule_install() -> None:
    """Make the operating system run the scans on its own, as you, with no
    administrator: hourly Task Scheduler jobs (Windows), launchd agents (macOS),
    systemd --user timers or a crontab block (Linux). `make start` runs this;
    run it again after moving the checkout."""
    from hb import schedule_install as installer

    try:
        lines = installer.install()
    except RuntimeError as exc:
        typer.echo(f"schedule: {exc}", err=True)
        raise typer.Exit(1) from exc
    for line in lines:
        typer.echo(f"schedule: {line}")


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Remove what `hb schedule install` set up."""
    from hb import schedule_install as installer

    for line in installer.remove():
        typer.echo(f"schedule: {line}")


@app.command()
def backtest(n: int = typer.Option(20, help="number of recent sales to backtest")) -> None:
    """Golden CMA/overbid backtest (docs/10 §4) — the CMA credibility gate."""
    from hb.backtest import run_backtest, write_report
    from hb.db.engine import make_session

    _ready_db()
    with make_session() as session:
        report = run_backtest(session, n)
    path = write_report(report)
    mdape = f"{report.mdape:.2%}" if report.mdape is not None else "n/a"
    coverage = f"{report.coverage:.0%}" if report.coverage is not None else "n/a"
    typer.echo(f"backtest: n_used={report.n_used} MdAPE={mdape} coverage={coverage} "
               f"-> {'PASS' if report.passed else 'FAIL'}")
    mf = report.midflight
    if mf:
        ok = mf["calibration_ok"]
        prec = mf["overpriced_precision"]
        typer.echo(f"posture (pass B, n={mf['n']}): calibration "
                   f"{'PASS' if ok else 'FAIL' if ok is False else 'n/a'}; overpriced "
                   f"medium+high sold below asking "
                   f"{f'{prec['precision']:.0%}' if prec['precision'] is not None else 'n/a'} "
                   f"(n={prec['n']})")
    if report.note:
        typer.echo(report.note, err=True)
    typer.echo(f"report: {path}")
    if not report.passed:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

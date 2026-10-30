# 12 — API keys & data bootstrap

How to obtain every external credential the platform can use, and how to seed
enough sales history for the golden backtest to run. All keys go in a single
`.env` at the **repo root** (copy `.env.example` → `.env`; loaded by
`hb/config.py`, which also reads `backend/.env` as a fallback). Never commit
`.env`.

## At a glance

| Service | Env var(s) | Cost | Required for | Fails cleanly if absent? |
|---|---|---|---|---|
| **Realtor.com** | *(none)* | free, no key | enrich: home-value estimate, details, gallery photos; `price-history`: sale/listing price history | yes — network only |
| **FRED** | `FRED_API_KEY` | free | `hb pipeline fred` (mortgage-rate chart, affordability) | yes — run recorded as `noop`; affordability and offer math assume 6.5% |
| **RentCast** | `RENTCAST_API_KEY`, `RENTCAST_MONTHLY_LIMIT` | free tier 50/mo | enrich: RentCast AVM + comps | yes — recorded miss, run continues |
| **Zillow (RapidAPI)** | `ZILLOW_WRAPPER_ENABLED`, `RAPIDAPI_KEY` | free tier varies | enrich: Zestimate (optional) | yes — skipped when disabled |
| **SchoolDigger** | `SCHOOLDIGGER_APP_ID`, `SCHOOLDIGGER_APP_KEY`, `SCHOOLDIGGER_DAILY_LIMIT` | free developer plan, 20 calls/day | `hb pipeline schooldigger-ratings` (statewide school rankings on the Schools card) | yes — run recorded as `noop` |
| **CAASPP** (California only) | `CAASPP_YEAR` | free, no key | `hb pipeline school-ratings` (state test-score decile, the `ca` pack's primary rating source) | yes — `noop` outside California |
| **Pushover** | `PUSHOVER_TOKEN`, `PUSHOVER_USER` | one-time app purchase per phone platform | `pushover` alert channel (phone push) | yes — the channel reports failure; any other channel in `ALERT_CHANNELS` still delivers |
| **SMTP (email alerts)** | `SMTP_*`, `ALERT_EMAIL_TO` | free (Gmail app pw) | `email` alert channel | yes — the channel reports failure; any other channel in `ALERT_CHANNELS` still delivers |

Nothing above blocks core valuation: the CMA and overbid models run on scraped
`sales` + the derived price index with **no keys at all**. Keys only add the
third-party AVMs shown in the multi-AVM spread, the mortgage-rate series,
SchoolDigger's school rankings, and the phone-push and email alert channels.

---

## Realtor.com — no key needed

The enrich pipeline calls Realtor.com's `frontdoor/graphql` endpoint directly over
`httpx` (`hb/pipelines/realtor_gql.py`; no SDK, no key) for the home-value estimate
(`avm_snapshots(source='realtor_estimate')`), the property details it NULL-fills and
the gallery photos; the `price-history` job uses the same endpoint for the
sale/listing price history. There is nothing to sign up for. It just needs network
access; the enrich pipeline already rate-limits to ~1 request/second. Because these
are unofficial endpoints they can change without notice — a failure is recorded as
a miss and the rest of the enrich run continues.

## FRED (mortgage rates)

Used by `hb pipeline fred` to pull `MORTGAGE30US` / `MORTGAGE15US` and the geography's optional metro Case-Shiller series.

1. Create a free account at <https://fred.stlouisfed.org/> (top-right "My Account").
2. Go to **API Keys**: <https://fredaccount.stlouisfed.org/apikeys>.
3. Click **Request API Key**, accept the terms — the key is issued instantly
   (a 32-char hex string), no approval wait.
4. Put it in `.env`:
   ```
   FRED_API_KEY=your32charhexkey
   ```
5. Verify: `hb pipeline fred` → status `ok`; the Dashboard rate chart fills in.

Without a key the job logs a one-line hint and records a `noop` run, so `make daily` stays
clean; the rate chart stays empty, there is no Case-Shiller series, and affordability and
offer math use the buyer profile's rate if set, else 6.5%. `make setup` offers to save the key.

## RentCast (AVM + comps)

Used by enrich for a second AVM and to import comparable sales.

1. Sign up at <https://app.rentcast.io/app/api>.
2. The **Developer** (free) tier grants **50 requests/month** — no credit card.
3. In the dashboard open **API Keys → Create API Key** and copy it.
4. Put it in `.env` and keep the budget guard just under your plan limit:
   ```
   RENTCAST_API_KEY=your-rentcast-key
   RENTCAST_MONTHLY_LIMIT=45
   ```
   The guard (an AppSetting counter surfaced in `/api/ops/health` as
   `rentcast_quota_remaining`) refuses the call once the monthly count is hit —
   no accidental overage — and resets at each month boundary.
5. Verify: on a listing detail page click **Refresh estimates**, or run
   `hb pipeline enrich --property-id <id>`; a `rentcast` dot appears in the AVM
   spread and the quota decrements.

## Zillow / Zestimate (optional, via RapidAPI)

Off by default and breakage-prone (third-party scraper of Zillow); enable only
if you want a Zestimate dot in the spread.

1. Create a free RapidAPI account at <https://rapidapi.com/>.
2. Subscribe to a Zillow API served at host **`zillow-com1.p.rapidapi.com`**
   (search RapidAPI for "Zillow"; the free tier is limited, e.g. a few hundred
   calls/month). Subscribing to any RapidAPI product activates your single
   RapidAPI key.
3. Copy your key from **RapidAPI → Apps → default → Security → Application Key**
   (the `X-RapidAPI-Key` value).
4. Put it in `.env` **and turn the wrapper on**:
   ```
   ZILLOW_WRAPPER_ENABLED=true
   RAPIDAPI_KEY=your-rapidapi-key
   ```
   With `ZILLOW_WRAPPER_ENABLED=false` (the default) the Zestimate step is
   skipped entirely regardless of the key.

## SchoolDigger (school rankings)

Used by `hb pipeline schooldigger-ratings` (part of the daily sequence) for a statewide
school ranking on the listing page's Schools card — the only rating source under the `us`
base pack, and the second one beside CAASPP under `ca`.

1. Sign up for the free developer plan at <https://developer.schooldigger.com/>.
2. Copy the application's **App ID** and **App Key**.
3. Put them in `.env` and keep the budget guard under the plan's 20 calls/day:
   ```
   SCHOOLDIGGER_APP_ID=your-app-id
   SCHOOLDIGGER_APP_KEY=your-app-key
   SCHOOLDIGGER_DAILY_LIMIT=18
   ```
   The job rates only the districts assigned to homes in the database, 1–3 calls each,
   keeps its progress in the `settings` table and stops cleanly when the day's budget runs
   out or the API answers 429 — it converges over a few daily runs, so do not spend the
   quota on ad-hoc test calls.
4. Verify: `hb pipeline schooldigger-ratings` → status `ok` (`noop` once every assigned
   district is rated); a `SchoolDigger` badge appears beside each school on a listing's
   Schools card.

Without credentials the job records a `noop`.

## CAASPP (California only, no key)

`hb pipeline school-ratings` downloads the state's CAASPP research files for `CAASPP_YEAR`
(default `2024`; bump it after each annual release) into `data/raw/caaspp/<date>/` and
writes the test-score decile that is the `ca` pack's primary rating badge. Outside
California it records a `noop`. Nothing to sign up for.

## Pushover (phone push alerts)

Only needed if you add `pushover` to `ALERT_CHANNELS`. An application token can only send
to the user key it is paired with, so a leaked pair lets someone page you and nothing more;
regenerate it on the Pushover dashboard if that ever happens.

1. Create an account at <https://pushover.net/> and install the phone app (a one-time
   purchase per phone platform after the trial).
2. On the dashboard copy your **user key**, then **Create an Application** (name it `hb`)
   and copy its **API token**.
3. Put both in `.env`:
   ```
   ALERT_CHANNELS=pushover
   PUSHOVER_TOKEN=your-app-token
   PUSHOVER_USER=your-user-key
   ```
   Run it alone on a headless server: an alert counts as delivered once any channel
   succeeds and `log` always succeeds, so `pushover,log` would mark a failed push delivered
   (`11` §2a).
4. Verify: `hb alerts send` with a pending alert pushes a notification whose **Open** link
   is the listing page; a rejected or unreachable push leaves the alert for the next run.

## Email alerts (optional SMTP)

Only needed if you add `email` to `ALERT_CHANNELS` (default is `toast,log`: a Windows
desktop notification plus one line per alert in the server log, neither needing anything;
`pushover` above is the phone-push channel). For Gmail, create an **App
Password** (Google Account → Security → 2-Step Verification → App passwords) and
set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`,
`ALERT_EMAIL_TO`.

---

## Bootstrapping sales history for the golden backtest

`hb backtest --n 20` (docs/10 §4) re-values recent sales **as of the day before
each was listed**, which means it needs comps that had already closed *before*
that date. A fresh install fails the gate not because the model is wrong but
because the daily `listing-scan` only captures `sold` records from the last 30
days — so a mid-June listing has only a few days of prior sales and lands 1–3
weak comps. The math itself is proven by the §4.3 / §5.5 unit gates.

**Fix — a one-time historical backfill.** HomeHarvest supports a `date_from` /
`date_to` window on `sold` listings, so we can pull 1–2 years of closed
single-family sales in one pass and drop them straight into `sales`:

```
hb pipeline backfill-sales --months 24
# or an explicit window:
hb pipeline backfill-sales --date-from 2023-01-01 --date-to 2025-12-31
```

This job (`hb/pipelines/backfill_sales.py`) is **comp-only**: it resolves
properties and upserts `sales` rows but creates no listings, events, or alerts,
so backfilling years of solds never spams the timeline or the alert inbox. It is
idempotent on the `(property_id, sale_date)` key — safe to re-run, and safe to
run alongside the daily scan (which keeps history fresh going forward).

Caveats for backfilled comps: we only see the *final* list price of an old
episode, so `original_list_price` uses that as a proxy and `had_price_cut` is set
`false` (treated as "fresh") — good enough for the distribution, and live scans
supply the richer signal for current listings.

After backfilling, rebuild the index and re-run the gate:

```
hb pipeline backfill-sales --months 24
hb pipeline build-index          # refresh the price index over the deeper data
hb backtest --n 20               # now has real prior comps; tune knobs if needed
```

If the gate still misses after a genuine backfill, tune the knobs recorded in
`data/backtests/<date>.md` (m factor, similarity/overbid half-lives, shrinkage
`k`) and re-run — that report exists precisely to drive the tuning loop.

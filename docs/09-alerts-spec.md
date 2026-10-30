# 09 — Alerts Spec

Alerts are **written to the `alerts` table first** (by rule evaluation), then **delivered** by a separate step (`hb alerts send`). This decouples detection from delivery and makes both idempotent.

## 1. Pipeline position
`alerts/rules.py` runs inside `listing-scan` (05 §4.5) — after relist stitching and the auto-enrich of tracked homes (so RentCast comps feed `new_comp_sold`), before the price-history refresh, the photo download and the `open-houses` tail — and evaluates rules over (a) this run's `listing_events`, (b) current tracker / Watchlist state and the latest `pipeline_runs` → inserts `alerts` rows (dedup-keyed) → the hourly (:30) `hb alerts send` delivers undelivered rows via enabled channels and stamps `delivered_at`. A first scan (no completed `listing-scan` in `pipeline_runs` yet, `listing_scan._first_scan`) evaluates no rules at all: every home is new to the database, not to the buyer, and a fresh install must not open with an alert for each listing in its band. Alerts start with the second scan, which sees what changed.

## 2. Rules

| type | Trigger | Scope | Payload highlights |
|---|---|---|---|
| `price_cut` | `price_change` event with new < old | any active listing in target area within the target price band ±20% (`[price_band]` in `geography.toml`); always for tracked and for watched (Watchlist homes, 08 §5b) at any price | old/new price, % cut, cut count |
| `relist` | `relisted` event | same scope as price_cut | cumulative_dom, episode_count |
| `back_on_market` | pending→active event | same scope as price_cut | none (`{}`) |
| `watched_status` | `pending`, `sold` or `delisted` event | watched: every home on the Watchlist (watched, tracked or toured, until removed) | event, list / original list price, sold price (on `sold`), the tracker's `my_max_bid` |
| `new_listing_match` | `new` event AND list price within the geography's `[price_band]` AND its ZIPs AND beds ≥ `min_beds` | band and ZIPs from config; `min_beds` from the alert rules settings | `{price, zip, beds, sqft}` |
| `new_comp_sold` | new `sales` row within `radius_mi` (0.5) of any tracked listing's property | tracked | comp address, price, $/sqft, distance, DOM |
| `offer_date_soon` | `offer_due_at` within 3 days (then again at 1 day) | tracked | due date, days left |
| `deal_deadline_soon` | a closing task on an **open** deal falls due within 3 days (then again at 1 day) | open deals (14) | task key, label, due date, days left, blocking |
| `deal_deadline_overdue` | a **blocking** closing task on an open deal is past due | open deals | task key, label, due date |
| `scan_failure` | the last two finished `listing-scan` runs in `pipeline_runs` (a `running` row is skipped) are both `failed`; checked by `hb alerts send` (`rules.check_scan_failure`), since a failed scan never reaches its own rule pass | ops | the two runs' `started_at` |

The `alert_rules` settings JSON row (seeded by the initial migration, editable via `PUT /api/alerts/rules`, 08 §8) is read for each rule's `enabled` flag, `new_listing_match.min_beds` (default 3) and `new_comp_sold.radius_mi` (default 0.5). The ±20 % band widening (`_in_band(widen=0.20)`) and the offer-date buckets `[3, 1]` are constants in `rules.py`; the seeded `price_band_pct`, `days_buckets`, `consecutive_days` and `bps_threshold` keys are not read by any rule.

**Tracked vs watched.** *Tracked* means a tracker row in an active stage (not `won`/`lost`/`passed`); it carries `alerts.tracked_listing_id` and drives `new_comp_sold` and `offer_date_soon`. *Watched* is the wider Watchlist set (`hb.watchlist.watched_property_ids`), matched on the **property**, so a relisted home's new listing row is still in scope: it keeps price cuts, relists and back-on-market flowing after the buyer stops pursuing a home, and `watched_status` reports how it ended. A home the buyer passed on carries no `tracked_listing_id`.

## 3. Dedup (binding)
`alerts.dedup_key` is UNIQUE; inserts use INSERT-or-ignore semantics (`sqlite.insert().on_conflict_do_nothing()` in `alerts/rules.py` `_insert` and `pipelines/deal_deadlines.py`). Construction:
- event-driven types: `{type}:{listing_id}:{event.observed_at}:{event.new_value}` — same underlying event never alerts twice, even if rules re-run.
- `new_comp_sold`: `{type}:{tracked_listing_id}:{sale_id}`
- `offer_date_soon`: `{type}:{tracked_listing_id}:{offer_due_at}:{days_left_bucket}` (buckets 3 and 1 ⇒ max two alerts per deadline)
- `deal_deadline_soon`: `{type}:{deal_id}:{task_key}:{due_on}:{days_left_bucket}` (buckets 3 and 1). The due date is in the key, so moving `accepted_on` re-dates the task and legitimately re-alerts.
- `deal_deadline_overdue`: `{type}:{deal_id}:{task_key}:{due_on}` ⇒ one alert per missed deadline, not one per day.
- `watched_status`: `{type}:{event_type}:{listing_id}:{event.observed_at}:{event.new_value}` — the event-driven key prefixed with the event that ended (or paused) the home's run.
- `scan_failure`: `{type}:{date}` ⇒ at most one alert per day while the streak lasts

Both `deal_deadline_*` rules are evaluated by the `deal-deadlines` job (05 §15), **not** by
`listing-scan` — they depend on the calendar rather than on scraped events, so they must fire
on a day when nothing was scraped. Only `blocking` tasks raise the overdue alert: the point is
to shout about the deposit, not to nag about registering appliance warranties. Completed and
waived tasks, and tasks belonging to a waived contingency, never alert.

## 4. Delivery channels (`alerts/channels.py`)
- **Log**: one INFO line per alert in the server/CLI log. Works on every OS and always succeeds, so it is the portable default.
- **Desktop toast**: `win11toast`, Windows-only adapter (no-ops elsewhere). Title = the type with underscores as spaces (`price cut`), body = message, click-through URL to the listing page. `win11toast` blocks until the toast is dismissed or times out (about six seconds); `deliver_pending` commits each alert before the next toast, so that wait never holds the SQLite write lock and the API keeps writing meanwhile.
- **Pushover**: phone push via `api.pushover.net` (`PUSHOVER_TOKEN`, `PUSHOVER_USER`). One push per alert: title = the type with underscores as spaces, body = message, the listing page (`APP_BASE_URL`) as the tap-through URL. Unconfigured, rejected (non-200 or `status != 1`) or unreachable all count as a failed channel. An application token can only send to its user key, so the pair in `.env` is worth nothing to an attacker beyond paging you; `_pushover_post` is the test seam.
- **Email**: SMTP (Gmail app password via `SMTP_HOST/PORT/USER/PASSWORD`, `ALERT_EMAIL_TO`). One digest email per delivery run when > 3 undelivered alerts; individual emails otherwise. HTML body with listing links (`APP_BASE_URL`).
- Channel enablement: `ALERT_CHANNELS` (default `toast,log`; add `pushover` for phone push, `email` for SMTP). Delivery marks `delivered_at` + `channel`; a failed channel leaves the row undelivered for the next run (retry-safe) — note that with `log` enabled every alert succeeds on the first pass, so a toast or push failure next to it is logged, not retried. On a headless server run `pushover` (or `email`) alone.

## 5. Message rendering
A formatter per type in `channels.py` (`format_alert`), plain-language, with a generic fallback `"{type} — {address}"` for any type without one, e.g.
`price_cut`: "↓ $50,000 (2.3%) — 123 Main St, Sunnyvale now $2,100,000. Cut #2."
`new_comp_sold`: has no formatter and renders as the fallback "new_comp_sold — 456 Oak Ave, Sunnyvale" (the tracked home's address; the comp address, price, $/sqft, distance and DOM stay in `payload`, which `GET /api/alerts` returns).
`watched_status`: "Watched home sold — 123 Main St, Sunnyvale for $1,620,000 (+4.0% vs original ask). $40,000 over your max bid." / "Watched home went pending — 123 Main St, Sunnyvale, asking $1,450,000." / "Watched home taken off the market — 123 Main St, Sunnyvale."

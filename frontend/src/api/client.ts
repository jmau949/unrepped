// Typed API client — shapes mirror docs/07-api-spec.md (kept in sync by hand).

export interface Health {
  db: string;
  last_scan: string | null;
  /** the scheduled scan slot (UTC ISO) missed by >2 h; null = scans on schedule */
  scan_overdue_since: string | null;
  rentcast_quota_remaining: number | null;
}

export interface PipelineRunInfo {
  id: string;
  job: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "noop" | "partial" | "failed";
  items_seen: number;
  items_upserted: number;
  events_emitted: number;
  error_summary: string | null;
}

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init);
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return resp.json() as Promise<T>;
}

/** Abort after `ms`. Hand-rolled rather than `AbortSignal.timeout`, which older
 * iOS Safari lacks — and iOS is exactly where a stalled TLS handshake happens. */
function timeoutSignal(ms: number): AbortSignal {
  const ctrl = new AbortController();
  setTimeout(() => ctrl.abort(new Error(`timed out after ${ms}ms`)), ms);
  return ctrl.signal;
}

export interface TargetBand {
  min: number;
  max: number;
}

export type SummaryMetrics = Record<string, number | null>;

export interface ZipSummary {
  geo_id: string;
  city: string | null;
  metrics: SummaryMetrics;
  deltas_90d: SummaryMetrics;
  /** per-metric provenance of the latest value: redfin | derived | derived_city */
  sources: Record<string, string | null>;
}

export interface MarketSummary {
  target_band: TargetBand;
  zips: ZipSummary[];
}

export interface SeriesPoint {
  period_start: string;
  value: number;
  source: string;
}

export interface RatePoint {
  date: string;
  value: number;
}

/** The connectivity probe behind the header badge (Layout.tsx). Bounded so a
 * hung connection — a device that cannot complete the TLS handshake against the
 * LAN origin — reports "API unreachable" instead of sitting on "checking…" for
 * the browser's own multi-minute timeout. Only this call is bounded; the slow
 * endpoints (enrich, brief) keep the default. */
export const getHealth = () => get<Health>("/api/ops/health", { signal: timeoutSignal(8_000) });

export const getPipelineRuns = (job?: string, limit = 20) =>
  get<PipelineRunInfo[]>(
    `/api/ops/pipeline-runs?limit=${limit}${job ? `&job=${encodeURIComponent(job)}` : ""}`,
  );

export interface PredictedSale {
  low: number;
  point: number;
  high: number;
  basis: string;
  /** blended model value before the market-evidence adjustment (docs/06 §5.6) */
  unadjusted_point?: number;
  /** 0..1 — how credibly prolonged exposure says "value <= list"; 0 = untouched */
  rejection_weight?: number;
}

export type Posture = "underpriced" | "near_market" | "overpriced" | "unknown";

export interface PostureSignal {
  id: string;
  label: string;
  points: number;
  detail: string;
}

export interface PostureExposure {
  /** cumulative days over the campaign's episodes */
  days: number | null;
  /** days into the current episode (the clock a relist is judged on) */
  episode_days: number | null;
  episode_count: number;
  cuts: number;
  cut_source: "observed" | "history" | "relist_lower" | null;
  median_dom: number | null;
  /** exposure days / area median DOM */
  ratio: number | null;
  offer_passed: boolean;
}

export interface PostureOut {
  posture: Posture;
  /** tiers on max(p, 1 − p): ≥0.80 high, ≥0.65 medium */
  confidence: "low" | "medium" | "high";
  /** Σ signal points — log-odds of selling below the current asking price */
  logit: number | null;
  /** sigmoid(logit): P(sells below asking | it sells); null without exposure data */
  p_below_list: number | null;
  /** backtest-measured median sold/list for this posture */
  typical_sold_to_list: number | null;
  exposure: PostureExposure | null;
  /** list / unadjusted model value − 1 — informational, never a vote */
  value_gap_pct: number | null;
  /** share of such listings withdrawn rather than sold, once past 2× the area median */
  withdrawal_share: number | null;
  signals: PostureSignal[];
  agreement: "agree" | "moderate" | "diverge" | "unknown";
  spread_pct: number | null;
  rejection_weight: number;
  adjusted: { low: number; point: number; high: number } | null;
  unadjusted_point: number | null;
}

export interface ListingSummary {
  id: string;
  property_id: string;
  address: string;
  city: string | null;
  zip: string;
  lat: number | null;
  lon: number | null;
  status: string;
  list_price: number | null;
  original_list_price: number | null;
  sold_price: number | null;
  sold_date: string | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  list_date: string | null;
  dom_source: number | null;
  cumulative_dom: number | null;
  price_cut_count: number;
  /** % below the original ask; null when the price never came down */
  cut_pct: number | null;
  is_relist: boolean;
  predicted_sale: PredictedSale | null;
  posture: Posture | null;
  posture_confidence: "low" | "medium" | "high" | null;
  /** P(sells below the current asking price | it sells) — docs/06 §5.6 */
  posture_p_below_list: number | null;
  photo_url: string | null;
  url: string | null;
  tracked: boolean;
  /** first detail-page open (stamped by GET /api/listings/{id}); null = never viewed */
  viewed_at: string | null;
  /** soonest open house not yet over (UTC ISO); null when none is scheduled */
  next_open_house: { start_at: string; end_at: string } | null;
}

export interface ListingEvent {
  event_type: string;
  old_value: string | null;
  new_value: string | null;
  observed_at: string;
}

export interface ListingEpisode {
  listing_id: string;
  source: string;
  list_date: string | null;
  original_list_price: number | null;
  pending_date: string | null;
  delist_date: string | null;
  sold_date: string | null;
  sold_price: number | null;
  status: string;
}

export interface SchoolSourceRating {
  source: string; // a rating-source key of the configured pack (AppConfig.pack.rating_sources)
  rating_10: number | null; // normalized 1-10
  label: string | null; // source-native display, e.g. "#123 of 5,856 statewide"
}

export interface SchoolRating {
  name: string;
  level: string; // elementary | middle | high
  rating: number | null; // the pack's primary source, normalized 1-10 (null until rated)
  pct_met: number | null; // raw % met/exceeded standard, where that source is a state test
  distance_mi: number | null;
  district: string | null;
  assignment: string; // district (boundary match) | nearest (fallback) | zip
  ratings: SchoolSourceRating[];
}

export interface ListingDetail extends ListingSummary {
  offer_due_at: string | null;
  sold_price: number | null;
  sold_date: string | null;
  photos: string[];
  events: ListingEvent[];
  price_history: PriceHistoryEntry[];
  listing_group: {
    cumulative_dom: number | null;
    episode_count: number;
    ended_by: string;
    episodes: ListingEpisode[];
  } | null;
  property: {
    condition_tag: string | null;
    condition_notes: string | null;
    lot_sqft: number | null;
    year_built: number | null;
    assessor_sqft: number | null;
    sqft_mismatch: boolean;
    schools: SchoolRating[];
  };
  avm_snapshots: { source: string; value: number; low: number | null; high: number | null; as_of: string }[];
  hazard_flags: HazardFlagOut[];
  tracked_id: string | null;
  /** Tracker stage when tracked_id is set; null when not tracked. */
  tracked_stage: string | null;
  /** on the Watchlist (docs/08 §5b) */
  watching: boolean;
  posture_detail: PostureOut | null;
  /** The listing side off the MLS record; null when the source carried no advertiser. */
  listing_contact: ListingContact | null;
  /** Contacts saved on this listing by hand (owner of record, a second agent, …). */
  contacts: Contact[];
  /** The listing agent's public remarks off the source record; null when it carried none. */
  remarks: string | null;
  /** Every open-house slot not yet over, soonest first; [] once the home is no longer active. */
  open_houses: ListingOpenHouse[];
  /** IANA zone the market lives in — render open-house times in it, not the device's. */
  timezone: string;
}

/** An open house as the detail page sees it — the slot itself, without the
 *  home (the page already is the home) or a distance (no origin here). */
export type ListingOpenHouse = Omit<OpenHouse, "listing_id" | "distance_mi" | "listing">;

export interface ContactPhone {
  /** ten digits, no punctuation — build tel:/sms: links from this */
  number: string;
  type: "mobile" | "office" | "home" | "toll_free" | "other";
  primary: boolean;
  /** true only for mobile lines — the ones an sms: link can reach */
  sms: boolean;
}

/** Parsed from `listings.raw` by hb/listing_contact.py (docs/07 §Listings). */
export interface ListingContact {
  agent: {
    name: string;
    email: string | null;
    phones: ContactPhone[];
    mls_id: string | null;
    nrds_id: string | null;
  } | null;
  office: { name: string; email: string | null; phones: ContactPhone[] } | null;
  broker: { name: string } | null;
  builder: { name: string } | null;
  mls: { system: string | null; id: string | null } | null;
}

export interface ListingFilters {
  status?: string;
  city?: string;
  zip?: string;
  /** free text over address / city / unit / ZIP prefix; tokens are ANDed */
  q?: string;
  min_price?: number | null;
  max_price?: number | null;
  min_sold_price?: number | null;
  max_sold_price?: number | null;
  min_beds?: number;
  has_price_cut?: boolean;
  /** minimum reduction off the original ask, in percent */
  min_cut_pct?: number;
  stale_only?: boolean;
  sort?: string;
}

export interface TrackedItem {
  id: string;
  stage: string;
  notes: string | null;
  my_max_bid: number | null;
  disclosure_checklist: Record<string, unknown>;
  offer_due_at: string | null;
  /** Set once a deal exists for this listing — the hand-off to /closing. */
  deal_id: string | null;
  cma_estimate: number | null;
  overbid_point: number | null;
  listing: ListingSummary;
}

export interface AlertItem {
  id: string;
  type: string;
  message: string;
  listing_id: string | null;
  created_at: string;
  delivered_at: string | null;
}

export interface Profile {
  cash_available: number;
  down_payment: number; // dollars
  rate_assumption: number | null;
  appraisal_gap_tolerance_pct: number;
  insurance_monthly_est: number;
  include_earthquake_ins: boolean;
  target_zips: string[];
  /** gross dollars per year; 0 = not entered (no payment limit) */
  annual_income: number;
  /** other monthly debt payments: car, student loans, card minimums */
  monthly_debts: number;
}

export interface HazardFlagOut {
  /** a hazard layer key of the configured pack (AppConfig.pack.hazards) */
  hazard: string;
  zone_value: string | null;
}

export interface CompareItem extends Omit<ListingSummary, "tracked"> {
  cma: { estimate: number; low: number | null; high: number | null; created_at: string } | null;
  piti_at_point: number | null;
  price_per_sqft: number | null;
  hazard_flags: HazardFlagOut[];
  sqft_mismatch: boolean;
  tracked: {
    stage: string;
    my_max_bid: number | null;
    disclosure_checklist: Record<string, unknown>;
  } | null;
}

export interface OfferSolution {
  max_defensible_bid: number;
  cma_estimate: number | null;
  predicted: PredictedSale | null;
  verdict: string;
  verdict_template: string;
  escalation_cap: number;
  gap_capped: boolean;
  ltv_capped: boolean;
  /** the income-based payment limit was the binding constraint */
  payment_capped: boolean;
  /** the price each limit allows; the max is the lowest. payment is null without income */
  limits: { cash: number; down_payment: number; payment: number | null };
  e_basis: string;
  recommendation: "underbid" | "at_list" | "overbid" | null;
  opening_range: { low: number; high: number } | null;
  /** value-justified cap (= escalation_cap), never above max_defensible_bid */
  ceiling: number;
  posture: Omit<PostureOut, "adjusted" | "unadjusted_point"> | null;
  confidence: "low" | "medium" | "high" | null;
}

export interface CalcResult {
  piti: number;
  breakdown: Record<string, number>;
  closing_est: number;
  cash_needed: number;
  supplemental_tax_note: string;
  reserves_after: number;
  reserves_ok: boolean;
  rate_used: number;
  tax_rate_used: number;
  /** max housing payment from income (43% of gross, less other debts); null without income */
  payment_limit: number | null;
  payment_ok: boolean | null;
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${method} ${path} -> ${resp.status}`);
  return resp.json() as Promise<T>;
}

export function getListings(filters: ListingFilters, limit = 200) {
  const params = new URLSearchParams({ limit: String(limit) });
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== false) params.set(k, String(v));
  });
  return get<{ total: number; items: ListingSummary[] }>(`/api/listings?${params}`);
}

export const getListing = (id: string) => get<ListingDetail>(`/api/listings/${id}`);
export const patchListing = (id: string, body: { offer_due_at?: string }) =>
  send(`/api/listings/${id}`, "PATCH", body);
export const patchProperty = (id: string, body: { condition_tag?: string; condition_notes?: string }) =>
  send(`/api/properties/${id}`, "PATCH", body);

export interface PriceHistoryEntry {
  date: string;
  event: string; // Sold | Listed | Price Changed | ...
  price: number | null;
}

/** Stage vocabulary of PATCH /api/tracker/:id — anything else 422s (docs/07 §Tracker). */
export const TRACKER_STAGES = ["saved", "toured", "disclosures", "offer_prep", "offered",
  "won", "closing", "lost", "passed"];

export const getTracked = () => get<TrackedItem[]>("/api/tracker");
export const track = (listing_id: string) =>
  send<{ id: string }>("/api/tracker", "POST", { listing_id });
export const patchTracked = (id: string, body: Partial<Pick<TrackedItem, "stage" | "notes" | "my_max_bid">> & { disclosure_checklist?: Record<string, unknown> }) =>
  send(`/api/tracker/${id}`, "PATCH", body);
export const untrack = (id: string) => send(`/api/tracker/${id}`, "DELETE");

/** One Watchlist home (docs/07 §Watchlist): its current listing episode plus
 * what the buyer did with it and how it turned out. */
export interface WatchedItem extends ListingSummary {
  /** "listing" = the scan saw it close; "public_record" = Realtor history, after it left the market */
  sold_source: "listing" | "public_record" | null;
  /** sold price / original ask (1.04 = 4% over); null until sold */
  sp_lp: number | null;
  /** sold price − your max bid; positive = it went for more than you'd have paid */
  vs_max_bid: number | null;
  involvement: {
    tracked_id: string | null;
    stage: string | null;
    my_max_bid: number | null;
    tour_count: number;
    last_toured_on: string | null;
    verdict: string | null;
    gut_score: number | null;
  };
  last_change: ListingEvent | null;
  watched_at: string;
}

export const getWatchlist = () =>
  get<{ last_seen_at: string | null; items: WatchedItem[] }>("/api/watchlist");
export const markWatchlistSeen = () =>
  send<{ previous: string | null; at: string }>("/api/watchlist/seen", "POST");
/** Put a home on the Watchlist (true) or remove it (false) — docs/07 §Watchlist. */
export const setWatching = (propertyId: string, watching: boolean) =>
  send<{ property_id: string; watching: boolean }>(`/api/watchlist/${propertyId}`, "PATCH", { watching });

export const getAlerts = (limit = 100, undeliveredOnly = false) =>
  get<AlertItem[]>(`/api/alerts?limit=${limit}${undeliveredOnly ? "&undelivered_only=true" : ""}`);
export const ackAlert = (id: string) => send(`/api/alerts/${id}/ack`, "POST");
export const getAlertRules = () => get<Record<string, Record<string, unknown>>>("/api/alerts/rules");
export const putAlertRules = (rules: Record<string, Record<string, unknown>>) =>
  send<Record<string, Record<string, unknown>>>("/api/alerts/rules", "PUT", rules);

export const getCompare = (ids: string[]) =>
  get<CompareItem[]>(`/api/compare?listing_ids=${ids.join(",")}`);

export const solveOffer = (body: {
  listing_id?: string;
  city?: string;
  overrides?: Partial<Profile> & { hoa_monthly?: number };
}) => send<OfferSolution>("/api/offer/solve", "POST", body);

export const getProfile = () => get<Profile>("/api/profile");
export const putProfile = (p: Profile) => send<Profile>("/api/profile", "PUT", p);
export const calcAffordability = (body: {
  price: number;
  city?: string;
  down_payment?: number; // dollars
  rate?: number;
  hoa_monthly?: number;
  include_earthquake_ins?: boolean;
}) => send<CalcResult>("/api/affordability/calc", "POST", body);

export const getMarketSummary = () => get<MarketSummary>("/api/market/summary");

export const getSeries = (
  geoType: string,
  geoId: string,
  metric: string,
  since?: string,
  period?: string,
) =>
  get<SeriesPoint[]>(
    `/api/market/series?geo_type=${geoType}&geo_id=${encodeURIComponent(geoId)}` +
      `&metric=${metric}${since ? `&since=${since}` : ""}${period ? `&period=${period}` : ""}`,
  );

export const getRates = (series = "MORTGAGE30US", since?: string) =>
  get<RatePoint[]>(`/api/market/rates?series=${series}${since ? `&since=${since}` : ""}`);

export type SupplyBand = "very_tight" | "tight" | "balancing" | "soft" | "unknown";

export interface SupplyGeo {
  geo_id: string;
  city: string | null;
  months_supply: number | null;
  months_supply_basis: string | null;
  months_supply_live: number | null;
  months_supply_live_basis: string | null;
  delta_90d: number | null;
  pct_rank_3y: number | null;
  band: SupplyBand;
}

// Trailing windows the live now-cast is stored for; `period` on the series is `${n}m`.
export const LIVE_WINDOWS = [3, 6, 9, 12] as const;
export type LiveWindow = (typeof LIVE_WINDOWS)[number];

export interface SupplyResponse {
  as_of: {
    redfin_window_start: string | null;
    redfin_window_end: string | null;
    live: string | null;
    live_window_months: number;
  };
  zips: SupplyGeo[];
  cities: SupplyGeo[];
}

export const getSupply = (window: LiveWindow) =>
  get<SupplyResponse>(`/api/market/supply?window=${window}`);

// --- CMA / overbid / enrich -----------------------------------------

export interface CmaAdjustments {
  time: number;
  sqft: number;
  baths: number;
  lot: number;
  condition: number;
}

export interface CmaComp {
  sale_id: string;
  address: string;
  sale_date: string;
  sale_price: number;
  distance_mi: number | null;
  lat: number | null;
  lon: number | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  condition_tag: string | null;
  similarity_score: number;
  auto_selected: boolean;
  included: boolean;
  time_adj_factor: number | null;
  adjustments: CmaAdjustments;
  adjusted_price: number;
}

export interface CmaSubject {
  property_id: string;
  address: string;
  lat: number | null;
  lon: number | null;
  sqft: number | null;
  beds: number | null;
  baths: number | null;
}

export interface CmaRun {
  id: string;
  property_id: string;
  subject: CmaSubject | null;
  estimate: number | null;
  low: number | null;
  high: number | null;
  confidence: string;
  confidence_reasons: string[];
  index_source: string | null;
  as_of: string;
  comps: CmaComp[];
}

export interface CmaRunSummary {
  id: string;
  created_at: string;
  estimate: number | null;
  low: number | null;
  high: number | null;
  confidence: string;
  index_source: string | null;
  n_comps: number;
}

export interface OverbidComp {
  address: string;
  sale_date: string;
  sp_lp: number;
  original_list_price: number | null;
  sale_price: number;
}

export interface OverbidResult {
  list_price: number | null;
  basis: "fresh" | "stale";
  basis_reason: string;
  n_comps: number;
  n_eff: number;
  window_days: number;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  predicted: { low: number; point: number; high: number } | null;
  atypical_pricing: boolean;
  histogram: { bucket_low: number; bucket_high: number; weight: number }[];
  comps: OverbidComp[];
}

export interface AvmSnapshotOut {
  source: string;
  value: number;
  low: number | null;
  high: number | null;
  as_of: string;
}

export interface EnrichResult {
  avm_snapshots: AvmSnapshotOut[];
  rentcast_quota_remaining: number | null;
}

export const runCma = (property_id: string, params?: Record<string, unknown>) =>
  send<CmaRun>("/api/cma/run", "POST", { property_id, params });
export const getCmaRun = (runId: string) => get<CmaRun>(`/api/cma/runs/${runId}`);
export const getCmaRuns = (property_id: string) =>
  get<CmaRunSummary[]>(`/api/cma/runs?property_id=${property_id}`);
export const patchCmaComp = (runId: string, sale_id: string, included: boolean) =>
  send<CmaRun>(`/api/cma/runs/${runId}/comps`, "PATCH", { sale_id, included });
export const patchCmaAdjustments = (
  runId: string,
  sale_id: string,
  overrides: Record<string, number>,
) => send<CmaRun>(`/api/cma/runs/${runId}/adjustments`, "PATCH", { sale_id, overrides });

export const getOverbid = (listing_id: string) =>
  get<OverbidResult>(`/api/overbid/${listing_id}`);
export const enrichProperty = (property_id: string) =>
  send<EnrichResult>(`/api/properties/${property_id}/enrich`, "POST");

// --- Tours (docs/07 §Tours, docs/13 tour playbook) ---

export interface TourItem {
  key: string;
  label: string;
  type: "bool" | "number" | "text" | "choice" | "rating";
  choices: string[];
  hint: string;
  /** the exact shot to take — the shot-list is what feeds the AI deep dive */
  photo: string;
  flag_when: Record<string, unknown>;
  cost: string;
  cost_band: { key: string; label: string; low: number; high: number } | null;
}

export interface TourSection {
  key: string;
  title: string;
  blurb: string;
  items: TourItem[];
}

export interface TourChecklist {
  property_id: string;
  facts: Record<string, unknown>;
  sections: TourSection[];
  agent_questions: string[];
  /** what this specific home's age/flags mean for what to look at */
  context_notes: string[];
  /** where the cost bands come from — printed next to any total */
  costs: CostBookInfo;
  photo_shot_list: { key: string; label: string; shot: string }[];
}

export interface TourFlag {
  key: string;
  label: string;
  value: unknown;
  section: string;
  cost: string | null;
}

export interface TourCosts extends CostBookInfo {
  low: number;
  high: number;
  items: { key: string; label: string; low: number; high: number }[];
  overridden: boolean;
}

export interface Tour {
  id: string;
  property_id: string;
  listing_id: string | null;
  toured_on: string;
  kind: string;
  checklist: Record<string, unknown>;
  agent_answers: Record<string, string>;
  gut_score: number | null;
  verdict: string | null;
  notes: string | null;
  repair_low: number | null;
  repair_high: number | null;
  source: string;
  flags: TourFlag[];
  costs: TourCosts;
  unanswered: { key: string; label: string; section: string }[];
}

export interface TourImportResult {
  created: number;
  updated: number;
  unchanged: number;
  /** values the import declined to overwrite — a stale backup never reverts an edit */
  conflicts: { property_id: string; toured_on: string; field: string; existing: unknown; incoming: unknown }[];
  errors: { property_id: string | null; toured_on: string; error: string }[];
}

/** Field seed (GET /api/tours/field-data) — everything the Field page needs about
 * one home, loaded once for the day's set (docs/08 §11). */
export interface FieldHome {
  listing_id: string;
  property_id: string;
  address: string;
  city: string | null;
  zip: string;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  lot_sqft: number | null;
  year_built: number | null;
  list_price: number | null;
  original_list_price: number | null;
  posture: Posture | null;
  cumulative_dom: number | null;
  price_cuts: number;
  offer_due_at: string | null;
  cma_estimate: number | null;
  predicted_low: number | null;
  predicted_point: number | null;
  predicted_high: number | null;
  facts: Record<string, unknown>;
  /** the age-pruned checklist, carrying flag_when so flags raise with no server */
  spec: {
    sections: TourSection[];
    agent_questions: string[];
    context_notes: string[];
    costs: CostBookInfo;
    photo_shot_list: { key: string; label: string; shot: string }[];
  };
  existing: Tour | null;
}

// ---- Open houses (docs/07 §Open houses)

export interface Origin {
  address: string;
  lat: number;
  lon: number;
}

export interface OpenHouse {
  id: string;
  listing_id: string;
  source: string;
  start_at: string;
  end_at: string;
  description: string | null;
  href: string | null;
  methods: string[];
  /** on the buyer's open-house schedule */
  scheduled: boolean;
  /** upstream stopped listing this scheduled slot (only ever true on the schedule) */
  cancelled: boolean;
  /** straight-line miles from the origin; null when either side has no coordinates */
  distance_mi: number | null;
  listing: ListingSummary;
}

export interface OpenHouseList {
  origin: Origin | null;
  from: string;
  to: string;
  /** IANA zone the market lives in — render every time in it */
  timezone: string;
  items: OpenHouse[];
}

export interface OpenHouseFilters {
  from?: string;
  to?: string;
  max_miles?: number;
  city?: string;
  min_price?: number | null;
  max_price?: number | null;
  sort?: "time" | "distance" | "price";
}

export interface RouteStop {
  open_house_id: string;
  listing_id: string;
  address: string;
  start_at: string;
  end_at: string;
  /** drive in from the previous stop (or home); null = no map location */
  drive_min: number | null;
  drive_miles: number | null;
}

/** a day's stops in visiting order — every stop kept, no visit times */
export interface RoutePlan {
  origin: Origin;
  total_drive_min: number;
  maps_url: string | null;
  /** how many stops the Google Maps link covers (it takes at most 10) */
  maps_stops: number;
  stops: RouteStop[];
}

export function getOpenHouses(filters: OpenHouseFilters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  return get<OpenHouseList>(`/api/open-houses?${params}`);
}
export const getOrigin = () => get<{ origin: Origin | null }>("/api/open-houses/origin");
export const putOrigin = (address: string) =>
  send<{ origin: Origin }>("/api/open-houses/origin", "PUT", { address });
export const getSchedule = () =>
  get<{ origin: Origin | null; timezone: string; items: OpenHouse[] }>("/api/open-houses/schedule");
export const scheduleOpenHouse = (id: string) =>
  send<{ id: string; scheduled: boolean }>(`/api/open-houses/${id}/schedule`, "PUT");
export const unscheduleOpenHouse = (id: string) =>
  send<{ id: string; scheduled: boolean }>(`/api/open-houses/${id}/schedule`, "DELETE");
export const planRoute = (body: {
  open_house_ids: string[];
  /** answer in the planner's suggested order instead of the given one */
  optimize?: boolean;
  start_at?: string;
  dwell_min?: number;
}) => send<RoutePlan>("/api/open-houses/route", "POST", body);
export const reorderSchedule = (open_house_ids: string[]) =>
  send<{ open_house_ids: string[] }>("/api/open-houses/schedule/order", "PUT", { open_house_ids });

export interface FieldData {
  generated_at: string;
  homes: FieldHome[];
}

export const getTourChecklist = (listing_id: string) =>
  get<TourChecklist>(`/api/tours/checklist?listing_id=${listing_id}`);
export const getTours = (listing_id: string) =>
  get<Tour[]>(`/api/tours?listing_id=${listing_id}`);
export const createTour = (body: { listing_id: string; toured_on?: string; kind?: string }) =>
  send<Tour>("/api/tours", "POST", body);
export const patchTour = (
  id: string,
  body: {
    kind?: string;
    checklist?: Record<string, unknown>;
    agent_answers?: Record<string, string>;
    gut_score?: number;
    verdict?: string;
    notes?: string;
    repair_low?: number;
    repair_high?: number;
  },
) => send<Tour>(`/api/tours/${id}`, "PATCH", body);
export const deleteTour = (id: string) => send(`/api/tours/${id}`, "DELETE");
/** JSON-only: the Field page's "Copy answers" recovery path (docs/08 §11). */
export const importTours = (payload: { tours: unknown[] }) =>
  send<TourImportResult>("/api/tours/import", "POST", payload);

/** Seed the Field page with the day's homes. */
export const getFieldData = (listing_ids: string[]) =>
  get<FieldData>(`/api/tours/field-data?listing_ids=${listing_ids.join(",")}`);

export async function getListingBrief(listing_id: string): Promise<string> {
  const resp = await fetch(`/api/listings/${listing_id}/brief`);
  if (!resp.ok) throw new Error(`brief -> ${resp.status}`);
  return resp.text();
}

// --- Deals / closing tracker (docs/07 §Deals, docs/14) ---

export interface ClosingTask {
  key: string;
  label: string;
  phase: string;
  owner: string;
  why: string;
  how: string;
  form: string;
  /** Plain-English name for `form` — a badge reading "BNA" means nothing on its own. */
  form_name: string;
  form_what: string;
  blocking: boolean;
  anchor: string;
  offset: number;
  due_on: string;
  due_overridden: boolean;
  cost: string;
  cost_band: { key: string; label: string; low: number; high: number } | null;
  done_on: string | null;
  done: boolean;
  waived: boolean;
  note: string | null;
}

export interface ClosingPhase {
  key: string;
  title: string;
  blurb: string;
  tasks: ClosingTask[];
}

export interface DealRollup {
  anchors: Record<string, string | null>;
  /** Anchor names whose contingency was waived (NULL day-count). */
  waived: string[];
  total: number;
  done: number;
  overdue: ClosingTask[];
  due_soon: ClosingTask[];
  blocking_open: ClosingTask[];
  next_action: ClosingTask | null;
  phases: { key: string; title: string; total: number; done: number }[];
  days_to_close: number | null;
  costs: CostBookInfo & {
    low: number;
    high: number;
    items: { key: string; label: string; low: number; high: number }[];
  };
}

/** Kind vocabulary of the contacts routes — anything else 422s (docs/07 §Listings). */
export const CONTACT_KINDS = [
  "escrow", "title", "lender", "inspector", "insurance", "attorney", "tc",
  "listing_agent", "owner", "contractor", "other",
];

/** One `contacts` row: on a deal's team (deal_id), saved on a listing (listing_id), or both null. */
export interface Contact {
  id: string;
  kind: string;
  name: string;
  company: string | null;
  role: string | null;
  phone: string | null;
  email: string | null;
  notes: string | null;
  deal_id: string | null;
  listing_id: string | null;
}

export type ContactBody = {
  kind: string;
  name: string;
  company?: string;
  role?: string;
  phone?: string;
  email?: string;
  notes?: string;
};

export interface Deal {
  id: string;
  listing_id: string;
  property_id: string;
  accepted_on: string;
  purchase_price: number | null;
  emd_amount: number | null;
  emd_sent_on: string | null;
  emd_business_days: number | null;
  close_of_escrow_on: string | null;
  investigation_days: number | null;
  appraisal_days: number | null;
  loan_days: number | null;
  financed: boolean;
  loan_type: string | null;
  escrow_company: string | null;
  escrow_number: string | null;
  status: string;
  notes: string | null;
  checklist: Record<string, Record<string, unknown>>;
  address?: string;
  city?: string | null;
  zip?: string | null;
  year_built?: number | null;
  rollup: DealRollup;
  spec?: ClosingSpec;
  /** The deal team, plus the contacts saved on the deal's listing before the offer. */
  contacts?: Contact[];
}

/** The task list pruned to one deal (or the no-deal preview), grouped by phase. */
export interface ClosingSpec {
  phases: ClosingPhase[];
  anchors: Record<string, string | null>;
  /** the pack's default day-counts — what "restore" puts back, and the hint under the fields */
  contingency: ContingencyDefaults;
}

export const getDeals = () => get<Deal[]>("/api/deals");
export const getDeal = (id: string) => get<Deal>(`/api/deals/${id}`);
export const createDeal = (body: {
  listing_id: string;
  accepted_on?: string;
  purchase_price?: number;
  close_of_escrow_on?: string;
}) => send<Deal>("/api/deals", "POST", body);
export const patchDeal = (
  id: string,
  body: {
    accepted_on?: string;
    purchase_price?: number | null;
    emd_amount?: number | null;
    emd_sent_on?: string;
    close_of_escrow_on?: string;
    investigation_days?: number;
    appraisal_days?: number;
    loan_days?: number;
    financed?: boolean;
    escrow_company?: string;
    escrow_number?: string;
    status?: string;
    notes?: string;
    checklist?: Record<string, Record<string, unknown> | null>;
    /** Clear a contingency day-count — PATCH can't express NULL any other way. */
    waive?: string[];
  },
) => send<Deal>(`/api/deals/${id}`, "PATCH", body);
export const deleteDeal = (id: string) => send(`/api/deals/${id}`, "DELETE");

/** Preview the task list before an offer is accepted — no deal row needed. */
export const getClosingSpec = (listing_id?: string) =>
  get<ClosingSpec>(`/api/deals/spec${listing_id ? `?listing_id=${listing_id}` : ""}`);

export const addDealContact = (deal_id: string, body: ContactBody) =>
  send<Contact>(`/api/deals/${deal_id}/contacts`, "POST", body);
export const deleteDealContact = (deal_id: string, id: string) =>
  send(`/api/deals/${deal_id}/contacts/${id}`, "DELETE");

// --- Contacts saved on a listing (docs/07 §Listings, docs/08 §3 1c) ---

export const addListingContact = (listing_id: string, body: ContactBody) =>
  send<Contact>(`/api/listings/${listing_id}/contacts`, "POST", body);
export const patchListingContact = (listing_id: string, id: string, body: Partial<ContactBody>) =>
  send<Contact>(`/api/listings/${listing_id}/contacts/${id}`, "PATCH", body);
export const deleteListingContact = (listing_id: string, id: string) =>
  send(`/api/listings/${listing_id}/contacts/${id}`, "DELETE");

// --- Prep checklist (docs/07 §Prep, docs/15) ---

export interface PrepTask {
  key: string;
  label: string;
  phase: string;
  owner: string;
  why: string;
  how: string;
  needed_by: string;
  /** Calendar time this takes regardless of effort — why it should be started first. */
  lead_time: string;
  done_on: string | null;
  done: boolean;
  note: string | null;
}

export interface PrepPhase {
  key: string;
  title: string;
  blurb: string;
  tasks: PrepTask[];
}

export interface Prep {
  phases: PrepPhase[];
  rollup: {
    total: number;
    done: number;
    long_lead_open: PrepTask[];
    before_tour_open: PrepTask[];
    before_offer_open: PrepTask[];
    next_action: PrepTask | null;
    phases: { key: string; title: string; total: number; done: number }[];
  };
}

export const getPrep = () => get<Prep>("/api/prep");
export const patchPrep = (checklist: Record<string, Record<string, unknown> | null>) =>
  send<Prep>("/api/prep", "PATCH", { checklist });

// --- Config (docs/07 §Config) — the configured geography and the state pack ---
//
// Everything the UI knows about *where* it is running and *which state's rules*
// apply comes from here: city list, map centre, assessor links, contingency
// defaults, hazard and school-rating labels, the tracker checklist. Static for
// the life of the server (fetched once, lib/config.ts).

/** Default contingency clocks for a new deal, calendar days after acceptance
 * (the deposit in business days). A deal's own negotiated numbers govern once it exists. */
export interface ContingencyDefaults {
  investigation_days: number;
  appraisal_days: number;
  loan_days: number;
  emd_business_days: number;
  /** names the contract the defaults come from, shown next to the numbers */
  label: string;
}

/** Where a set of cost bands comes from, printed next to any total ("2026 …"). */
export interface CostBookInfo {
  year: number;
  label: string;
}

/** Chip colour of a hazard layer; the class names live in HazardChips.tsx. */
export type HazardTone = "sky" | "orange" | "amber" | "purple" | "rose" | "slate";

export interface AppConfig {
  geography: {
    name: string;
    state: string;
    /** IANA zone the market lives in */
    timezone: string;
    cities: { name: string; county: string; zips: string[]; flags: string[] }[];
    zips: string[];
    counties: {
      name: string;
      assessor_label: string | null;
      /** free owner-of-record lookup; null when the county publishes none */
      assessor_url: string | null;
      effective_tax_rate: number | null;
    }[];
    map: { center: [number, number]; zoom: number };
    price_band: TargetBand;
  };
  pack: {
    key: string;
    label: string;
    contingency: ContingencyDefaults;
    costs: CostBookInfo;
    hazards: { key: string; label: string; tone: HazardTone }[];
    rating_sources: { key: string; label: string; blurb: string }[];
    /** Tracker's per-listing disclosure checklist; keys are the storage contract */
    tracker_checklist: { key: string; label: string; kind: "bool" | "number" | "text" }[];
    affordability: {
      earthquake_monthly_default: number;
      optional_insurance_label: string;
    };
    /** who to hire for contract review, in words that complete "… on a flat fee" */
    attorney_phrase: string;
    guide: { available: boolean };
  };
}

export const getConfig = () => get<AppConfig>("/api/config");

// --- Closing guide (docs/07 §Guide) — the pack's playbook, split into sections ---

export interface GuideSection {
  id: string;
  n: number;
  title: string;
  /** the section body, GFM — tables and nested quotes included */
  markdown: string;
}

export interface GuideLink {
  id: string;
  label: string;
}

export interface ClosingGuide {
  pack: string;
  pack_label: string;
  doc: string;
  title: string;
  intro_md: string;
  sections: GuideSection[];
  /** closing phase key -> the guide sections that explain it */
  phase_map: Record<string, GuideLink[]>;
}

/** null when the configured pack ships no closing guide (the server answers 404). */
export async function getClosingGuide(): Promise<ClosingGuide | null> {
  const resp = await fetch("/api/guide/closing");
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`/api/guide/closing -> ${resp.status}`);
  return resp.json() as Promise<ClosingGuide>;
}

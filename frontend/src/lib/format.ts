export function money(v: number | null | undefined, compact = true): string {
  if (v == null) return "—";
  // 999,500+ rounds to "$1000k", so it switches to millions there, not at 1,000,000
  if (compact && Math.abs(v) >= 999_500) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (compact && Math.abs(v) >= 1_000) return `$${Math.round(v / 1_000)}k`;
  return `$${Math.round(v).toLocaleString()}`;
}

/** A dollar change with its sign spelled out: "+$15k", "−$149k", "$0". */
export function signedMoney(v: number, compact = true): string {
  if (v === 0) return "$0";
  return `${v > 0 ? "+" : "−"}${money(Math.abs(v), compact)}`;
}

/** A sale-to-asking ratio in words: 1.12 -> "12% over asking", 0.973 -> "2.7% under
 *  asking", within half a percent either way -> "right at asking". */
export function vsAsking(ratio: number): string {
  const d = (ratio - 1) * 100;
  if (Math.abs(d) < 0.5) return "right at asking";
  const n = Math.abs(d) >= 10 ? Math.abs(d).toFixed(0) : Math.abs(d).toFixed(1).replace(/\.0$/, "");
  return `${n}% ${d > 0 ? "over" : "under"} asking`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/** Sold-vs-ask ratio (sold / original list − 1); null when either side is missing. */
export function deltaVsAsk(sold: number | null, ask: number | null): number | null {
  return sold && ask ? sold / ask - 1 : null;
}

/** Ten bare digits -> 650-555-0123; anything else passes through untouched. */
export function phone(digits: string): string {
  return /^\d{10}$/.test(digits)
    ? `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`
    : digits;
}

export function num(v: number | null | undefined, digits = 0): string {
  if (v == null) return "—";
  return v.toFixed(digits);
}

/** Format a metric value by metric name. */
export function metricValue(metric: string, v: number | null | undefined): string {
  if (v == null) return "—";
  if (metric.includes("price") && !metric.includes("drops")) return money(v);
  if (metric === "median_ppsf") return `$${Math.round(v)}`;
  if (metric === "avg_sp_lp") return pct(v, 1); // ratio 1.11 -> "111.0%"
  if (metric.startsWith("pct_")) return pct(v);
  return num(v, metric.startsWith("months_supply") ? 1 : 0);
}

export const METRIC_LABELS: Record<string, string> = {
  median_sale_price: "Median sale",
  median_ppsf: "$/sqft",
  avg_sp_lp: "Sale-to-list",
  median_dom: "Days on mkt",
  inventory: "Inventory",
  months_supply: "Months supply",
  months_supply_live: "Months supply (live)",
};

// ---- open-house times (docs/08 §14). ISO instants rendered as wall-clock in
// `timeZone` (the market's zone from the API; the device zone when omitted).

function clockParts(iso: string, timeZone?: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    hour: "numeric", minute: "2-digit", hour12: true, weekday: "short", timeZone,
  }).formatToParts(new Date(iso));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return { weekday: get("weekday"), hour: get("hour"), minute: get("minute"),
           ampm: get("dayPeriod").toUpperCase() };
}

/** "1:20 PM" */
export function clock(iso: string, timeZone?: string): string {
  const p = clockParts(iso, timeZone);
  return `${p.hour}${p.minute === "00" ? "" : `:${p.minute}`} ${p.ampm}`;
}

/** "Sat 1 PM" — a slot's start, compact enough for a map pin */
export function weekdayClock(iso: string, timeZone?: string): string {
  return `${clockParts(iso, timeZone).weekday} ${clock(iso, timeZone)}`;
}

/** "Sat 1–4 PM", "Sun 11 AM–2 PM", "Wed 4:30–7 PM" */
export function openHouseWindow(start: string, end: string, timeZone?: string): string {
  const a = clockParts(start, timeZone);
  const b = clockParts(end, timeZone);
  const t = (p: typeof a) => `${p.hour}${p.minute === "00" ? "" : `:${p.minute}`}`;
  return a.ampm === b.ampm
    ? `${a.weekday} ${t(a)}–${t(b)} ${b.ampm}`
    : `${a.weekday} ${t(a)} ${a.ampm}–${t(b)} ${b.ampm}`;
}

/** Calendar date key "2026-10-17" of an instant in `timeZone` — for grouping by day. */
export function dayKey(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit",
                                            day: "2-digit" }).format(new Date(iso));
}

/** A day's heading pieces: { weekday: "Saturday", short: "Sat", date: "Oct 17",
 *  relative: "Today" | "Tomorrow" | "Yesterday" | null } */
export function dayParts(iso: string, timeZone?: string) {
  const fmt = (o: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat("en-US", { timeZone, ...o }).format(new Date(iso));
  const key = dayKey(iso, timeZone);
  const today = dayKey(new Date().toISOString(), timeZone);
  const tomorrow = dayKey(new Date(Date.now() + 86_400_000).toISOString(), timeZone);
  const yesterday = dayKey(new Date(Date.now() - 86_400_000).toISOString(), timeZone);
  return {
    weekday: fmt({ weekday: "long" }),
    short: fmt({ weekday: "short" }),
    date: fmt({ month: "short", day: "numeric" }),
    relative: key === today ? "Today" : key === tomorrow ? "Tomorrow"
      : key === yesterday ? "Yesterday" : null,
  };
}

export type DayGroup<T> = { key: string; iso: string; items: T[] };

/** Rows under their calendar day in `timeZone`. Days run chronologically
 *  (`asc`) or newest first (`desc`); inside a day the rows keep the order they
 *  came in, so a distance or price sort survives the grouping. */
export function groupByDay<T>(
  items: T[], iso: (item: T) => string, timeZone: string | undefined, order: "asc" | "desc",
): DayGroup<T>[] {
  const out: DayGroup<T>[] = [];
  const keyed = items.map((item) => ({ item, key: dayKey(iso(item), timeZone) }));
  keyed.sort((a, b) => (order === "asc" ? 1 : -1) * a.key.localeCompare(b.key));
  for (const { item, key } of keyed) {
    if (out.at(-1)?.key !== key) out.push({ key, iso: iso(item), items: [] });
    out.at(-1)!.items.push(item);
  }
  return out;
}

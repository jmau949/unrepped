import { useQueries, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getSeries,
  getSupply,
  LIVE_WINDOWS,
  type LiveWindow,
  type SupplyGeo,
} from "../api/client";
import { MAX_SERIES, SERIES_COLORS } from "../lib/chartColors";
import { num, pct } from "../lib/format";

const LIVE_METRIC = "months_supply_live";
const DEFAULT_WINDOW: LiveWindow = 3;

// Red = hardest for a buyer. The bands are calibrated to the target market, not
// the national 3/6-month convention — see docs/06 §9.
const BAND: Record<string, { label: string; className: string }> = {
  very_tight: { label: "Very tight", className: "bg-red-100 text-red-700" },
  tight: { label: "Tight", className: "bg-amber-100 text-amber-700" },
  balancing: { label: "Balancing", className: "bg-emerald-100 text-emerald-700" },
  soft: { label: "Soft", className: "bg-sky-100 text-sky-700" },
  unknown: { label: "—", className: "bg-slate-100 text-slate-500" },
};

/** "12345 · Springfield" for a ZIP; a city row is already named by its geo_id. */
function geoLabel(g: SupplyGeo): string {
  return g.city ? `${g.geo_id} · ${g.city}` : g.geo_id;
}

function BandChip({ band }: { band: string }) {
  const { label, className } = BAND[band] ?? BAND.unknown;
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{label}</span>
  );
}

function CityChip() {
  return (
    <span
      title="Too few sales in this ZIP — showing the parent city's figure"
      className="ml-1 rounded bg-slate-100 px-1 py-0.5 align-middle text-[10px] font-medium text-slate-500"
    >
      city
    </span>
  );
}

function Delta({ value }: { value: number | null }) {
  if (value == null) return <span className="text-slate-400">—</span>;
  // rising supply = more choice = better for a buyer
  return (
    <span className={value > 0 ? "text-emerald-600" : "text-red-600"}>
      {value > 0 ? "▲" : "▼"} {pct(value)}
    </span>
  );
}

/** One control for the whole page: the trailing window behind every live figure. */
function WindowPicker({
  value,
  onChange,
}: {
  value: LiveWindow;
  onChange: (w: LiveWindow) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <div>
        <div className="text-sm font-semibold text-slate-700">Live window</div>
        <div className="text-xs text-slate-500">closed sales counted behind every live figure</div>
      </div>
      <div
        role="radiogroup"
        aria-label="Live window in months"
        className="inline-flex overflow-hidden rounded-md border border-slate-300 text-sm"
      >
        {LIVE_WINDOWS.map((w) => (
          <button
            key={w}
            role="radio"
            aria-checked={w === value}
            onClick={() => onChange(w)}
            className={`px-3 py-1.5 font-medium first:rounded-l-md last:rounded-r-md ${
              w === value
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 hover:bg-slate-100"
            } border-l border-slate-300 first:border-l-0`}
          >
            {w} months
          </button>
        ))}
      </div>
    </div>
  );
}

const COLUMNS: { key: keyof SupplyGeo | "geo_id"; label: string }[] = [
  { key: "geo_id", label: "ZIP" },
  { key: "city", label: "City" },
  { key: LIVE_METRIC, label: "Live" },
  { key: "months_supply", label: "Redfin" },
  { key: "delta_90d", label: "90d" },
  { key: "pct_rank_3y", label: "vs own 3y" },
  { key: "band", label: "Band" },
];

function SupplyRows({
  rows,
  linkable,
  window,
}: {
  rows: SupplyGeo[];
  linkable: boolean;
  window: LiveWindow;
}) {
  const [sortBy, setSortBy] = useState<string>(LIVE_METRIC);
  const [desc, setDesc] = useState(true);
  const navigate = useNavigate();

  // city rows are already named by geo_id — the parent-city column is redundant
  const columns = linkable ? COLUMNS : COLUMNS.filter((c) => c.key !== "city");

  const sorted = [...rows].sort((a, b) => {
    const av = a[sortBy as keyof SupplyGeo];
    const bv = b[sortBy as keyof SupplyGeo];
    if (typeof av === "string" || typeof bv === "string")
      return desc
        ? String(bv ?? "").localeCompare(String(av ?? ""))
        : String(av ?? "").localeCompare(String(bv ?? ""));
    const an = av ?? -Infinity;
    const bn = bv ?? -Infinity;
    return desc ? Number(bn) - Number(an) : Number(an) - Number(bn);
  });

  const label = (c: (typeof COLUMNS)[number]) => {
    if (c.key === "geo_id" && !linkable) return "City";
    if (c.key === LIVE_METRIC) return `Live (${window} mo)`;
    return c.label;
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-3">
      <table className="min-w-[44rem] text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            {columns.map((c) => (
              <th
                key={c.key}
                onClick={() => {
                  if (sortBy === c.key) setDesc(!desc);
                  else {
                    setSortBy(c.key);
                    setDesc(true);
                  }
                }}
                className="cursor-pointer select-none whitespace-nowrap py-2 pr-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-900"
              >
                {label(c)} {sortBy === c.key ? (desc ? "↓" : "↑") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.geo_id}
              className={`border-b border-slate-100 ${
                linkable ? "cursor-pointer hover:bg-slate-50" : ""
              }`}
              onClick={
                linkable
                  ? () => navigate({ to: "/listings", search: { zip: r.geo_id } as never })
                  : undefined
              }
            >
              <td className="py-2 pr-4 font-medium">{r.geo_id}</td>
              {linkable && <td className="py-2 pr-4 text-slate-500">{r.city ?? ""}</td>}
              <td className="whitespace-nowrap py-2 pr-4">
                {num(r.months_supply_live, 1)}
                {r.months_supply_live_basis === "derived_city" && <CityChip />}
              </td>
              <td className="whitespace-nowrap py-2 pr-4">
                {num(r.months_supply, 1)}
                {r.months_supply_basis === "derived_city" && <CityChip />}
              </td>
              <td className="whitespace-nowrap py-2 pr-4 text-xs">
                <Delta value={r.delta_90d} />
              </td>
              <td className="whitespace-nowrap py-2 pr-4 text-slate-500">
                {r.pct_rank_3y == null ? "—" : pct(r.pct_rank_3y, 0)}
              </td>
              <td className="py-2 pr-4">
                <BandChip band={r.band} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SupplyTrend({
  geoType,
  geos,
  title,
  window,
}: {
  geoType: "zip" | "city";
  geos: SupplyGeo[];
  title: string;
  window: LiveWindow;
}) {
  const [metric, setMetric] = useState(LIVE_METRIC);
  // position === colour slot; null === a freed slot. Holding the slot is what
  // keeps a series the same colour when a *different* series is deselected.
  const [slots, setSlots] = useState<(string | null)[]>(() =>
    geos.slice(0, 2).map((g) => g.geo_id),
  );
  const active = slots.filter((s): s is string => s !== null);
  const since = new Date(Date.now() - 3 * 365 * 86_400_000).toISOString().slice(0, 10);
  // the live series is stored once per window; every other metric has one series
  const period = metric === LIVE_METRIC ? `${window}m` : undefined;
  const labels = new Map(geos.map((g) => [g.geo_id, geoLabel(g)]));

  const queries = useQueries({
    queries: active.map((geoId) => ({
      queryKey: ["series", geoType, geoId, metric, since, period],
      queryFn: () => getSeries(geoType, geoId, metric, since, period),
      staleTime: 60 * 60 * 1000,
    })),
  });

  const merged = new Map<string, Record<string, number | string>>();
  queries.forEach((q, i) => {
    (q.data ?? []).forEach((p) => {
      const row = merged.get(p.period_start) ?? { period_start: p.period_start };
      row[active[i]] = p.value;
      merged.set(p.period_start, row);
    });
  });
  const data = [...merged.values()].sort((a, b) =>
    String(a.period_start).localeCompare(String(b.period_start)),
  );
  // a line needs two points; a series this short is only visible as dots
  const showDots = data.length < 3;

  const toggle = (geoId: string) =>
    setSlots((cur) => {
      const at = cur.indexOf(geoId);
      if (at !== -1) {
        const next = [...cur];
        next[at] = null; // free this slot only — survivors keep their colours
        return next;
      }
      const free = cur.indexOf(null);
      if (free !== -1) {
        const next = [...cur];
        next[free] = geoId;
        return next;
      }
      return cur.length < MAX_SERIES ? [...cur, geoId] : cur;
    });

  const atCapacity = active.length >= MAX_SERIES;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value={LIVE_METRIC}>Months supply (live, {window} mo)</option>
          <option value="months_supply">Months supply (Redfin)</option>
          <option value="inventory">Inventory</option>
          <option value="homes_sold">Homes sold</option>
        </select>
        <div className="flex max-w-full flex-wrap gap-1">
          {geos.map((g) => {
            const slot = slots.indexOf(g.geo_id);
            const on = slot !== -1;
            return (
              <button
                key={g.geo_id}
                onClick={() => toggle(g.geo_id)}
                disabled={!on && atCapacity}
                title={!on && atCapacity ? `Deselect one first — ${MAX_SERIES} series max` : undefined}
                className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
                  on
                    ? "bg-slate-900 text-white"
                    : atCapacity
                      ? "cursor-not-allowed bg-slate-50 text-slate-300"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {/* a colour chip carries series identity; the label stays ink */}
                {on && (
                  <span
                    aria-hidden
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: SERIES_COLORS[slot] }}
                  />
                )}
                {geoLabel(g)}
              </button>
            );
          })}
        </div>
      </div>
      {metric === LIVE_METRIC && (
        <p className="mb-2 text-xs text-slate-400">
          Live history begins with this app's first scan — daily points, every window.
        </p>
      )}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="period_start" tick={{ fontSize: 11 }} minTickGap={50} />
            <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} width={44} />
            <Tooltip />
            <Legend />
            {slots.map((geoId, slot) =>
              geoId === null ? null : (
                <Line
                  key={geoId}
                  type="monotone"
                  dataKey={geoId}
                  name={labels.get(geoId) ?? geoId}
                  stroke={SERIES_COLORS[slot]}
                  strokeWidth={2}
                  dot={showDots}
                  connectNulls
                  isAnimationActive={false}
                />
              ),
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function definitions(window: LiveWindow): { term: string; body: React.ReactNode }[] {
  return [
    {
      term: `Months supply (live, ${window} mo)`,
      body: (
        <>
          Computed from this app's own daily scan: <strong>active listings right now ÷ the
          monthly closed-sale pace over the trailing {window} months</strong> (closed sales in
          the window ÷ {window}). No publication lag — current as of the last scan. The window
          picker at the top changes it everywhere on this page: 3 months reacts fastest to a
          turn in the market, 12 months smooths out seasonality. It counts only homes the
          scanner has seen, so expect it to differ from Redfin's figure.
        </>
      ),
    },
    {
      term: "Months supply (Redfin)",
      body: (
        <>
          Redfin's published measure: <strong>inventory ÷ the monthly closed-sale rate</strong> —
          at today's pace, how long until every listed home is gone. Lower means tighter. ZIP
          and city series are both <strong>rolling 3-month windows</strong> labelled by the
          window's <em>start</em>, so the newest point covers the three months ending about a
          month ago. This is the series with years of history, so <em>vs own 3y</em>, the 90-day
          delta and the band all describe it.
        </>
      ),
    },
    {
      term: "Inventory",
      body: (
        <>
          The <strong>numerator</strong>. Active listings counted on the <em>last day</em> of the
          window — a snapshot, not a running total, so it does not accumulate across a 3-month
          window. Rising inventory against flat sales is supply loosening.
        </>
      ),
    },
    {
      term: "Homes sold",
      body: (
        <>
          The <strong>denominator's</strong> raw input: closed sales in the window — a{" "}
          <strong>3-month total</strong> on ZIP and city rows (divide by three for a monthly
          pace). Falling sales against flat inventory pushes months supply up just as much as
          new listings do — so read the two together before concluding the market loosened.
        </>
      ),
    },
  ];
}

function MetricDefinitions({ window }: { window: LiveWindow }) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        What these metrics mean
      </h2>
      <dl className="max-w-4xl space-y-3 rounded-lg border border-slate-200 bg-white p-4 text-sm">
        {definitions(window).map((d) => (
          <div key={d.term}>
            <dt className="font-semibold text-slate-700">{d.term}</dt>
            <dd className="text-slate-500">{d.body}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
      {children}
    </h2>
  );
}

export default function Supply() {
  // the window lives in the URL (?window=6) so a view can be linked and survives a reload
  const search = useSearch({ strict: false }) as Record<string, unknown>;
  const window =
    LIVE_WINDOWS.find((w) => w === Number(search.window)) ?? DEFAULT_WINDOW;
  const navigate = useNavigate();
  const setWindow = (w: LiveWindow) =>
    navigate({ to: "/supply", search: { window: w } as never, replace: true });

  const supply = useQuery({
    queryKey: ["market-supply", window],
    queryFn: () => getSupply(window),
  });
  const [focusZip, setFocusZip] = useState<string | null>(null);

  const zips = supply.data?.zips ?? [];
  const cities = supply.data?.cities ?? [];
  const asOf = supply.data?.as_of;
  const focused = zips.find((z) => z.geo_id === focusZip) ?? zips[0];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Supply</h1>

      <p className="max-w-3xl text-sm text-slate-500">
        <strong className="text-slate-700">Months of supply</strong> is active inventory divided by
        the monthly closed-sale rate — how long it would take to clear every listed home at the
        current pace. Lower means less choice and more competition.{" "}
        <strong className="text-slate-700">Live</strong> is computed from this app's own daily
        scan over the trailing window picked below and is current as of the last run;{" "}
        <strong className="text-slate-700">Redfin</strong> is Redfin's published rolling
        3-month figure, which trails by about a month but carries years of history. Bands are
        calibrated to this market rather than the national 3/6-month convention — a market
        that sits entirely under the national "seller's market" line would otherwise read red
        everywhere, so <em>vs own 3y</em> (where a ZIP sits in its own three-year range) is
        usually the more useful column.
      </p>

      <div className="flex flex-wrap items-center gap-x-8 gap-y-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
        <WindowPicker value={window} onChange={setWindow} />
        {asOf && (
          <dl className="ml-auto grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs text-slate-500">
            <dt className="font-medium text-slate-600">Live as of</dt>
            <dd>{asOf.live ?? "—"}</dd>
            <dt className="font-medium text-slate-600">Redfin window</dt>
            <dd>
              {asOf.redfin_window_start ?? "—"} → {asOf.redfin_window_end ?? "—"}
            </dd>
          </dl>
        )}
      </div>

      {zips.length === 0 && !supply.isLoading && (
        <p className="text-sm text-slate-400">
          No supply data yet — run `hb pipeline market-supply` to fill this page.
        </p>
      )}

      {focused && (
        <section>
          <div className="mb-2 flex items-center gap-2">
            <SectionTitle>Focus ZIP</SectionTitle>
            <select
              value={focused.geo_id}
              onChange={(e) => setFocusZip(e.target.value)}
              className="mb-2 rounded border border-slate-300 px-2 py-1 text-sm"
            >
              {zips.map((z) => (
                <option key={z.geo_id} value={z.geo_id}>
                  {z.geo_id} — {z.city}
                </option>
              ))}
            </select>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3">
              <div>
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Live ({window} mo)
                </div>
                <div className="text-3xl font-bold">
                  {num(focused.months_supply_live, 1)}
                  {focused.months_supply_live_basis === "derived_city" && <CityChip />}
                </div>
              </div>
              <div>
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Redfin
                </div>
                <div className="text-3xl font-bold">
                  {num(focused.months_supply, 1)}
                  {focused.months_supply_basis === "derived_city" && <CityChip />}
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <BandChip band={focused.band} />
                <span className="text-xs text-slate-500">
                  90d: <Delta value={focused.delta_90d} />
                </span>
              </div>
            </div>
            <p className="mt-3 text-sm text-slate-500">
              {focused.pct_rank_3y == null
                ? "Not enough history in this ZIP to place it against its own range."
                : `Redfin supply here is higher than ${pct(focused.pct_rank_3y, 0)} of this ZIP's last three years — ` +
                  (focused.pct_rank_3y < 0.35
                    ? "tighter than usual, expect competition."
                    : focused.pct_rank_3y > 0.65
                      ? "looser than usual, you have more room to negotiate."
                      : "about normal for this ZIP.")}
            </p>
          </div>
        </section>
      )}

      {zips.length > 0 && (
        <SupplyTrend geoType="zip" geos={zips} title="Trend — ZIP" window={window} />
      )}

      {cities.length > 0 && (
        <SupplyTrend geoType="city" geos={cities} title="Trend — city" window={window} />
      )}

      {zips.length > 0 && (
        <section>
          <SectionTitle>ZIP comparison</SectionTitle>
          <SupplyRows rows={zips} linkable window={window} />
        </section>
      )}

      {cities.length > 0 && (
        <section>
          <SectionTitle>City context</SectionTitle>
          <p className="mb-2 text-xs text-slate-400">
            The same two figures rolled up to the city — the value a thin ZIP borrows when it
            has too few sales of its own.
          </p>
          <SupplyRows rows={cities} linkable={false} window={window} />
        </section>
      )}

      <MetricDefinitions window={window} />
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getMarketSummary, getPipelineRuns } from "../api/client";
import MetricTile from "../components/MetricTile";
import RateChart from "../components/RateChart";
import SeriesExplorer from "../components/SeriesExplorer";
import ZipTable from "../components/ZipTable";
import { money } from "../lib/format";

const STATUS_COLOR: Record<string, string> = {
  ok: "text-emerald-600",
  noop: "text-slate-500",
  partial: "text-amber-600",
  failed: "text-red-600",
  running: "text-blue-600",
};

const TILE_METRICS = [
  "median_sale_price",
  "median_ppsf",
  "avg_sp_lp",
  "median_dom",
  "inventory",
  "months_supply",
];

export default function Dashboard() {
  const summary = useQuery({ queryKey: ["market-summary"], queryFn: getMarketSummary });
  const runs = useQuery({ queryKey: ["pipeline-runs"], queryFn: () => getPipelineRuns() });
  const [focusZip, setFocusZip] = useState<string | null>(null);

  const zips = summary.data?.zips ?? [];
  const focused = zips.find((z) => z.geo_id === focusZip) ?? zips[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        {summary.data && (
          <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white">
            Shopping band: {money(summary.data.target_band.min)} –{" "}
            {money(summary.data.target_band.max)}
          </span>
        )}
      </div>

      {zips.length === 0 && !summary.isLoading && (
        <p className="text-sm text-slate-400">
          No market data yet — run `hb pipeline daily` to fill the dashboard.
        </p>
      )}

      {focused && (
        <section>
          <div className="mb-2 flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Focus ZIP
            </h2>
            <select
              value={focused.geo_id}
              onChange={(e) => setFocusZip(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            >
              {zips.map((z) => (
                <option key={z.geo_id} value={z.geo_id}>
                  {z.geo_id} — {z.city}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
            {TILE_METRICS.map((m) => (
              <MetricTile
                key={m}
                geoType="zip"
                geoId={focused.geo_id}
                metric={m}
                value={focused.metrics[m]}
                delta90d={focused.deltas_90d[m]}
                basis={focused.sources[m]}
              />
            ))}
          </div>
        </section>
      )}

      {zips.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            ZIP comparison
          </h2>
          <ZipTable zips={zips} />
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <RateChart />
        {zips.length > 0 && <SeriesExplorer zips={zips} />}
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Pipeline freshness
        </h2>
        {runs.data?.length === 0 && (
          <p className="text-sm text-slate-400">No pipeline runs yet — run `hb pipeline daily`.</p>
        )}
        <div className="overflow-x-auto">
          <table className="min-w-[36rem] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-2 pr-6">Job</th>
                <th className="py-2 pr-6">Status</th>
                <th className="py-2 pr-6">Finished</th>
                <th className="py-2 pr-6">Items</th>
                <th className="py-2">Errors</th>
              </tr>
            </thead>
            <tbody>
              {runs.data?.map((r) => (
                <tr key={r.id} className="border-b border-slate-100">
                  <td className="py-2 pr-6 font-medium">{r.job}</td>
                  <td className={`py-2 pr-6 font-medium ${STATUS_COLOR[r.status] ?? ""}`}>
                    {r.status}
                  </td>
                  <td className="py-2 pr-6">{r.finished_at ?? "—"}</td>
                  <td className="py-2 pr-6">{r.items_seen}</td>
                  <td className="max-w-md truncate py-2 text-slate-500">
                    {r.error_summary ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

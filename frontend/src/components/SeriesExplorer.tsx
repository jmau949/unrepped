import { useQueries } from "@tanstack/react-query";
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
import { getSeries, type ZipSummary } from "../api/client";
import { METRIC_LABELS, metricValue } from "../lib/format";

const COLORS = ["#0f172a", "#0284c7", "#d97706", "#dc2626"];

export default function SeriesExplorer({ zips }: { zips: ZipSummary[] }) {
  const [metric, setMetric] = useState("median_ppsf");
  const [selected, setSelected] = useState<string[]>(zips.slice(0, 2).map((z) => z.geo_id));
  const since = new Date(Date.now() - 3 * 365 * 86_400_000).toISOString().slice(0, 10);

  const queries = useQueries({
    queries: selected.map((zip) => ({
      queryKey: ["series", "zip", zip, metric, since],
      queryFn: () => getSeries("zip", zip, metric, since),
      staleTime: 60 * 60 * 1000,
    })),
  });

  // merge on period_start: [{period_start, [zip]: value}]
  const merged = new Map<string, Record<string, number | string>>();
  queries.forEach((q, i) => {
    (q.data ?? []).forEach((p) => {
      const row = merged.get(p.period_start) ?? { period_start: p.period_start };
      row[selected[i]] = p.value;
      merged.set(p.period_start, row);
    });
  });
  const data = [...merged.values()].sort((a, b) =>
    String(a.period_start).localeCompare(String(b.period_start)),
  );

  const toggle = (zip: string) =>
    setSelected((cur) =>
      cur.includes(zip) ? cur.filter((z) => z !== zip) : cur.length < 4 ? [...cur, zip] : cur,
    );

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Compare ZIPs
        </h2>
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          {Object.entries(METRIC_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <div className="flex max-w-full flex-wrap gap-1">
          {zips.map((z) => (
            <button
              key={z.geo_id}
              onClick={() => toggle(z.geo_id)}
              className={`rounded-full px-2 py-0.5 text-xs ${
                selected.includes(z.geo_id)
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {z.geo_id}
            </button>
          ))}
        </div>
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="period_start" tick={{ fontSize: 11 }} minTickGap={50} />
            <YAxis
              tick={{ fontSize: 11 }}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => metricValue(metric, v)}
              width={80}
            />
            <Tooltip formatter={(v) => metricValue(metric, Number(v))} />
            <Legend />
            {selected.map((zip, i) => (
              <Line
                key={zip}
                type="monotone"
                dataKey={zip}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={1.5}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

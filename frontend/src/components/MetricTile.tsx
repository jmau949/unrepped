import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { getSeries } from "../api/client";
import { METRIC_LABELS, metricValue, pct } from "../lib/format";

interface Props {
  geoType: string;
  geoId: string;
  metric: string;
  value: number | null;
  delta90d: number | null;
  /** provenance of `value`; "derived_city" means it was borrowed from the parent city */
  basis?: string | null;
}

export default function MetricTile({
  geoType,
  geoId,
  metric,
  value,
  delta90d,
  basis,
}: Props) {
  const since = new Date(Date.now() - 365 * 86_400_000).toISOString().slice(0, 10);
  const series = useQuery({
    queryKey: ["series", geoType, geoId, metric, since],
    queryFn: () => getSeries(geoType, geoId, metric, since),
    staleTime: 60 * 60 * 1000,
  });

  const deltaColor =
    delta90d == null ? "text-slate-400" : delta90d > 0 ? "text-emerald-600" : "text-red-600";
  const arrow = delta90d == null ? "" : delta90d > 0 ? "▲" : "▼";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {METRIC_LABELS[metric] ?? metric}
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-2">
        <span className="text-xl font-bold">
          {metricValue(metric, value)}
          {basis === "derived_city" && (
            <span
              title="Too few sales in this ZIP — showing the parent city's figure"
              className="ml-1 rounded bg-slate-100 px-1 py-0.5 align-middle text-[10px] font-medium text-slate-500"
            >
              city
            </span>
          )}
        </span>
        <span className={`text-xs font-medium ${deltaColor}`}>
          {arrow} {pct(delta90d)} <span className="text-slate-400">90d</span>
        </span>
      </div>
      <div className="mt-1 h-8">
        {series.data && series.data.length > 1 && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series.data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#0f172a"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

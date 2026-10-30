import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OverbidResult } from "../api/client";

/** Weighted SP/LP histogram with p25/p50/p75 markers (docs/08 §3 item 3). */
export default function OverbidHistogram({ overbid }: { overbid: OverbidResult }) {
  if (!overbid.histogram.length) {
    return <p className="text-sm text-slate-400">Not enough comps for a distribution.</p>;
  }
  const data = overbid.histogram.map((h) => ({
    mid: (h.bucket_low + h.bucket_high) / 2,
    weight: h.weight,
  }));
  const inRange = (mid: number) =>
    overbid.p25 != null && overbid.p75 != null && mid >= overbid.p25 && mid <= overbid.p75;

  return (
    <div className="h-40">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          {/* numeric axis: a categorical axis only matched the p50 reference
              line when the rounded label happened to equal a bucket edge, so
              the marker usually never rendered */}
          <XAxis dataKey="mid" type="number" domain={["dataMin", "dataMax"]}
            tick={{ fontSize: 10 }} minTickGap={8}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
          <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
          <Tooltip
            formatter={(v) => [Number(v).toFixed(2), "weight"]}
            labelFormatter={(l) => `SP/LP ${(Number(l) * 100).toFixed(1)}%`}
          />
          {overbid.p50 != null && (
            <ReferenceLine x={overbid.p50} stroke="#dc2626"
              strokeWidth={1.5} label={{ value: "p50", fontSize: 10, fill: "#dc2626" }} />
          )}
          <Bar dataKey="weight" radius={[2, 2, 0, 0]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={inRange(d.mid) ? "#0284c7" : "#cbd5e1"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

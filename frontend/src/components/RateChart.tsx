import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getRates } from "../api/client";

export default function RateChart() {
  const since = new Date(Date.now() - 730 * 86_400_000).toISOString().slice(0, 10);
  const rates = useQuery({
    queryKey: ["rates", since],
    queryFn: () => getRates("MORTGAGE30US", since),
    staleTime: 60 * 60 * 1000,
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        30-yr mortgage rate (24 mo)
      </h2>
      {rates.data?.length === 0 && (
        <p className="py-8 text-center text-sm text-slate-400">
          No rate data — set FRED_API_KEY in .env and run `hb pipeline fred`.
        </p>
      )}
      {rates.data && rates.data.length > 0 && (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rates.data} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
              <YAxis
                tick={{ fontSize: 11 }}
                domain={["dataMin - 0.2", "dataMax + 0.2"]}
                tickFormatter={(v: number) => `${v.toFixed(1)}%`}
              />
              <Tooltip formatter={(v) => [`${Number(v).toFixed(2)}%`, "30-yr rate"]} />
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
        </div>
      )}
    </div>
  );
}

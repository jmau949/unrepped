import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import type { ZipSummary } from "../api/client";
import { METRIC_LABELS, metricValue } from "../lib/format";

const COLUMNS = [
  "median_sale_price",
  "median_ppsf",
  "avg_sp_lp",
  "median_dom",
  "inventory",
  "months_supply",
];

export default function ZipTable({ zips }: { zips: ZipSummary[] }) {
  const [sortBy, setSortBy] = useState<string>("median_sale_price");
  const [desc, setDesc] = useState(true);
  const navigate = useNavigate();

  const sorted = [...zips].sort((a, b) => {
    const av = sortBy === "zip" ? Number(a.geo_id) : (a.metrics[sortBy] ?? -Infinity);
    const bv = sortBy === "zip" ? Number(b.geo_id) : (b.metrics[sortBy] ?? -Infinity);
    return desc ? Number(bv) - Number(av) : Number(av) - Number(bv);
  });

  const header = (key: string, label: string) => (
    <th
      key={key}
      onClick={() => {
        if (sortBy === key) setDesc(!desc);
        else {
          setSortBy(key);
          setDesc(true);
        }
      }}
      className="cursor-pointer select-none whitespace-nowrap py-2 pr-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-900"
    >
      {label} {sortBy === key ? (desc ? "↓" : "↑") : ""}
    </th>
  );

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-3">
      <table className="min-w-[52rem] text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            {header("zip", "ZIP")}
            <th className="py-2 pr-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              City
            </th>
            {COLUMNS.map((c) => header(c, METRIC_LABELS[c] ?? c))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((z) => (
            <tr
              key={z.geo_id}
              className="cursor-pointer border-b border-slate-100 hover:bg-slate-50"
              onClick={() => navigate({ to: "/listings", search: { zip: z.geo_id } as never })}
            >
              <td className="py-2 pr-4 font-medium">{z.geo_id}</td>
              <td className="py-2 pr-4 text-slate-500">{z.city}</td>
              {COLUMNS.map((c) => {
                const delta = z.deltas_90d[c];
                return (
                  <td key={c} className="whitespace-nowrap py-2 pr-4">
                    {metricValue(c, z.metrics[c])}
                    {delta != null && (
                      <span
                        className={`ml-1 text-xs ${delta > 0 ? "text-emerald-600" : "text-red-600"}`}
                      >
                        {delta > 0 ? "▲" : "▼"}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";
import { getCompare, getTracked, type CompareItem } from "../api/client";
import HazardChips from "../components/HazardChips";
import { money } from "../lib/format";

const CHECKLIST_KEYS = ["packet_received", "tds_spq_read", "pest_section1_total",
  "nhd_read", "hoa_docs", "insurance_quoted"];

// row config drives both rendering and best-value highlighting;
// best: "min"/"max" marks the winner, null rows are informational
const ROWS: {
  label: string;
  value: (i: CompareItem) => number | null;
  render?: (i: CompareItem) => React.ReactNode;
  best: "min" | "max" | null;
}[] = [
  { label: "List price", value: (i) => i.list_price, best: "min" },
  {
    label: "Posture",
    value: () => null,
    render: (i) =>
      i.posture ? (
        <span
          title="Share of past listings in this area with the same exposure that sold below their asking price (docs/06 §5.6). overpriced = lingering, most sell a little under asking; underpriced = early, most sell above; near market = close to even."
          className={
            i.posture === "overpriced"
              ? "font-semibold text-red-700"
              : i.posture === "underpriced"
                ? "font-semibold text-amber-700"
                : "text-slate-600"
          }
        >
          {i.posture.replace("_", " ")}
          {i.posture_p_below_list != null
            ? ` · ${Math.round(i.posture_p_below_list * 100)}% sell below asking`
            : ""}
        </span>
      ) : null,
    best: null,
  },
  { label: "CMA estimate", value: (i) => i.cma?.estimate ?? null, best: null },
  {
    label: "Predicted sale",
    value: (i) => i.predicted_sale?.point ?? null,
    render: (i) =>
      i.predicted_sale
        ? `${money(i.predicted_sale.low)} – ${money(i.predicted_sale.high)}`
        : null,
    best: "min",
  },
  { label: "$/sqft", value: (i) => i.price_per_sqft, best: "min" },
  { label: "PITI at predicted", value: (i) => i.piti_at_point, best: "min" },
  { label: "CDOM (leverage)", value: (i) => i.cumulative_dom, best: "max" },
  { label: "My max bid", value: (i) => i.tracked?.my_max_bid ?? null, best: null },
  {
    label: "Hazards",
    value: () => null,
    render: (i) => (i.hazard_flags.length ? <HazardChips flags={i.hazard_flags} /> : "none"),
    best: null,
  },
  {
    label: "Sqft mismatch",
    value: () => null,
    render: (i) =>
      i.sqft_mismatch ? <span className="font-semibold text-red-600">⚠ &gt;15%</span> : "ok",
    best: null,
  },
  {
    label: "Disclosures",
    value: () => null,
    render: (i) => {
      if (!i.tracked) return null;
      const done = CHECKLIST_KEYS.filter((k) => {
        const v = i.tracked!.disclosure_checklist?.[k];
        return v !== null && v !== undefined && v !== false && v !== "";
      }).length;
      return `${done}/${CHECKLIST_KEYS.length} ✓`;
    },
    best: null,
  },
];

export default function Compare() {
  const { ids } = useSearch({ from: "/compare" });
  const idList = ids.split(",").filter(Boolean);
  return idList.length >= 2 ? <Grid ids={idList} /> : <Picker preselected={idList} />;
}

function Picker({ preselected }: { preselected: string[] }) {
  const navigate = useNavigate();
  const tracked = useQuery({ queryKey: ["tracked"], queryFn: getTracked });
  const [sel, setSel] = useState<string[]>(preselected);
  const toggle = (id: string) =>
    setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length < 4 ? [...s, id] : s));

  return (
    <div className="max-w-xl">
      <h1 className="mb-2 text-2xl font-bold">Compare</h1>
      <p className="mb-4 text-sm text-slate-500">
        Pick 2–4 tracked listings to compare side by side.
      </p>
      {(tracked.data ?? []).length === 0 && (
        <p className="text-sm text-slate-400">
          Nothing tracked yet — star listings from the Listings page first.
        </p>
      )}
      <div className="space-y-2">
        {(tracked.data ?? []).map((t) => (
          <label
            key={t.id}
            className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 text-sm hover:border-slate-300"
          >
            <input
              type="checkbox"
              checked={sel.includes(t.listing.id)}
              onChange={() => toggle(t.listing.id)}
            />
            <span className="font-medium">{t.listing.address}</span>
            <span className="ml-auto text-slate-500">{money(t.listing.list_price)}</span>
          </label>
        ))}
      </div>
      <button
        disabled={sel.length < 2}
        onClick={() => navigate({ to: "/compare", search: { ids: sel.join(",") } })}
        className="mt-4 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
      >
        Compare {sel.length} listings
      </button>
    </div>
  );
}

function Grid({ ids }: { ids: string[] }) {
  const q = useQuery({ queryKey: ["compare", ids.join(",")], queryFn: () => getCompare(ids) });
  if (q.isLoading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!q.data) return <p className="text-sm text-red-500">Compare failed — are the listings still in the DB?</p>;
  const items = q.data;

  const bestIndex = (row: (typeof ROWS)[number]): number | null => {
    const vals = items.map(row.value);
    const present = vals.filter((v): v is number => v != null);
    if (row.best === null || present.length < 2) return null;
    const target = row.best === "min" ? Math.min(...present) : Math.max(...present);
    return vals.findIndex((v) => v === target);
  };

  return (
    <div>
      <div className="mb-4 flex items-baseline gap-4">
        <h1 className="text-2xl font-bold">Compare</h1>
        <Link to="/compare" search={{ ids: "" }} className="text-xs text-blue-600 underline">
          change selection
        </Link>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full min-w-[48rem] text-sm">
          <thead>
            <tr className="border-b border-slate-200 align-top">
              <th className="w-44 p-3"></th>
              {items.map((i) => (
                <th key={i.id} className="p-3 text-left font-normal">
                  {i.photo_url && (
                    <img src={i.photo_url} alt="" className="mb-2 h-24 w-full rounded object-cover" />
                  )}
                  <Link
                    to="/listings/$listingId"
                    params={{ listingId: i.id }}
                    className="font-semibold text-blue-700 hover:underline"
                  >
                    {i.address}
                  </Link>
                  <p className="text-xs text-slate-500">
                    {i.city} {i.zip} · {i.beds}bd/{i.baths}ba
                    {i.sqft ? ` · ${i.sqft.toLocaleString()} sqft` : ""}
                  </p>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => {
              const best = bestIndex(row);
              return (
                <tr key={row.label} className="border-b border-slate-100">
                  <td className="p-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {row.label}
                  </td>
                  {items.map((i, idx) => {
                    const rendered = row.render ? row.render(i) : null;
                    const value = row.value(i);
                    const content =
                      rendered ?? (value != null
                        ? row.label === "CDOM (leverage)" ? `${value}d` : money(value)
                        : null);
                    return (
                      <td
                        key={i.id}
                        className={`p-3 ${idx === best ? "bg-emerald-50 font-semibold" : ""}`}
                      >
                        {content ?? <span className="text-slate-300">—</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

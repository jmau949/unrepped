import type { OverbidResult } from "../api/client";
import { money, vsAsking } from "../lib/format";

/** Within one percent of the asking price either way counts as "at asking". */
const AT_ASK = 0.01;

const GROUPS = [
  { id: "over", label: "over asking", bar: "bg-amber-500", dot: "bg-amber-500" },
  { id: "at", label: "at asking", bar: "bg-slate-400", dot: "bg-slate-400" },
  { id: "under", label: "under asking", bar: "bg-sky-600", dot: "bg-sky-600" },
] as const;

function groupOf(ratio: number): (typeof GROUPS)[number]["id"] {
  if (ratio > 1 + AT_ASK) return "over";
  if (ratio < 1 - AT_ASK) return "under";
  return "at";
}

/** How the similar sales split — over, at, or under their asking price — as one
 *  bar, with the sales themselves a click away (docs/08 §3 item 3). */
export default function SaleVsAskBar({ overbid }: { overbid: OverbidResult }) {
  const comps = overbid.comps;
  if (comps.length === 0) return null;
  const counts = { over: 0, at: 0, under: 0 };
  comps.forEach((c) => { counts[groupOf(c.sp_lp)] += 1; });

  return (
    <div>
      <p className="text-xs font-medium text-slate-600">
        {comps.length} similar sale{comps.length === 1 ? "" : "s"}
      </p>
      <div className="mt-1 flex h-5 overflow-hidden rounded">
        {GROUPS.filter((g) => counts[g.id] > 0).map((g) => (
          <div
            key={g.id}
            className={`${g.bar} flex items-center justify-center text-[11px] font-semibold text-white`}
            style={{ width: `${(counts[g.id] / comps.length) * 100}%` }}
            title={`${counts[g.id]} ${g.label}`}
          >
            {counts[g.id]}
          </div>
        ))}
      </div>
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-600">
        {GROUPS.map((g) => (
          <li key={g.id} className="flex items-center gap-1">
            <span className={`inline-block h-2 w-2 rounded-sm ${g.dot}`} />
            <b>{counts[g.id]}</b> {g.label}
          </li>
        ))}
      </ul>

      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-sky-700">
          See the {comps.length} sale{comps.length === 1 ? "" : "s"}
        </summary>
        <table className="mt-1 w-full">
          <thead>
            <tr className="text-left text-[11px] text-slate-400">
              <th className="py-0.5 font-normal">Home</th>
              <th className="py-0.5 font-normal">Sold</th>
              <th className="py-0.5 text-right font-normal">Asked</th>
              <th className="py-0.5 text-right font-normal">Sold for</th>
              <th className="py-0.5 text-right font-normal">Result</th>
            </tr>
          </thead>
          <tbody>
            {comps.map((c, i) => {
              const g = groupOf(c.sp_lp);
              return (
                <tr key={i} className="border-t border-slate-100">
                  <td className="max-w-[9rem] truncate py-0.5 pr-2" title={c.address}>{c.address}</td>
                  <td className="py-0.5 pr-2 text-slate-500">{c.sale_date}</td>
                  <td className="py-0.5 text-right tabular-nums text-slate-500">
                    {money(c.original_list_price)}
                  </td>
                  <td className="py-0.5 text-right tabular-nums">{money(c.sale_price)}</td>
                  <td className={`py-0.5 text-right tabular-nums ${
                    g === "over" ? "text-amber-700" : g === "under" ? "text-sky-700" : "text-slate-500"
                  }`}>
                    {vsAsking(c.sp_lp).replace(" asking", "")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-1 text-[11px] text-slate-400">
          Asked = original list price.
        </p>
      </details>
    </div>
  );
}

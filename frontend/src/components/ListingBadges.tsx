import type { ListingSummary } from "../api/client";
import { openHouseWindow } from "../lib/format";

export default function ListingBadges({
  l,
  hidePredicted = false,
  hideOpenHouse = false,
}: {
  l: ListingSummary;
  hidePredicted?: boolean;
  /** the Open Houses page already shows the slot itself */
  hideOpenHouse?: boolean;
}) {
  const cdomDiffers =
    l.cumulative_dom != null && l.dom_source != null && l.cumulative_dom > l.dom_source;
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {(l.cut_pct != null || l.price_cut_count > 0) && (
        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700"
              title={`reduced from the original ask${l.price_cut_count > 0
                ? ` in ${l.price_cut_count} observed step(s)` : ""}`}>
          ↓ {l.cut_pct != null ? `${l.cut_pct}%` : "cut"}
          {l.price_cut_count > 1 && ` ×${l.price_cut_count}`}
        </span>
      )}
      {l.status === "sold" && (
        <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-white">
          sold
        </span>
      )}
      {l.status === "pending" && (
        <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
          PENDING
        </span>
      )}
      {l.is_relist && (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
          RELIST
        </span>
      )}
      {(l.cumulative_dom != null || l.dom_source != null) && (
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
          {cdomDiffers && <s className="mr-1 text-slate-400">{l.dom_source}d</s>}
          {l.cumulative_dom ?? l.dom_source}d
        </span>
      )}
      {l.next_open_house && !hideOpenHouse && (
        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700"
              title="next scheduled open house">
          Open {openHouseWindow(l.next_open_house.start_at, l.next_open_house.end_at)}
        </span>
      )}
      {l.predicted_sale && !hidePredicted && (
        <span className="rounded-full bg-slate-900 px-2 py-0.5 text-xs font-medium text-white"
              title="predicted sale price (blended CMA + overbid model)">
          ~${(l.predicted_sale.point / 1_000_000).toFixed(2)}M
        </span>
      )}
    </span>
  );
}

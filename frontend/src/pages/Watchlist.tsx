import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { getWatchlist, markWatchlistSeen, setWatching, type WatchedItem } from "../api/client";
import { money, pct } from "../lib/format";
import { statusLabel, statusPillClass } from "../lib/status";

// Status tabs in reading order; `delisted` reads as "Off market" to a buyer.
const TABS = [
  { key: "all", label: "All" },
  { key: "active", label: "For sale" },
  { key: "pending", label: "Pending" },
  { key: "sold", label: "Sold" },
  { key: "delisted", label: "Off market" },
] as const;
type Tab = (typeof TABS)[number]["key"];

// The API returns latest change first; "added" re-sorts by when the home was watched.
const SORTS = [
  { key: "added", label: "Recently added" },
  { key: "changed", label: "Latest change" },
] as const;
type Sort = (typeof SORTS)[number]["key"];

const EVENT_LABEL: Record<string, string> = {
  new: "Listed", price_change: "Price change", pending: "Went pending",
  back_on_market: "Back on market", delisted: "Taken off market", relisted: "Relisted",
  sold: "Sold", status_change: "Status change",
};

/** "2026-10-05" or an ISO instant -> "Oct 5"; date-only strings stay local
 * (new Date("2026-10-05") is UTC midnight, a day early west of Greenwich). */
function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** The row's one plain-language sentence: what the home did after you looked. */
function story(w: WatchedItem): string {
  const dom = w.cumulative_dom ?? w.dom_source;
  const cuts = w.price_cut_count > 0 || w.cut_pct != null
    ? `cut ${w.price_cut_count > 1 ? `${w.price_cut_count}× ` : ""}to ${money(w.list_price)}${
        w.cut_pct != null ? ` (−${w.cut_pct}%)` : ""}`
    : null;
  if (w.status === "sold") {
    const parts = [`Sold ${shortDate(w.sold_date)} for ${money(w.sold_price)}`];
    if (w.sp_lp != null) {
      const d = w.sp_lp - 1;
      parts.push(`${d >= 0 ? "+" : ""}${pct(d)} vs the original ${money(w.original_list_price)} ask`);
    }
    if (w.sold_source === "public_record") parts.push("after it left the market (public record)");
    return parts.join(", ");
  }
  if (w.status === "pending") {
    return `Under contract${dom != null ? ` after ${dom} days` : ""}${cuts ? `, ${cuts} first` : " at the original ask"}`;
  }
  if (w.status === "delisted") {
    return `Taken off the market${cuts ? ` after being ${cuts}` : ""} — watching for a relist or a quiet sale`;
  }
  return `${cuts ? `For sale, ${cuts}` : `For sale at the original ${money(w.list_price)} ask`}${
    dom != null ? ` · ${dom} days on market` : ""}`;
}

/** What you did with the home, so a row says why it is on the list. */
function involvement(w: WatchedItem): string {
  const i = w.involvement;
  const parts: string[] = [];
  if (i.last_toured_on) {
    parts.push(`Toured ${shortDate(i.last_toured_on)}${i.tour_count > 1 ? ` (${i.tour_count}×)` : ""}`);
    if (i.verdict) parts.push(`verdict: ${i.verdict}`);
    if (i.gut_score != null) parts.push(`gut ${i.gut_score}/5`);
  }
  if (i.stage) parts.push(`Tracker: ${i.stage.replace("_", " ")}`);
  if (i.my_max_bid) parts.push(`your max ${money(i.my_max_bid)}`);
  return parts.join(" · ");
}

export default function Watchlist() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("all");
  const [sort, setSort] = useState<Sort>("added");
  const list = useQuery({ queryKey: ["watchlist"], queryFn: getWatchlist });

  // "Changed since your last visit" compares against the stamp as it stood when
  // the page opened; the visit is then recorded, so refetches don't clear it.
  const [lastVisit, setLastVisit] = useState<string | null | undefined>(undefined);
  const stamped = useRef(false);
  useEffect(() => {
    if (!list.data || stamped.current) return;
    stamped.current = true;
    setLastVisit(list.data.last_seen_at);
    markWatchlistSeen().catch(() => { /* next visit simply re-highlights */ });
  }, [list.data]);

  const removeMut = useMutation({
    mutationFn: (propertyId: string) => setWatching(propertyId, false),
    onSettled: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const fetched = list.data?.items ?? [];
  const items = sort === "added"
    ? [...fetched].sort((a, b) => b.watched_at.localeCompare(a.watched_at))
    : fetched;
  const isNew = (w: WatchedItem) =>
    !!lastVisit && !!w.last_change && w.last_change.observed_at > lastVisit;
  const count = (key: Tab) => key === "all" ? items.length : items.filter((w) => w.status === key).length;
  const shown = tab === "all" ? items : items.filter((w) => w.status === tab);
  const newCount = items.filter(isNew).length;

  return (
    <div className="max-w-4xl space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="mr-2 text-2xl font-bold">Watchlist</h1>
          {newCount > 0 && (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
              {newCount} changed since your last visit
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Every home you watched, saved to the <Link to="/tracker" className="text-blue-600 hover:underline">Tracker</Link> or
          toured, and what happened to it next — price cuts, pending, sold and for how much. The daily
          scan keeps it current, including after you pass on a home or stop looking.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
                  className={`rounded-full px-3 py-1 text-sm ${
                    tab === t.key ? "bg-slate-900 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"}`}>
            {t.label} <span className={tab === t.key ? "text-slate-300" : "text-slate-400"}>{count(t.key)}</span>
          </button>
        ))}
        <div className="ml-auto flex rounded-md ring-1 ring-slate-200" role="group" aria-label="Sort">
          {SORTS.map((s) => (
            <button key={s.key} onClick={() => setSort(s.key)}
                    className={`px-2.5 py-1 text-sm first:rounded-l-md last:rounded-r-md ${
                      sort === s.key ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white">
        {list.isLoading && <p className="p-6 text-sm text-slate-400">Loading…</p>}
        {!list.isLoading && items.length === 0 && (
          <div className="space-y-1 p-6 text-sm text-slate-500">
            <p className="font-medium text-slate-700">Nothing on your Watchlist yet.</p>
            <p>
              A home lands here when you press <span className="font-medium">👁 Watch</span> on a listing, add it
              to the Tracker, or log a tour of it. It stays here whatever you decide, so you can see what it
              eventually sold for. Use <span className="font-medium">Remove</span> on a row to drop one.
            </p>
          </div>
        )}
        {!list.isLoading && items.length > 0 && shown.length === 0 && (
          <p className="p-6 text-sm text-slate-400">No watched homes in this group.</p>
        )}
        <ul className="divide-y divide-slate-100">
          {shown.map((w) => {
            const fresh = isNew(w);
            const price = w.status === "sold" ? w.sold_price : w.list_price;
            return (
              <li key={w.property_id} className="flex gap-3 p-3">
                <Link to="/listings/$listingId" params={{ listingId: w.id }} className="shrink-0">
                  {w.photo_url
                    ? <img src={w.photo_url} alt="" loading="lazy" className="h-16 w-20 rounded object-cover" />
                    : <div className="h-16 w-20 rounded bg-slate-100" />}
                </Link>
                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {fresh && <span className="h-2 w-2 shrink-0 rounded-full bg-blue-500" title="Changed since your last visit" />}
                    <Link to="/listings/$listingId" params={{ listingId: w.id }}
                          className="font-medium hover:underline">
                      {w.address}
                    </Link>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusPillClass(w.status)}`}>
                      {statusLabel(w.status)}
                    </span>
                  </div>
                  <p className="text-sm text-slate-700">{story(w)}</p>
                  {involvement(w) && <p className="text-xs text-slate-500">{involvement(w)}</p>}
                  <p className="text-xs text-slate-400">
                    {w.city} {w.zip} · {w.beds}bd/{w.baths}ba · {w.sqft?.toLocaleString()} sqft
                    {w.last_change && (
                      <> · last change: {EVENT_LABEL[w.last_change.event_type] ?? w.last_change.event_type}{" "}
                        {shortDate(w.last_change.observed_at)}</>
                    )}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end justify-between gap-1">
                  <div className="text-right">
                    <div className="font-semibold">{money(price)}</div>
                    {w.vs_max_bid != null && (
                      <div className={`text-xs ${w.vs_max_bid > 0 ? "text-red-600" : "text-emerald-600"}`}
                           title="Sold price minus the max bid you set on the Tracker">
                        {money(Math.abs(w.vs_max_bid))} {w.vs_max_bid > 0 ? "over" : "under"} your max
                      </div>
                    )}
                  </div>
                  <button onClick={() => removeMut.mutate(w.property_id)}
                          disabled={removeMut.isPending && removeMut.variables === w.property_id}
                          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:border-red-300 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"
                          title="Remove from the Watchlist and its alerts (👁 Watch on the listing puts it back)">
                    ✕ Remove
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

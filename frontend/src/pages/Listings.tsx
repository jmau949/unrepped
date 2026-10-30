import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  getListings,
  getMarketSummary,
  track,
  untrack,
  getTracked,
  type ListingFilters,
} from "../api/client";
import ListingBadges from "../components/ListingBadges";
import LazyMapView from "../components/LazyMapView";
import type { MapBounds } from "../components/MapView";
import { useCities } from "../lib/config";
import { deltaVsAsk, money, pct } from "../lib/format";
import MoneyInput from "../components/MoneyInput";

export default function Listings() {
  const search = useSearch({ strict: false }) as Record<string, string | undefined>;
  const cities = useCities();
  const openDetail = (id: string) =>
    window.open(`/listings/${id}`, "_blank", "noopener,noreferrer");
  const qc = useQueryClient();
  const summary = useQuery({ queryKey: ["market-summary"], queryFn: getMarketSummary });
  const band = summary.data?.target_band;

  const [filters, setFilters] = useState<ListingFilters>({
    status: "active,pending",
    zip: search.zip,
    min_price: undefined, // undefined = "use band default"; null = cleared
    max_price: undefined,
    sort: "list_date",
  });

  // Typing is cheap; refetching is not — every keystroke would re-run the
  // per-row prediction pass server-side. Settle for 250ms first.
  const [queryText, setQueryText] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(queryText.trim()), 250);
    return () => clearTimeout(t);
  }, [queryText]);

  // A search is a hunt for one specific home, so the *default* band must not
  // silently hide it. An explicitly typed range still applies.
  const bandApplies = !q;
  const effective: ListingFilters = {
    ...filters,
    q: q || undefined,
    min_price: filters.min_price === undefined
      ? (bandApplies ? band?.min : undefined) : filters.min_price,
    max_price: filters.max_price === undefined
      ? (bandApplies ? band?.max : undefined) : filters.max_price,
  };

  const listings = useQuery({
    queryKey: ["listings", effective],
    queryFn: () => getListings(effective),
    enabled: !!band,
  });
  const tracked = useQuery({ queryKey: ["tracked"], queryFn: getTracked });
  const trackMut = useMutation({
    mutationFn: async (l: { id: string; tracked: boolean }) => {
      if (l.tracked) {
        const t = tracked.data?.find((t) => t.listing.id === l.id);
        if (t) await untrack(t.id);
      } else {
        await track(l.id);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["listings"] });
      qc.invalidateQueries({ queryKey: ["tracked"] });
    },
  });

  // Hover is two-way, so the source matters: only a map-driven hover scrolls
  // the table, otherwise moving down the rows would fight the scroll position.
  const [rowHovered, setRowHovered] = useState<string | null>(null);
  const [mapHovered, setMapHovered] = useState<string | null>(null);
  const hovered = rowHovered ?? mapHovered;
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());
  useEffect(() => {
    if (mapHovered) rowRefs.current.get(mapHovered)?.scrollIntoView({ block: "center" });
  }, [mapHovered]);

  // The map keeps every result — it is the thing being panned — and the table
  // narrows to the current viewport. Filtering the map's own input instead
  // would loop: fewer pins → refit → tighter bounds → fewer pins.
  const [bounds, setBounds] = useState<MapBounds | null>(null);
  const [refitKey, setRefitKey] = useState(0);
  const items = listings.data?.items ?? [];
  // Drop the stale viewport the moment the result set changes — the map is
  // about to refit and will report a fresh one. Keyed on the id set exactly as
  // MapView keys its refit, so a background refetch that returns the same rows
  // leaves the user's pan alone. Without this, a search for an address across
  // the bay empties the table until the fly-to animation lands.
  const signature = useMemo(() => items.map((l) => l.id).join(","), [items]);
  useEffect(() => setBounds(null), [signature]);
  const visible = bounds
    ? items.filter((l) =>
        // a home with no coordinates is on no map, so no viewport can judge it;
        // hiding it would make it unreachable from this page
        l.lat == null || l.lon == null ||
        (l.lon >= bounds.west && l.lon <= bounds.east &&
         l.lat >= bounds.south && l.lat <= bounds.north))
    : items;
  const offscreen = items.length - visible.length;
  const set = (patch: Partial<ListingFilters>) => setFilters((f) => ({ ...f, ...patch }));

  // One control drives two params: "any" reduction vs a percentage threshold.
  const cutFilter = filters.min_cut_pct != null ? String(filters.min_cut_pct)
    : filters.has_price_cut ? "any" : "";
  const setCutFilter = (v: string) => set({
    has_price_cut: v === "any" || undefined,
    min_cut_pct: v && v !== "any" ? Number(v) : undefined,
  });

  return (
    <div className="flex flex-col gap-4 lg:h-full">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-2xl font-bold">Listings</h1>
        <div className="relative">
          <input value={queryText} onChange={(e) => setQueryText(e.target.value)}
                 placeholder="search address, city, ZIP…"
                 aria-label="Search listings"
                 className="w-56 rounded border border-slate-300 py-1 pl-2 pr-6 text-sm" />
          {queryText && (
            <button onClick={() => setQueryText("")} aria-label="clear search"
                    className="absolute right-1 top-1/2 -translate-y-1/2 px-1 text-slate-400 hover:text-slate-700">
              ✕
            </button>
          )}
        </div>
        <select value={filters.status} onChange={(e) => set({ status: e.target.value })}
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          {[
            { v: "active,pending", label: "active + pending" },
            { v: "active", label: "active" },
            { v: "pending", label: "pending" },
            { v: "sold", label: "sold" },
            { v: "delisted", label: "delisted" },
            { v: "any", label: "any" },
          ].map((s) => (
            <option key={s.v} value={s.v}>{s.label}</option>
          ))}
        </select>
        <select value={filters.city ?? ""} onChange={(e) => set({ city: e.target.value || undefined })}
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="">all cities</option>
          {cities.map((c) => <option key={c}>{c}</option>)}
        </select>
        <input placeholder="ZIP" value={filters.zip ?? ""} size={5}
               onChange={(e) => set({ zip: e.target.value || undefined })}
               className="rounded border border-slate-300 px-2 py-1 text-sm" />
        <MoneyInput placeholder="min $" value={effective.min_price ?? null}
                    onChange={(v) => set({ min_price: v })}
                    className="w-28 rounded border border-slate-300 px-2 py-1 text-sm" />
        <MoneyInput placeholder="max $" value={effective.max_price ?? null}
                    onChange={(v) => set({ max_price: v })}
                    className="w-28 rounded border border-slate-300 px-2 py-1 text-sm" />
        {band && bandApplies && filters.min_price === undefined
          && filters.max_price === undefined && (
          <button onClick={() => set({ min_price: null, max_price: null })}
                  className="rounded-full bg-slate-900 px-2 py-0.5 text-xs text-white"
                  title="Filtering to your shopping band — click to clear">
            band {money(band.min)}–{money(band.max)} ✕
          </button>
        )}
        <select value={cutFilter} onChange={(e) => setCutFilter(e.target.value)}
                title="Filter by how far the ask has fallen below the original list price"
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="">any price move</option>
          <option value="any">reduced</option>
          <option value="3">reduced ≥ 3%</option>
          <option value="5">reduced ≥ 5%</option>
          <option value="10">reduced ≥ 10%</option>
        </select>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={!!filters.stale_only}
                 onChange={(e) => set({ stale_only: e.target.checked || undefined })} />
          stale only
        </label>
        <select value={filters.sort} onChange={(e) => set({ sort: e.target.value })}
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="list_date">newest</option>
          <option value="price">price</option>
          <option value="cdom">days on market</option>
          <option value="cut">biggest reduction</option>
        </select>
        <span className="text-sm text-slate-400">{listings.data?.total ?? "…"} results</span>
        {offscreen > 0 && (
          <button onClick={() => setRefitKey((k) => k + 1)}
                  className="rounded-full border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
                  title="The table lists only what the map is showing — click to zoom back out to every pin">
            {visible.length} in view · {offscreen} off-screen — reset map
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-2">
        <div className="max-h-[70dvh] overflow-auto rounded-lg border border-slate-200 bg-white lg:max-h-none">
          {visible.length === 0 && !listings.isLoading && (
            <p className="p-6 text-sm text-slate-400">
              {items.length > 0
                ? "Nothing in the map's current view — pan or zoom out, or reset the map."
                : "No listings match — clear the search or filters, or run `hb pipeline listing-scan`."}
            </p>
          )}
          <table className="w-full text-sm">
            <tbody>
              {visible.map((l) => {
                const soldDelta = deltaVsAsk(l.sold_price, l.original_list_price);
                return (
                <tr key={l.id}
                    ref={(el) => {
                      if (el) rowRefs.current.set(l.id, el);
                      else rowRefs.current.delete(l.id);
                    }}
                    onMouseEnter={() => setRowHovered(l.id)}
                    onMouseLeave={() => setRowHovered(null)}
                    onClick={() => openDetail(l.id)}
                    className={`cursor-pointer border-b border-slate-100 ${
                      hovered === l.id
                        ? "bg-blue-50 shadow-[inset_3px_0_0_0_theme(colors.blue.600)]"
                        : ""
                    }`}>
                  <td className="w-16 py-2 pl-2">
                    {l.photo_url
                      ? <img src={l.photo_url} alt="" className="h-10 w-14 rounded object-cover" loading="lazy" />
                      : <div className="h-10 w-14 rounded bg-slate-100" />}
                  </td>
                  <td className="py-2 pl-2">
                    <div className="font-medium">{l.address}</div>
                    <div className="text-xs text-slate-500">
                      {l.city} {l.zip} · {l.beds}bd/{l.baths}ba · {l.sqft?.toLocaleString()} sqft
                    </div>
                  </td>
                  <td className="py-2 pr-2 text-right sm:whitespace-nowrap">
                    {l.status === "sold" ? (
                      <>
                        <div className="font-semibold">{money(l.sold_price)}</div>
                        <div className="text-xs text-slate-500">
                          ask {money(l.original_list_price ?? l.list_price)}
                          {soldDelta != null && (
                            <span className={soldDelta >= 0 ? "text-emerald-600" : "text-red-600"}>
                              {" "}{soldDelta >= 0 ? "+" : ""}{pct(soldDelta)}
                            </span>
                          )}
                          {l.sold_date && ` · ${l.sold_date}`}
                        </div>
                      </>
                    ) : (
                      <div className="font-semibold">{money(l.list_price)}</div>
                    )}
                    <ListingBadges l={l} />
                  </td>
                  <td className="w-8 pr-2 text-center"
                      onClick={(e) => { e.stopPropagation(); trackMut.mutate(l); }}>
                    <span className={l.tracked ? "text-amber-500" : "text-slate-300"}
                          title={l.tracked ? "untrack" : "track"}>★</span>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="h-72 lg:h-auto lg:min-h-[24rem]">
          <LazyMapView listings={items} hoveredId={hovered} onSelect={openDetail}
                       onHover={setMapHovered} onBoundsChange={setBounds}
                       refitKey={refitKey} />
        </div>
      </div>
    </div>
  );
}

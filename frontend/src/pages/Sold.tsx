import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  getListings,
  getMarketSummary,
  type ListingFilters,
} from "../api/client";
import LazyMapView from "../components/LazyMapView";
import ListingLink from "../components/ListingLink";
import { useCities } from "../lib/config";
import { deltaVsAsk, money, pct } from "../lib/format";
import { useOpenListing } from "../lib/openListing";
import { loadSaved, save } from "../lib/sessionSaved";
import MoneyInput from "../components/MoneyInput";

const ppsf = (price: number | null, sqft: number | null) =>
  price && sqft ? `$${Math.round(price / sqft).toLocaleString()}` : "—";

/** Where the buyer was, kept per browser tab (as on Listings): the filters,
 *  and the homes opened from here — the detail page stamps viewed_at
 *  server-side, but the cached list won't refetch for a while, so the row
 *  flips locally and stays flipped on the way back. */
type Saved = { filters?: ListingFilters; opened?: string[] };
const SAVED_KEY = "hb.sold.v1";
// the header and every row share one grid, so the numbers sit under their
// headings; phones drop the List, $/sqft and Sold date columns
const GRID = "grid grid-cols-[3.5rem_minmax(0,1fr)_6rem_4rem] items-center gap-x-2 px-2 " +
  "sm:grid-cols-[3.5rem_minmax(0,1fr)_5.5rem_6rem_4rem_4rem_5.5rem]";

export default function Sold() {
  const search = useSearch({ strict: false }) as Record<string, string | undefined>;
  const navigate = useNavigate();
  const cities = useCities();
  const [saved] = useState(() => loadSaved<Saved>(SAVED_KEY));
  const [justViewed, setJustViewed] = useState<Set<string>>(() => new Set(saved.opened));
  const open = useOpenListing();
  // the row flips to viewed at once and stays so on the way back (docs/08 §2b)
  const noteOpened = (id: string) => {
    const next = new Set(justViewed).add(id);
    setJustViewed(next);
    save<Saved>(SAVED_KEY, { opened: [...next] });
  };
  const openDetail = (id: string, e?: { ctrlKey: boolean; metaKey: boolean }) => {
    noteOpened(id);
    open(id, e);
  };
  const summary = useQuery({ queryKey: ["market-summary"], queryFn: getMarketSummary });
  const band = summary.data?.target_band;

  // a `?zip=` arrival wins over the saved ZIP, once (see Listings)
  const [filters, setFilters] = useState<ListingFilters>({
    status: "sold",
    min_sold_price: undefined, // undefined = "use band default"; null = cleared
    max_sold_price: undefined,
    sort: "sold_date",
    ...saved.filters,
    ...(search.zip ? { zip: search.zip } : {}),
  });
  useEffect(() => {
    if (search.zip) void navigate({ to: "/sold", search: {}, replace: true });
  }, [search.zip, navigate]);
  useEffect(() => save<Saved>(SAVED_KEY, { filters }), [filters]);
  const effective: ListingFilters = {
    ...filters,
    min_sold_price: filters.min_sold_price === undefined ? band?.min : filters.min_sold_price,
    max_sold_price: filters.max_sold_price === undefined ? band?.max : filters.max_sold_price,
  };

  const listings = useQuery({
    queryKey: ["sold-listings", effective],
    queryFn: () => getListings(effective),
    enabled: !!band,
  });

  const [hovered, setHovered] = useState<string | null>(null);
  const items = listings.data?.items ?? [];
  const set = (patch: Partial<ListingFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const isViewed = (l: { id: string; viewed_at: string | null }) =>
    l.viewed_at !== null || justViewed.has(l.id);
  const unviewedCount = items.filter((l) => !isViewed(l)).length;

  return (
    <div className="flex flex-col gap-4 lg:h-full">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-2xl font-bold">Recently Sold</h1>
        <select value={filters.city ?? ""} onChange={(e) => set({ city: e.target.value || undefined })}
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="">all cities</option>
          {cities.map((c) => <option key={c}>{c}</option>)}
        </select>
        <input placeholder="ZIP" value={filters.zip ?? ""} size={5}
               onChange={(e) => set({ zip: e.target.value || undefined })}
               className="rounded border border-slate-300 px-2 py-1 text-sm" />
        <MoneyInput placeholder="min sold $" value={effective.min_sold_price ?? null}
                    onChange={(v) => set({ min_sold_price: v })}
                    className="w-32 rounded border border-slate-300 px-2 py-1 text-sm" />
        <MoneyInput placeholder="max sold $" value={effective.max_sold_price ?? null}
                    onChange={(v) => set({ max_sold_price: v })}
                    className="w-32 rounded border border-slate-300 px-2 py-1 text-sm" />
        {band && filters.min_sold_price === undefined && filters.max_sold_price === undefined && (
          <button onClick={() => set({ min_sold_price: null, max_sold_price: null })}
                  className="rounded-full bg-slate-900 px-2 py-0.5 text-xs text-white"
                  title="Filtering to your shopping band (by sold price) — click to clear">
            band {money(band.min)}–{money(band.max)} ✕
          </button>
        )}
        <select value={filters.sort} onChange={(e) => set({ sort: e.target.value })}
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="sold_date">newest sold</option>
          <option value="sold_price">sold price</option>
          <option value="cdom">days on market</option>
        </select>
        <span className="text-sm text-slate-400">{listings.data?.total ?? "…"} results</span>
        {unviewedCount > 0 && (
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700"
                title="Sold listings you haven't clicked into yet">
            {unviewedCount} not yet viewed
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-2">
        <div data-scroll-restoration-id="sold"
             className="max-h-[70dvh] overflow-auto rounded-lg border border-slate-200 bg-white lg:max-h-none">
          {items.length === 0 && !listings.isLoading && (
            <p className="p-6 text-sm text-slate-400">
              No sold homes match — run `hb pipeline listing-scan` or clear filters.
            </p>
          )}
          <div className="text-sm">
            <div className={`sticky top-0 border-b border-slate-100 bg-white py-2 text-xs font-medium uppercase text-slate-400 ${GRID}`}>
              <div className="col-span-2">Home</div>
              <div className="hidden text-right sm:block">List</div>
              <div className="text-right">Sold</div>
              <div className="hidden text-right sm:block">$/sqft</div>
              <div className="text-right">vs ask</div>
              <div className="hidden text-right sm:block">Sold date</div>
            </div>
            {items.map((l) => {
              const d = deltaVsAsk(l.sold_price, l.original_list_price);
              const viewed = isViewed(l);
              return (
                <div key={l.id}
                     onMouseEnter={() => setHovered(l.id)}
                     onMouseLeave={() => setHovered(null)}
                     className={`relative border-b border-slate-100 py-2 ${GRID} ${hovered === l.id ? "bg-slate-50" : ""}`}>
                  {l.photo_url
                    ? <img src={l.photo_url} alt="" loading="lazy"
                           className={`h-10 w-14 rounded object-cover ${viewed ? "opacity-50" : ""}`} />
                    : <div className="h-10 w-14 rounded bg-slate-100" />}
                  <div className="min-w-0">
                    <div className={`flex items-center gap-1.5 font-medium ${viewed ? "text-slate-400" : ""}`}>
                      {!viewed && (
                        <span className="h-2 w-2 shrink-0 rounded-full bg-blue-500"
                              title="Not viewed yet" />
                      )}
                      <ListingLink id={l.id} onOpen={noteOpened}>{l.address}</ListingLink>
                      {viewed && (
                        <span className="text-xs text-slate-300"
                              title={l.viewed_at ? `Viewed ${l.viewed_at.slice(0, 10)}` : "Viewed just now"}>
                          ✓
                        </span>
                      )}
                    </div>
                    <div className={`text-xs ${viewed ? "text-slate-400" : "text-slate-500"}`}>
                      {l.city} {l.zip} · {l.beds}bd/{l.baths}ba · {l.sqft?.toLocaleString()} sqft
                    </div>
                  </div>
                  <div className="hidden whitespace-nowrap text-right text-slate-500 sm:block">
                    {money(l.original_list_price)}
                  </div>
                  <div className="whitespace-nowrap text-right font-semibold">
                    {money(l.sold_price)}
                    {/* phones drop the Sold date column; the date rides here */}
                    <div className="text-xs font-normal text-slate-500 sm:hidden">{l.sold_date ?? "—"}</div>
                  </div>
                  <div className="hidden whitespace-nowrap text-right text-slate-500 sm:block">
                    {ppsf(l.sold_price, l.sqft)}
                  </div>
                  <div className={`whitespace-nowrap text-right ${
                    d == null ? "text-slate-400" : d > 0 ? "text-red-600" : d < 0 ? "text-emerald-600" : "text-slate-500"}`}>
                    {d == null ? "—" : `${d > 0 ? "+" : ""}${pct(d)}`}
                  </div>
                  <div className="hidden whitespace-nowrap text-right text-slate-500 sm:block">
                    {l.sold_date ?? "—"}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="h-72 lg:h-auto lg:min-h-[24rem]">
          <LazyMapView listings={items} hoveredId={hovered} onSelect={openDetail} />
        </div>
      </div>
    </div>
  );
}

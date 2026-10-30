import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  createTour,
  getMarketSummary,
  getOpenHouses,
  getSchedule,
  planRoute,
  putOrigin,
  reorderSchedule,
  scheduleOpenHouse,
  unscheduleOpenHouse,
  type ListingSummary,
  type OpenHouse,
  type OpenHouseFilters,
  type Origin,
} from "../api/client";
import LazyMapView from "../components/LazyMapView";
import ListingBadges from "../components/ListingBadges";
import { useCities } from "../lib/config";
import { clock, dayKey, dayParts, money, openHouseWindow, weekdayClock } from "../lib/format";
import MoneyInput from "../components/MoneyInput";

const SELECT = "rounded border border-slate-300 px-2 py-1 text-sm";
const CHIP = "rounded-full px-3 py-0.5 text-sm";
const LINK = "text-xs text-blue-600 hover:underline";

type Range = "weekend" | "today" | "week";
type DayGroup = { key: string; iso: string; items: OpenHouse[] };

/** Where the buyer was, kept per browser tab: a detail page opens in a new
 *  tab, and coming back (or the phone reloading a discarded tab) must land on
 *  the same filters, scroll position and last-opened home. */
type Saved = {
  range?: Range;
  filters?: OpenHouseFilters;
  hideViewed?: boolean;
  lastOpened?: string;
  opened?: string[];
  scrollTop?: number;
};
const SAVED_KEY = "hb.open-houses.v1";

function loadSaved(): Saved {
  try {
    return JSON.parse(sessionStorage.getItem(SAVED_KEY) ?? "{}") as Saved;
  } catch {
    return {};
  }
}

function save(patch: Saved) {
  try {
    sessionStorage.setItem(SAVED_KEY, JSON.stringify({ ...loadSaved(), ...patch }));
  } catch {
    // storage blocked (private window): the page just starts fresh next time
  }
}

/** undefined from/to = the server default: now through the end of the coming Sunday */
function rangeParams(range: Range): Pick<OpenHouseFilters, "from" | "to"> {
  if (range === "weekend") return {};
  const now = new Date();
  const end = new Date(now);
  if (range === "today") end.setHours(24, 0, 0, 0);
  else end.setDate(end.getDate() + 7);
  return { from: now.toISOString(), to: end.toISOString() };
}

const fullAddress = (l: ListingSummary) => `${l.address}, ${l.city ?? ""} ${l.zip}`.trim();

function directionsUrl(origin: Origin | null, l: ListingSummary): string {
  const params = new URLSearchParams({ api: "1", destination: fullAddress(l), travelmode: "driving" });
  if (origin) params.set("origin", origin.address);
  return `https://www.google.com/maps/dir/?${params}`;
}

/** group in list order; days themselves always run chronologically, so a
 *  distance/price sort keeps its order inside each day */
function groupByDay(items: OpenHouse[], tz: string | undefined): DayGroup[] {
  const out: DayGroup[] = [];
  const sorted = [...items].sort((a, b) =>
    dayKey(a.start_at, tz).localeCompare(dayKey(b.start_at, tz)));
  for (const oh of sorted) {
    const key = dayKey(oh.start_at, tz);
    if (out.at(-1)?.key !== key) out.push({ key, iso: oh.start_at, items: [] });
    out.at(-1)!.items.push(oh);
  }
  return out;
}

/** add/remove a slot on the schedule; both the list and the schedule refetch */
function useScheduleToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (oh: Pick<OpenHouse, "id" | "scheduled">) =>
      oh.scheduled ? unscheduleOpenHouse(oh.id) : scheduleOpenHouse(oh.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["open-houses"] });
      qc.invalidateQueries({ queryKey: ["open-house-schedule"] });
    },
  });
}

export default function OpenHouses() {
  const cities = useCities();
  const [saved] = useState(loadSaved);
  const [range, setRange] = useState<Range>(saved.range ?? "weekend");
  const summary = useQuery({ queryKey: ["market-summary"], queryFn: getMarketSummary });
  const band = summary.data?.target_band;
  // price: undefined = "use the shopping band" (as on Listings); null = cleared
  const [filters, setFilters] = useState<OpenHouseFilters>(saved.filters ?? { sort: "time" });
  const set = (patch: Partial<OpenHouseFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const [hideViewed, setHideViewed] = useState(saved.hideViewed ?? false);
  // homes opened from this tab: the detail page stamps viewed_at server-side,
  // but the list doesn't refetch on return, so flip them locally too
  const [opened, setOpened] = useState<Set<string>>(() => new Set(saved.opened));
  const [lastOpened, setLastOpened] = useState<string | null>(saved.lastOpened ?? null);
  useEffect(() => save({ range, filters, hideViewed }), [range, filters, hideViewed]);
  const isViewed = (l: ListingSummary) => l.viewed_at !== null || opened.has(l.id);
  // the "today"/"week" windows are anchored on the moment the range is picked,
  // so the query key stays stable instead of changing every render
  const effective = useMemo(() => ({
    ...filters,
    ...rangeParams(range),
    min_price: filters.min_price === undefined ? band?.min : filters.min_price,
    max_price: filters.max_price === undefined ? band?.max : filters.max_price,
  }), [filters, range, band]);

  const list = useQuery({
    queryKey: ["open-houses", effective],
    queryFn: () => getOpenHouses(effective),
    enabled: !summary.isLoading,
    // coming back from a detail tab must not re-sort the list under the buyer
    refetchOnWindowFocus: false,
  });
  const all = list.data?.items ?? [];
  // a home opened this visit stays put even with "hide viewed" on
  const items = useMemo(() => hideViewed
    ? all.filter((oh) => oh.listing.viewed_at === null || opened.has(oh.listing_id))
    : all, [all, hideViewed, opened]);
  const unviewedHomes = new Set(
    all.filter((oh) => !isViewed(oh.listing)).map((oh) => oh.listing_id)).size;
  const origin = list.data?.origin ?? null;
  const tz = list.data?.timezone;
  const groups = useMemo(() => groupByDay(items, tz), [items, tz]);
  const toggle = useScheduleToggle();

  // the schedule panel's query (shared cache): scheduled homes stay on the map
  // even when the list's range or filters leave them out, so hovering a
  // schedule entry always has a pin to light up
  const sched = useQuery({ queryKey: ["open-house-schedule"], queryFn: getSchedule });
  const scheduled = useMemo(
    () => (sched.data?.items ?? []).filter((i) => !i.cancelled && i.listing.status === "active"),
    [sched.data]);
  const earliest = (slots: OpenHouse[]) => {
    const m = new Map<string, OpenHouse>();
    for (const oh of slots) {
      const prev = m.get(oh.listing_id);
      if (!prev || oh.start_at < prev.start_at) m.set(oh.listing_id, oh);
    }
    return m;
  };
  const firstSlot = useMemo(() => earliest(items), [items]);
  const scheduledSlot = useMemo(() => earliest(scheduled), [scheduled]);

  // one pin per home, labelled with its first slot in the window
  const mapListings = useMemo(() => {
    const seen = new Map<string, ListingSummary>();
    for (const oh of [...items].sort((a, b) => a.start_at.localeCompare(b.start_at))) {
      if (!seen.has(oh.listing_id)) seen.set(oh.listing_id, oh.listing);
    }
    for (const oh of scheduled) {
      if (!seen.has(oh.listing_id)) seen.set(oh.listing_id, oh.listing);
    }
    return [...seen.values()];
  }, [items, scheduled]);
  const scheduledHomes = useMemo(() => new Set([
    ...items.filter((i) => i.scheduled).map((i) => i.listing_id),
    ...scheduled.map((i) => i.listing_id),
  ]), [items, scheduled]);
  const home = useMemo(() => (origin ? { lat: origin.lat, lon: origin.lon } : null),
    [origin?.lat, origin?.lon]);

  const [rowHovered, setRowHovered] = useState<string | null>(null);
  const [mapHovered, setMapHovered] = useState<string | null>(null);
  const [schedHovered, setSchedHovered] = useState<string | null>(null);
  const hovered = rowHovered ?? schedHovered ?? mapHovered;
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const dayRefs = useRef<Map<string, HTMLElement>>(new Map());
  const scroller = useRef<HTMLDivElement>(null);
  const scrollTop = useRef(saved.scrollTop ?? 0);
  const restored = useRef(false);

  /** bring a home's first row into view without moving a row already on screen */
  const scrollToHome = (listingId: string) => {
    const first = firstSlot.get(listingId);
    if (first) rowRefs.current.get(first.id)?.scrollIntoView({ block: "nearest" });
  };

  // put the list back where it was once the real rows exist (reload / discarded
  // tab). Not before the band has loaded: until then a cached result for the
  // band-less query can render and then empty out, clamping the scroll to 0.
  useEffect(() => {
    if (restored.current || summary.isLoading || !list.isSuccess || !scroller.current) return;
    restored.current = true;
    scroller.current.scrollTop = scrollTop.current;
  }, [summary.isLoading, list.isSuccess, list.data]);

  // leaving for a detail tab saves the position; returning re-shows the home
  // just opened in case the list moved meanwhile
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") save({ scrollTop: scrollTop.current });
      else if (lastOpened) scrollToHome(lastOpened);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      save({ scrollTop: scrollTop.current });
    };
  });

  const openDetail = (id: string) => {
    const next = new Set(opened).add(id);
    setOpened(next);
    setLastOpened(id);
    save({ opened: [...next], lastOpened: id, scrollTop: scrollTop.current });
    scrollToHome(id);  // a map-pin click brings its row into the list
    window.open(`/listings/${id}`, "_blank", "noopener,noreferrer");
  };
  const lastOpenedListing = lastOpened
    ? all.find((oh) => oh.listing_id === lastOpened)?.listing : undefined;

  return (
    <div className="flex flex-col gap-4 lg:h-full">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-2xl font-bold">Open Houses</h1>
        {([["weekend", "This weekend"], ["today", "Today"], ["week", "Next 7 days"]] as const)
          .map(([v, label]) => (
            <button key={v} onClick={() => setRange(v)}
                    className={`${CHIP} ${range === v
                      ? "bg-slate-900 text-white" : "border border-slate-300 text-slate-600 hover:bg-slate-100"}`}>
              {label}
            </button>
          ))}
        <select value={filters.max_miles ?? ""} className={SELECT}
                onChange={(e) => set({ max_miles: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">any distance</option>
          {[2, 5, 10, 15, 25].map((m) => <option key={m} value={m}>within {m} mi</option>)}
        </select>
        <select value={filters.city ?? ""} className={SELECT}
                onChange={(e) => set({ city: e.target.value || undefined })}>
          <option value="">all cities</option>
          {cities.map((c) => <option key={c}>{c}</option>)}
        </select>
        <MoneyInput placeholder="min $" value={effective.min_price ?? null} aria-label="Min price"
                    onChange={(v) => set({ min_price: v })}
                    className={`${SELECT} w-28`} />
        <MoneyInput placeholder="max $" value={effective.max_price ?? null} aria-label="Max price"
                    onChange={(v) => set({ max_price: v })}
                    className={`${SELECT} w-28`} />
        {band && filters.min_price === undefined && filters.max_price === undefined && (
          <button onClick={() => set({ min_price: null, max_price: null })}
                  className="rounded-full bg-slate-900 px-2 py-0.5 text-xs text-white"
                  title="Filtering to your shopping band — click to clear">
            band {money(band.min)}–{money(band.max)} ✕
          </button>
        )}
        <select value={filters.sort} className={SELECT}
                onChange={(e) => set({ sort: e.target.value as OpenHouseFilters["sort"] })}>
          <option value="time">soonest</option>
          <option value="distance">closest</option>
          <option value="price">price</option>
        </select>
        <label className="flex items-center gap-1 text-sm text-slate-600">
          <input type="checkbox" checked={hideViewed} onChange={(e) => setHideViewed(e.target.checked)} />
          hide viewed
        </label>
        <span className="text-sm text-slate-400">
          {list.data ? `${items.length} open house${items.length === 1 ? "" : "s"} · ${mapListings.length} homes` : "…"}
          {unviewedHomes > 0 && <span className="text-blue-600"> · {unviewedHomes} not yet viewed</span>}
        </span>
        {lastOpenedListing && (
          <button onClick={() => scrollToHome(lastOpenedListing.id)}
                  className="rounded-full bg-amber-100 px-3 py-0.5 text-sm text-amber-900 hover:bg-amber-200"
                  title="Scroll back to the home you opened last">
            ↩ last opened: {lastOpenedListing.address}
          </button>
        )}
      </div>

      <OriginBar origin={origin} />

      <div className="grid grid-cols-1 gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-2">
        <div className="flex min-h-0 flex-col gap-2">
          {groups.length > 1 && (
            <nav className="flex flex-wrap gap-2" aria-label="Jump to day">
              {groups.map((g) => {
                const d = dayParts(g.iso, tz);
                return (
                  <button key={g.key}
                          onClick={() => dayRefs.current.get(g.key)?.scrollIntoView({ block: "start" })}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-left hover:bg-slate-100">
                    <div className="text-sm font-semibold leading-tight">
                      {d.relative ?? d.short} <span className="font-normal text-slate-500">{d.date}</span>
                    </div>
                    <div className="text-xs text-slate-500">{g.items.length} open</div>
                  </button>
                );
              })}
            </nav>
          )}
          <div ref={scroller} onScroll={(e) => {
                 // load-time clamping must not overwrite the position being restored
                 if (restored.current) scrollTop.current = e.currentTarget.scrollTop;
               }}
               className="max-h-[70dvh] overflow-auto rounded-lg border border-slate-200 bg-white lg:max-h-none lg:min-h-0 lg:flex-1">
            {items.length === 0 && !list.isLoading && (
              <p className="p-6 text-sm text-slate-400">
                No open houses scheduled in this window — widen the range or filters, or run
                `hb pipeline open-houses`.
              </p>
            )}
            {groups.map((g) => (
              <section key={g.key} ref={(el) => {
                if (el) dayRefs.current.set(g.key, el);
                else dayRefs.current.delete(g.key);
              }}>
                <DayHeader iso={g.iso} tz={tz} count={g.items.length}
                           going={g.items.filter((i) => i.scheduled).length} />
                {g.items.map((oh) => (
                  <OpenHouseRow key={oh.id} oh={oh} origin={origin} tz={tz}
                                highlighted={hovered === oh.listing_id}
                                viewed={isViewed(oh.listing)}
                                lastOpened={lastOpened === oh.listing_id}
                                rowRef={(el) => {
                                  if (el) rowRefs.current.set(oh.id, el);
                                  else rowRefs.current.delete(oh.id);
                                }}
                                onHover={setRowHovered} onOpen={openDetail}
                                onToggle={() => toggle.mutate(oh)}
                                toggling={toggle.isPending && toggle.variables?.id === oh.id} />
                ))}
              </section>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-4 lg:min-h-[24rem]">
          <SchedulePanel onOpen={openDetail} onHover={setSchedHovered} hoveredId={hovered} />
          <div className="h-72 lg:h-auto lg:min-h-[20rem] lg:flex-1">
            <LazyMapView listings={mapListings} hoveredId={hovered} onSelect={openDetail}
                         onHover={setMapHovered} home={home}
                         pinLabel={(l) => {
                           const oh = firstSlot.get(l.id) ?? scheduledSlot.get(l.id);
                           const label = oh ? weekdayClock(oh.start_at, tz) : money(l.list_price);
                           return scheduledHomes.has(l.id) ? `✓ ${label}` : label;
                         }} />
          </div>
        </div>
      </div>
    </div>
  );
}

function DayHeader({ iso, tz, count, going }: {
  iso: string;
  tz: string | undefined;
  count: number;
  going: number;
}) {
  const d = dayParts(iso, tz);
  return (
    <h2 className="sticky top-0 z-10 flex items-baseline gap-2 bg-slate-800 px-3 py-2 text-white">
      <span className="text-lg font-bold">{d.weekday}</span>
      <span className="text-sm text-slate-300">{d.date}</span>
      {d.relative && (
        <span className="rounded-full bg-amber-400 px-2 py-0.5 text-xs font-semibold text-slate-900">
          {d.relative}
        </span>
      )}
      <span className="ml-auto text-xs text-slate-300">
        {count} open house{count === 1 ? "" : "s"}
        {going > 0 && <span className="text-emerald-300"> · {going} scheduled</span>}
      </span>
    </h2>
  );
}

function OriginBar({ origin }: { origin: Origin | null }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const save = useMutation({
    mutationFn: () => putOrigin(draft.trim()),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["open-houses"] });
      qc.invalidateQueries({ queryKey: ["open-house-route"] });
      qc.invalidateQueries({ queryKey: ["open-house-schedule"] });
    },
  });
  const open = editing || !origin;

  if (!open) {
    return (
      <div className="-mt-2 text-sm text-slate-500">
        Distances from <span className="font-medium text-slate-700">{origin!.address}</span>{" "}
        <button className={LINK} onClick={() => { setDraft(origin!.address); setEditing(true); }}>
          change
        </button>
      </div>
    );
  }
  return (
    <form className="-mt-2 flex flex-wrap items-center gap-2 text-sm"
          onSubmit={(e) => { e.preventDefault(); if (draft.trim()) save.mutate(); }}>
      <span className="text-slate-500">{origin ? "Home address" : "Set your home address to see distances and plan routes:"}</span>
      <input value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus={!!origin}
             placeholder="street, city, state ZIP" aria-label="Home address"
             className="w-80 rounded border border-slate-300 px-2 py-1 text-sm" />
      <button type="submit" disabled={save.isPending || !draft.trim()}
              className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50">
        {save.isPending ? "Finding…" : "Save"}
      </button>
      {origin && (
        <button type="button" className={LINK} onClick={() => setEditing(false)}>cancel</button>
      )}
      {save.isError && (
        <span className="text-red-600">
          {String(save.error).includes("422") ? "Couldn't find that address." : "Geocoder unavailable — try again."}
        </span>
      )}
    </form>
  );
}

function OpenHouseRow({ oh, origin, tz, highlighted, viewed, lastOpened, rowRef, onHover, onOpen,
                        onToggle, toggling }: {
  oh: OpenHouse;
  origin: Origin | null;
  tz: string | undefined;
  highlighted: boolean;
  /** the detail page has been opened (dimmed, ✓) */
  viewed: boolean;
  /** the home opened most recently from this tab (amber bar) */
  lastOpened: boolean;
  rowRef: (el: HTMLDivElement | null) => void;
  onHover: (listingId: string | null) => void;
  onOpen: (listingId: string) => void;
  onToggle: () => void;
  toggling: boolean;
}) {
  const l = oh.listing;
  const started = new Date(oh.start_at) <= new Date();
  const log = useMutation({
    mutationFn: () => createTour({ listing_id: l.id, kind: "open_house",
                                   toured_on: dayKey(oh.start_at, tz) }),
    onSuccess: () => onOpen(l.id),  // the tour log lives on the detail page
  });
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };

  return (
    <div ref={rowRef}
         onMouseEnter={() => onHover(l.id)} onMouseLeave={() => onHover(null)}
         onClick={() => onOpen(l.id)}
         className={`flex cursor-pointer gap-3 border-b border-slate-100 px-3 py-2 text-sm ${
           highlighted ? "bg-blue-50 shadow-[inset_3px_0_0_0_theme(colors.blue.600)]"
             : lastOpened ? "bg-amber-50 shadow-[inset_4px_0_0_0_theme(colors.amber.500)]"
             : oh.scheduled ? "bg-emerald-50/60 shadow-[inset_3px_0_0_0_theme(colors.emerald.500)]" : ""}`}>
      <div className="w-16 shrink-0 pt-0.5 sm:w-24">
        <div className="font-semibold text-emerald-700">
          {clock(oh.start_at, tz)}
        </div>
        <div className="text-xs text-slate-500">to {clock(oh.end_at, tz)}</div>
        {oh.methods.includes("virtual") && (
          <div className="text-xs text-violet-600">virtual</div>
        )}
      </div>
      {l.photo_url
        ? <img src={l.photo_url} alt="" loading="lazy"
               className={`hidden h-12 w-16 shrink-0 rounded object-cover sm:block ${viewed && !lastOpened ? "opacity-50" : ""}`} />
        : <div className="hidden h-12 w-16 shrink-0 rounded bg-slate-100 sm:block" />}
      <div className="min-w-0 flex-1">
        <div className={`flex items-center gap-1.5 font-medium ${viewed && !lastOpened ? "text-slate-500" : ""}`}>
          {!viewed && <span className="h-2 w-2 shrink-0 rounded-full bg-blue-500" title="Not viewed yet" />}
          <span className="truncate">{l.address}</span>
          {lastOpened ? (
            <span className="shrink-0 rounded-full bg-amber-400 px-2 py-0.5 text-xs font-semibold text-slate-900">
              last opened
            </span>
          ) : viewed && (
            <span className="shrink-0 text-xs font-normal text-slate-400"
                  title={l.viewed_at ? `Viewed ${l.viewed_at.slice(0, 10)}` : "Viewed just now"}>
              ✓ viewed
            </span>
          )}
        </div>
        <div className="text-xs text-slate-500">
          {l.city} {l.zip} · {l.beds}bd/{l.baths}ba · {l.sqft?.toLocaleString()} sqft
          {oh.distance_mi != null && ` · ${oh.distance_mi} mi`}
        </div>
        {oh.description && (
          <div className="truncate text-xs text-slate-400" title={oh.description}>{oh.description}</div>
        )}
        <div className="mt-1 flex flex-wrap gap-3">
          <a href={directionsUrl(origin, l)} target="_blank" rel="noreferrer"
             onClick={(e) => e.stopPropagation()} className={LINK}>
            Directions ↗
          </a>
          {oh.href && (
            <a href={oh.href} target="_blank" rel="noreferrer"
               onClick={(e) => e.stopPropagation()} className={LINK}>
              Event link ↗
            </a>
          )}
          {started && (
            <button onClick={stop(() => log.mutate())} className={LINK} disabled={log.isPending}
                    title="Start a tour-log entry for this visit">
              {log.isPending ? "Logging…" : "Log visit"}
            </button>
          )}
        </div>
      </div>
      <div className="max-w-[6rem] shrink-0 text-right sm:max-w-none">
        <div className="font-semibold">{money(l.list_price)}</div>
        <ListingBadges l={l} hideOpenHouse />
        <div className="mt-1">
          <button onClick={stop(onToggle)} disabled={toggling}
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium disabled:opacity-50 ${oh.scheduled
                    ? "bg-emerald-600 text-white hover:bg-emerald-700"
                    : "border border-slate-300 text-slate-600 hover:bg-slate-100"}`}
                  title={oh.scheduled ? "take off your schedule" : "you plan to go — add it to your schedule"}>
            {oh.scheduled ? "✓ Scheduled" : "+ Schedule"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** The open houses the buyer plans to go to, saved server-side, one tab per
 *  day; each day's stops are a driving route in the buyer's own order. */
function SchedulePanel({ onOpen, onHover, hoveredId }: {
  onOpen: (listingId: string) => void;
  /** hovering a stop lights up its map pin and list rows */
  onHover: (listingId: string | null) => void;
  hoveredId: string | null;
}) {
  const sched = useQuery({ queryKey: ["open-house-schedule"], queryFn: getSchedule });
  const items = sched.data?.items ?? [];
  const tz = sched.data?.timezone;
  const origin = sched.data?.origin ?? null;
  const days = useMemo(() => groupByDay(items, tz), [items, tz]);
  const [picked, setPicked] = useState<string | null>(null);
  const day = days.find((d) => d.key === picked) ?? days[0];

  return (
    <section className="max-h-[50dvh] overflow-auto rounded-lg border border-slate-200 bg-white p-4 lg:max-h-[55%]">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-bold">My schedule</h2>
        <span className="text-sm text-slate-500">
          {items.length > 0 &&
            `${items.length} open house${items.length === 1 ? "" : "s"} · ${days.length} day${days.length === 1 ? "" : "s"}`}
        </span>
      </div>
      {sched.isLoading && <p className="text-sm text-slate-400">Loading…</p>}
      {!sched.isLoading && items.length === 0 && (
        <p className="text-sm text-slate-500">
          Nothing scheduled yet. Hit <span className="font-medium">+ Schedule</span> on an open
          house you plan to go to — it's saved here, and each day gets a driving route.
        </p>
      )}
      {days.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {days.map((g) => {
            const d = dayParts(g.iso, tz);
            const active = g.key === day?.key;
            return (
              <button key={g.key} onClick={() => setPicked(g.key)}
                      className={`rounded-lg px-3 py-1 text-left ${active
                        ? "bg-slate-900 text-white" : "border border-slate-300 hover:bg-slate-100"}`}>
                <div className="text-sm font-semibold leading-tight">
                  {d.relative ?? d.weekday}{" "}
                  <span className={active ? "font-normal text-slate-300" : "font-normal text-slate-500"}>
                    {d.date}
                  </span>
                </div>
                <div className={`text-xs ${active ? "text-slate-300" : "text-slate-500"}`}>
                  {g.items.length} stop{g.items.length === 1 ? "" : "s"}
                </div>
              </button>
            );
          })}
        </div>
      )}
      {day && <DaySchedule key={day.key} items={day.items} origin={origin} tz={tz}
                           onOpen={onOpen} onHover={onHover} hoveredId={hoveredId} />}
    </section>
  );
}

type Schedule = Awaited<ReturnType<typeof getSchedule>>;
const ICON_BTN = "px-1 text-slate-300 hover:text-slate-700 disabled:invisible";

/** One day of the schedule in the buyer's own order: drag a stop (or use
 *  ▲ ▼) to rearrange it, Auto-order for the planner's suggestion. Every stop
 *  stays on the list; the drive into each one is shown, no visit times. */
function DaySchedule({ items, origin, tz, onOpen, onHover, hoveredId }: {
  items: OpenHouse[];
  origin: Origin | null;
  tz: string | undefined;
  onOpen: (listingId: string) => void;
  onHover: (listingId: string | null) => void;
  hoveredId: string | null;
}) {
  const qc = useQueryClient();
  const toggle = useScheduleToggle();
  const remove = (id: string) => toggle.mutate({ id, scheduled: true });
  const live = items.filter((i) => !i.cancelled && i.listing.status === "active");
  const off = items.filter((i) => !live.includes(i));
  const ids = live.map((i) => i.id);
  const [dwell, setDwell] = useState(20);
  const [dragging, setDragging] = useState<string | null>(null);

  // saved server-side; the cached schedule is reordered at once so the list
  // doesn't snap back while the PUT is in flight
  const reorder = useMutation({
    mutationFn: reorderSchedule,
    onMutate: async (order: string[]) => {
      await qc.cancelQueries({ queryKey: ["open-house-schedule"] });
      const prev = qc.getQueryData<Schedule>(["open-house-schedule"]);
      if (prev) {
        const byId = new Map(prev.items.map((i) => [i.id, i]));
        const moved = new Set(order);
        let k = 0;
        qc.setQueryData<Schedule>(["open-house-schedule"], {
          ...prev, items: prev.items.map((i) => (moved.has(i.id) ? byId.get(order[k++])! : i)),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["open-house-schedule"], ctx.prev);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["open-house-schedule"] }),
  });
  const move = (id: string, to: number) => {
    const order = ids.filter((x) => x !== id);
    order.splice(Math.max(0, Math.min(to, order.length)), 0, id);
    if (order.join() !== ids.join()) reorder.mutate(order);
  };
  const autoOrder = useMutation({
    mutationFn: () => planRoute({ open_house_ids: ids, optimize: true, dwell_min: dwell }),
    onSuccess: (plan) => reorder.mutate(plan.stops.map((s) => s.open_house_id)),
  });

  const route = useQuery({
    queryKey: ["open-house-route", ids],
    queryFn: () => planRoute({ open_house_ids: ids }),
    enabled: !!origin && ids.length > 0,
    placeholderData: (prev) => prev,
    retry: false,
  });
  // drive times only once the route matches the order on screen
  const p = route.data && route.data.stops.map((s) => s.open_house_id).join() === ids.join()
    ? route.data : undefined;
  const legs = new Map(p?.stops.map((s) => [s.open_house_id, s]));

  const removeBtn = (id: string) => (
    <button onClick={() => remove(id)} disabled={toggle.isPending}
            className="text-slate-300 hover:text-slate-600" aria-label="remove from schedule"
            title="remove from schedule">✕</button>
  );
  const hoverable = (oh: OpenHouse) => ({
    onMouseEnter: () => onHover(oh.listing_id),
    onMouseLeave: () => onHover(null),
  });

  return (
    <div className="text-sm">
      {!origin && (
        <p className="mb-2 text-xs text-amber-700">Set your home address above to see drive times.</p>
      )}
      {live.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {p && <span className="text-slate-500">~{Math.round(p.total_drive_min)} min driving</span>}
          {route.isError && <span className="text-red-600">Couldn't get drive times — try again.</span>}
          {live.length > 1 && origin && (
            <span className="ml-auto flex items-center gap-1 text-xs text-slate-500">
              <button onClick={() => autoOrder.mutate()}
                      disabled={autoOrder.isPending || reorder.isPending}
                      className="rounded border border-slate-300 px-2 py-0.5 text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                      title="Reorder to fit the most open-house windows with the least driving">
                {autoOrder.isPending ? "Ordering…" : "Auto-order"}
              </button>
              for
              <select value={dwell} onChange={(e) => setDwell(Number(e.target.value))}
                      className="rounded border border-slate-300 px-1 py-0.5 text-xs"
                      aria-label="Minutes at each stop">
                {[15, 20, 30, 45].map((m) => <option key={m} value={m}>{m} min</option>)}
              </select>
              stays
            </span>
          )}
        </div>
      )}

      <ol className="space-y-1">
        {live.map((oh, n) => {
          const leg = legs.get(oh.id);
          return (
            <li key={oh.id} {...hoverable(oh)}
                draggable onDragEnd={() => setDragging(null)}
                onDragStart={(e) => { e.dataTransfer.setData("text/plain", oh.id); setDragging(oh.id); }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); if (dragging) move(dragging, n); setDragging(null); }}
                className={`-mx-1 flex items-start gap-2 rounded px-1 py-0.5 ${
                  dragging === oh.id ? "opacity-40" : hoveredId === oh.listing_id ? "bg-blue-50" : ""}`}>
              <span className="cursor-grab select-none pt-0.5 text-slate-300" title="drag to reorder">⋮⋮</span>
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-xs text-white">
                {n + 1}
              </span>
              <div className="min-w-0 flex-1">
                <button onClick={() => onOpen(oh.listing_id)}
                        className="truncate text-left font-medium hover:underline">
                  {oh.listing.address}, {oh.listing.city}
                </button>
                <div className="text-xs text-slate-500">
                  open {openHouseWindow(oh.start_at, oh.end_at, tz)}
                  {leg?.drive_min != null && ` · ${Math.round(leg.drive_min)} min drive`}
                </div>
              </div>
              <button onClick={() => move(oh.id, n - 1)} disabled={n === 0 || reorder.isPending}
                      className={ICON_BTN} aria-label="move up" title="move up">▲</button>
              <button onClick={() => move(oh.id, n + 1)}
                      disabled={n === live.length - 1 || reorder.isPending}
                      className={ICON_BTN} aria-label="move down" title="move down">▼</button>
              {removeBtn(oh.id)}
            </li>
          );
        })}
      </ol>

      {off.length > 0 && (
        <div className="mt-2 space-y-1 text-xs text-red-700">
          {off.map((oh) => (
            <div key={oh.id} {...hoverable(oh)} className="flex gap-2">
              <span className="min-w-0 flex-1 truncate">
                {oh.listing.address} — {oh.cancelled
                  ? "open house cancelled (no longer listed)"
                  : `home is now ${oh.listing.status}`}
              </span>
              {removeBtn(oh.id)}
            </div>
          ))}
        </div>
      )}
      {p?.maps_url && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <a href={p.maps_url} target="_blank" rel="noreferrer"
             className="inline-block rounded bg-slate-900 px-3 py-1 text-sm text-white">
            Open route in Google Maps ↗
          </a>
          {live.length > p.maps_stops && (
            <span className="text-xs text-amber-700">
              Google Maps takes the first {p.maps_stops} stops; open the rest from stop {p.maps_stops + 1}.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

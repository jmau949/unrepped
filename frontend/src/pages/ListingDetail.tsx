import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useState } from "react";
import {
  calcAffordability,
  enrichProperty,
  getListing,
  getListingBrief,
  getOverbid,
  patchListing,
  patchProperty,
  patchTracked,
  scheduleOpenHouse,
  setWatching,
  track,
  unscheduleOpenHouse,
  untrack,
  TRACKER_STAGES,
  type AvmSnapshotOut,
  type ListingDetail as Detail,
  type ListingEpisode,
  type ListingEvent,
  type ListingOpenHouse,
  type PriceHistoryEntry,
} from "../api/client";
import AvmSpreadBar from "../components/AvmSpreadBar";
import CmaWorkbench from "../components/CmaWorkbench";
import ContactPanel from "../components/ContactPanel";
import HazardChips from "../components/HazardChips";
import ListingBadges from "../components/ListingBadges";
import OverbidHistogram from "../components/OverbidHistogram";
import PhotoGallery from "../components/PhotoGallery";
import PostureBadge, { SIGNAL_WHY, postureExplanation } from "../components/PostureBadge";
import SchoolRatings from "../components/SchoolRatings";
import TourPanel from "../components/TourPanel";
import VerdictCard from "../components/VerdictCard";
import type { PostureOut } from "../api/client";
import { money, openHouseWindow, pct } from "../lib/format";

const EVENT_LABEL: Record<string, string> = {
  new: "Listed", price_change: "Price change", pending: "Pending",
  back_on_market: "Back on market", delisted: "Delisted", relisted: "Relisted",
  sold: "Sold", status_change: "Status change",
};

export default function ListingDetail() {
  const { listingId } = useParams({ strict: false }) as { listingId: string };
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["listing", listingId],
    queryFn: () => getListing(listingId),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["listing", listingId] });

  const trackMut = useMutation({
    mutationFn: async (d: Detail) =>
      d.tracked_id ? untrack(d.tracked_id) : track(d.id),
    onSettled: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["tracked"] });
      qc.invalidateQueries({ queryKey: ["listings"] });
    },
  });
  const watchMut = useMutation({
    mutationFn: (d: Detail) => setWatching(d.property_id, !d.watching),
    onSettled: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });
  const stageMut = useMutation({
    mutationFn: (stage: string) => patchTracked(detail.data!.tracked_id!, { stage }),
    onSettled: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["tracked"] });
    },
  });
  const conditionMut = useMutation({
    mutationFn: (tag: string) => patchProperty(detail.data!.property_id, { condition_tag: tag }),
    onSettled: invalidate,
  });
  const offerMut = useMutation({
    mutationFn: (date: string) => patchListing(listingId, { offer_due_at: date }),
    onSettled: invalidate,
  });

  if (detail.isLoading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!detail.data) return <p className="text-sm text-red-500">Listing not found.</p>;
  const d = detail.data;

  const daysToOffer = d.offer_due_at
    ? Math.ceil((new Date(d.offer_due_at).getTime() - Date.now()) / 86_400_000)
    : null;

  return (
    <div className="space-y-6">
      {/* header */}
      <div className="flex flex-wrap gap-4">
        <PhotoGallery photos={d.photos} />
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-bold">{d.address}</h1>
          <p className="text-sm text-slate-500">
            {d.city} {d.zip} · {d.beds}bd/{d.baths}ba · {d.sqft?.toLocaleString()} sqft
            {d.property.lot_sqft ? ` · ${d.property.lot_sqft.toLocaleString()} lot` : ""}
            {d.property.year_built ? ` · built ${d.property.year_built}` : ""}
          </p>
          <p className="mt-2 flex flex-wrap items-baseline gap-x-2 text-xl font-semibold">
            {money(d.list_price)}
            {d.list_price != null && d.sqft ? (
              <span className="text-base font-semibold text-slate-600">
                ${Math.round(d.list_price / d.sqft).toLocaleString()}/sqft
              </span>
            ) : null}
            <PostureBadge posture={d.posture_detail} />
          </p>
          {d.predicted_sale && (
            <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-sm font-medium text-slate-500">Predicted sale price</span>
                <span className="text-2xl font-bold">{money(d.predicted_sale.point)}</span>
                <span className="text-sm text-slate-500">
                  likely {money(d.predicted_sale.low)} – {money(d.predicted_sale.high)}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                A model estimate of the <b>final sale price</b> — a backtest-tuned blend of the
                comparable-sales CMA (~20%) and the list-anchored overbid model (~80%: the list
                price × the recent sale-to-list ratio of similar nearby homes), pulled toward list
                when a home has lingered unsold. Not an appraisal — see the Overbid and CMA panels
                below for the underlying evidence.
              </p>
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ListingBadges l={d} hidePredicted />
            <HazardChips flags={d.hazard_flags} />
          </div>
          {d.property.sqft_mismatch && (
            <p className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700">
              ⚠ Listing sqft differs &gt;15% from assessor record — possible unpermitted addition.
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
            <TrackerControl
              trackedId={d.tracked_id}
              stage={d.tracked_stage}
              pending={trackMut.isPending}
              onToggle={() => trackMut.mutate(d)}
              onStage={(stage) => stageMut.mutate(stage)}
            />
            <WatchControl
              watching={d.watching}
              pending={watchMut.isPending}
              onToggle={() => watchMut.mutate(d)}
            />
            <label className="flex items-center gap-1">
              condition:
              <select value={d.property.condition_tag ?? ""}
                      onChange={(e) => conditionMut.mutate(e.target.value)}
                      className="rounded border border-slate-300 px-1 py-0.5">
                <option value="">unknown</option>
                <option value="renovated">renovated</option>
                <option value="dated">dated</option>
                <option value="fixer">fixer</option>
              </select>
            </label>
            <label className="flex items-center gap-1">
              offer date:
              <input type="date" value={d.offer_due_at ?? ""}
                     onChange={(e) => offerMut.mutate(e.target.value)}
                     className="rounded border border-slate-300 px-1 py-0.5" />
            </label>
            {daysToOffer != null && (
              <span className={`text-xs font-semibold ${daysToOffer <= 3 ? "text-red-600" : "text-slate-500"}`}>
                {daysToOffer >= 0 ? `${daysToOffer}d until offers` : "offer date passed"}
              </span>
            )}
            {d.url && <a href={d.url} target="_blank" rel="noreferrer"
                         className="text-xs text-blue-600 underline">source ↗</a>}
            <BriefButton listingId={d.id} />
          </div>
          {/* the ways in: every upcoming slot with the source's note, not just
              the badge's soonest window (docs/08 §3 1d) */}
          <OpenHousesBlock listingId={d.id} slots={d.open_houses} tz={d.timezone} />
        </div>
      </div>

      {/* who to call, before what it is worth — first contact is the step every
          other panel assumes has happened (docs/08 §3 1c) */}
      <ContactPanel listing={d} onChanged={invalidate} />

      {/* the agent's pitch, verbatim (docs/08 §3 1e) */}
      {d.remarks && (
        <section className={CARD}>
          <h2 className={H2}>Listing remarks</h2>
          <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">{d.remarks}</p>
          <p className="mt-2 text-xs text-slate-400">
            The listing agent's public remarks, as published on the source record — a sales
            pitch, not a disclosure. Condition and offer-date signals are parsed from this text.
          </p>
        </section>
      )}

      {/* timeline — Realtor price/sale history merged with app-observed episodes
          (Realtor drops withdrawn listings from its history; our scan doesn't) */}
      <TimelinePanel priceHistory={d.price_history} sqft={d.sqft}
                     yearBuilt={d.property.year_built}
                     events={d.events} listingGroup={d.listing_group} />

      {/* pricing posture (docs/06 §5.6) */}
      <PosturePanel posture={d.posture_detail} listPrice={d.list_price} />

      {/* overbid + AVM spread panels */}
      <div className="grid gap-4 lg:grid-cols-2">
        <OverbidPanel listingId={d.id}
                      rejectionWeight={d.predicted_sale?.rejection_weight ?? 0} />
        <AvmSpreadPanel
          propertyId={d.property_id}
          snapshots={d.avm_snapshots}
          onRefreshed={invalidate}
        />
      </div>

      {/* CMA workbench — embedded full-width */}
      <CmaWorkbench propertyId={d.property_id} />

      {/* affordability + schools */}
      <div className="grid gap-4 lg:grid-cols-2">
        <AffordabilityCard price={d.list_price} city={d.city} />
        <SchoolRatings schools={d.property.schools} />
      </div>

      {/* what I saw walking the house (docs/13) — before the offer helper,
          because observations should inform the recommendation, not follow it */}
      <TourPanel listingId={d.id} propertyId={d.property_id} />

      {/* offer helper */}
      <VerdictCard listingId={d.id} />
    </div>
  );
}

/** Add / remove this home on the kanban tracker (docs/08 §5), and set its stage
 * without a trip to that page — the detail page is where the decision to follow
 * a listing actually gets made. `saved` is the stage POST /api/tracker gives
 * a new row; the picker is how it becomes anything else. */
function TrackerControl({
  trackedId, stage, pending, onToggle, onStage,
}: {
  trackedId: string | null;
  stage: string | null;
  pending: boolean;
  onToggle: () => void;
  onStage: (stage: string) => void;
}) {
  if (!trackedId)
    return (
      <button
        type="button"
        onClick={onToggle}
        disabled={pending}
        className="flex items-center gap-1 rounded border border-amber-400 px-2 py-0.5 font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50"
      >
        <span className="text-slate-300">★</span>
        {pending ? "adding…" : "Add to tracker"}
      </button>
    );
  return (
    <span className="flex items-center gap-1.5 rounded border border-amber-300 bg-amber-50 px-2 py-0.5">
      <span className="text-amber-500">★</span>
      <label className="flex items-center gap-1">
        <span className="font-medium text-amber-800">Tracking</span>
        <select
          value={stage ?? "saved"}
          onChange={(e) => onStage(e.target.value)}
          className="rounded border border-amber-300 bg-white px-1 py-0.5"
        >
          {TRACKER_STAGES.map((s) => (
            <option key={s} value={s}>{s.replace("_", " ")}</option>
          ))}
        </select>
      </label>
      <Link to="/tracker" className="text-xs text-amber-800 underline">board ↗</Link>
      <button
        type="button"
        onClick={onToggle}
        disabled={pending}
        title="remove from tracker"
        className="text-xs text-amber-700 hover:text-red-600 disabled:opacity-50"
      >
        ✕
      </button>
    </span>
  );
}

/** Put the home on the Watchlist (docs/08 §5b) or take it off. Tracking or
 * touring a home already watches it; this is the way to follow a home's outcome
 * without either. */
function WatchControl({ watching, pending, onToggle }: {
  watching: boolean;
  pending: boolean;
  onToggle: () => void;
}) {
  if (!watching)
    return (
      <button
        type="button"
        onClick={onToggle}
        disabled={pending}
        title="Follow price cuts, pending and the sale price on the Watchlist"
        className="flex items-center gap-1 rounded border border-sky-400 px-2 py-0.5 font-medium text-sky-700 hover:bg-sky-50 disabled:opacity-50"
      >
        👁 {pending ? "adding…" : "Watch"}
      </button>
    );
  return (
    <span className="flex items-center gap-1.5 rounded border border-sky-300 bg-sky-50 px-2 py-0.5">
      <span className="font-medium text-sky-800">👁 Watching</span>
      <Link to="/watchlist" className="text-xs text-sky-800 underline">list ↗</Link>
      <button
        type="button"
        onClick={onToggle}
        disabled={pending}
        title="stop watching"
        className="text-xs text-sky-700 hover:text-red-600 disabled:opacity-50"
      >
        ✕
      </button>
    </span>
  );
}

/** Every open house still to come for this home, with the source's note in
 * full — the Open Houses page truncates it to a row, and the summary badge only
 * carries the soonest window. Schedule from here too: the toggle hits the same
 * endpoint as that page and refreshes both. */
function OpenHousesBlock({ listingId, slots, tz }: {
  listingId: string;
  slots: ListingOpenHouse[];
  tz: string;
}) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (oh: ListingOpenHouse) =>
      oh.scheduled ? unscheduleOpenHouse(oh.id) : scheduleOpenHouse(oh.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["listing", listingId] });
      qc.invalidateQueries({ queryKey: ["open-houses"] });
      qc.invalidateQueries({ queryKey: ["open-house-schedule"] });
    },
  });
  if (slots.length === 0) return null;
  return (
    <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50/50 px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-emerald-800">
          Open house{slots.length > 1 ? "s" : ""}
        </h2>
        <Link to="/open-houses" className="text-xs text-emerald-800 underline">all open houses ↗</Link>
      </div>
      <ul className="mt-1 space-y-1.5">
        {slots.map((oh) => (
          <li key={oh.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 text-sm">
            <span className={`shrink-0 font-semibold ${oh.cancelled ? "text-red-600 line-through" : "text-emerald-700"}`}>
              {openHouseWindow(oh.start_at, oh.end_at, tz)}
            </span>
            {oh.methods.includes("virtual") && (
              <span className="shrink-0 text-xs text-violet-600">virtual</span>
            )}
            {oh.cancelled && (
              <span className="shrink-0 text-xs font-medium text-red-600">
                cancelled — no longer listed by the source
              </span>
            )}
            {oh.description && (
              <span className="min-w-0 flex-1 basis-full text-slate-600 sm:basis-auto">{oh.description}</span>
            )}
            <span className="ml-auto flex shrink-0 items-center gap-2">
              {oh.href && (
                <a href={oh.href} target="_blank" rel="noreferrer"
                   className="text-xs text-blue-600 underline">Event link ↗</a>
              )}
              {!oh.cancelled && (
                <button type="button" onClick={() => toggle.mutate(oh)} disabled={toggle.isPending}
                        className={`rounded-full px-2.5 py-0.5 text-xs font-medium disabled:opacity-50 ${oh.scheduled
                          ? "bg-emerald-600 text-white hover:bg-emerald-700"
                          : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-100"}`}
                        title={oh.scheduled ? "take off your schedule" : "you plan to go — add it to your schedule"}>
                  {oh.scheduled ? "✓ Scheduled" : "+ Schedule"}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Copies the full deep-dive brief (docs/13 §9) for pasting into an AI chat.
 * Falls back to a download when the clipboard API is unavailable — it needs a
 * secure context, and this app is served over plain http on the LAN. */
function BriefButton({ listingId }: { listingId: string }) {
  const [state, setState] = useState<"idle" | "working" | "copied" | "failed">("idle");
  return (
    <button
      type="button"
      onClick={async () => {
        setState("working");
        try {
          const md = await getListingBrief(listingId);
          await navigator.clipboard.writeText(md);
          setState("copied");
        } catch {
          try {
            const md = await getListingBrief(listingId);
            const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
            const a = document.createElement("a");
            a.href = url;
            a.download = `brief-${listingId}.md`;
            a.click();
            URL.revokeObjectURL(url);
            setState("copied");
          } catch {
            setState("failed");
          }
        }
        setTimeout(() => setState("idle"), 2500);
      }}
      className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
    >
      {state === "working" ? "…" :
        state === "copied" ? "✓ brief copied" :
          state === "failed" ? "failed" : "Copy deep-dive brief"}
    </button>
  );
}

function AffordabilityCard({ price, city }: { price: number | null; city: string | null }) {
  const calc = useQuery({
    queryKey: ["afford", price, city],
    queryFn: () => calcAffordability({ price: price!, city: city ?? undefined }),
    enabled: !!price,
  });
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        At list price ({money(price)})
      </h2>
      {calc.data ? (
        <div className="text-sm">
          <p className="text-xl font-bold">{money(calc.data.piti, false)}/mo</p>
          <p className="text-xs text-slate-500">
            P&I {money(calc.data.breakdown.pi, false)} · tax {money(calc.data.breakdown.tax, false)} ·
            ins {money(calc.data.breakdown.insurance, false)}
            {calc.data.breakdown.pmi > 0 && <> · PMI {money(calc.data.breakdown.pmi, false)}</>}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Cash needed ≈ {money(calc.data.cash_needed)} (down + ~1.5% closing) at{" "}
            {calc.data.rate_used.toFixed(2)}%.
          </p>
          {!calc.data.reserves_ok && (
            <p className="mt-1 text-xs text-amber-700">⚠ Would leave under 6 months reserves.</p>
          )}
        </div>
      ) : (
        <p className="text-sm text-slate-400">…</p>
      )}
    </section>
  );
}

const CARD = "rounded-lg border border-slate-200 bg-white p-4";
const H2 = "mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500";

type TimelineRow = { date: string; label: string; price: number | null; old?: number | null };

// Realtor scrubs withdrawn listings from its property history (the standard
// pull-and-relist DOM reset), so rows the app observed itself must win any
// same-event collision with Realtor's sanitized version.
const rowKey = (label: string, date: string, price: number | null) => {
  const norm = label.toLowerCase().replace("relisted", "listed").replace("changed", "change");
  return norm === "price change" ? `${norm}|${price}` : `${norm}|${date}`;
};

function TimelinePanel({
  priceHistory, sqft, yearBuilt, events, listingGroup,
}: {
  priceHistory: PriceHistoryEntry[];
  sqft: number | null;
  yearBuilt: number | null;
  events: ListingEvent[];
  listingGroup: Detail["listing_group"];
}) {
  // App-observed rows: episode dates (accurate market dates from the scan) plus
  // observed price cuts. Episodes are ordered oldest-first by the API.
  const episodes: ListingEpisode[] = listingGroup?.episodes ?? [];
  const appRows: TimelineRow[] = [];
  episodes.forEach((ep, i) => {
    if (ep.list_date) appRows.push({ date: ep.list_date, label: i > 0 ? "Relisted" : "Listed", price: ep.original_list_price });
    if (ep.delist_date) appRows.push({ date: ep.delist_date, label: "Delisted", price: null });
    if (ep.pending_date) appRows.push({ date: ep.pending_date, label: "Pending", price: null });
    if (ep.sold_date) appRows.push({ date: ep.sold_date, label: "Sold", price: ep.sold_price });
  });
  events.forEach((e) => {
    if (e.event_type === "price_change" && e.new_value) {
      appRows.push({ date: e.observed_at.slice(0, 10), label: "Price change",
                     price: Number(e.new_value), old: e.old_value ? Number(e.old_value) : null });
    }
  });
  if (episodes.length === 0) {
    // no stitched group yet — fall back to raw observed events (dates lag reality)
    events.forEach((e) => {
      if (e.event_type === "price_change" || e.event_type === "relisted") return;
      appRows.push({ date: e.observed_at.slice(0, 10),
                     label: EVENT_LABEL[e.event_type] ?? e.event_type,
                     price: e.event_type === "new" && e.new_value ? Number(e.new_value) : null });
    });
  }

  const appKeys = new Set(appRows.map((r) => rowKey(r.label, r.date, r.price)));
  const rows: TimelineRow[] = priceHistory
    .filter((e) => !appKeys.has(rowKey(e.event, e.date, e.price)))
    .map((e) => ({ date: e.date, label: e.event, price: e.price }))
    .concat(appRows)
    .sort((a, b) => b.date.localeCompare(a.date));
  if (yearBuilt && !rows.some((r) => r.label === "Built")) {
    rows.push({ date: String(yearBuilt), label: "Built", price: null });
  }

  return (
    <section className={CARD}>
      <h2 className={H2}>Timeline</h2>
      <ol className="space-y-1 text-sm">
        {rows.map((e, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-x-3">
            <span className="w-24 shrink-0 text-slate-400">{e.date}</span>
            <span className="w-28 shrink-0 font-medium">{e.label}</span>
            {e.old != null && e.price != null ? (
              <span className={e.price < e.old ? "text-red-600" : "text-emerald-600"}>
                {money(e.old)} → {money(e.price)}
              </span>
            ) : (
              e.price != null && <span className="font-semibold">{money(e.price)}</span>
            )}
            {e.price != null && sqft ? (
              <span className="text-xs text-slate-400">${Math.round(e.price / sqft)}/sqft</span>
            ) : null}
          </li>
        ))}
        {rows.length === 0 && <li className="text-slate-400">No history yet.</li>}
      </ol>
      {listingGroup && listingGroup.episode_count > 1 && (
        <p className="mt-2 text-xs text-amber-700">
          {listingGroup.episode_count} listing episodes; true cumulative DOM{" "}
          {listingGroup.cumulative_dom} days.
        </p>
      )}
    </section>
  );
}

function PosturePanel({ posture, listPrice }: { posture: PostureOut | null; listPrice: number | null }) {
  if (!posture) return null;
  const adjusted = posture.adjusted;
  const pulledDown =
    adjusted && posture.unadjusted_point && adjusted.point < posture.unadjusted_point;
  const p = posture.p_below_list;
  const ex = posture.exposure;
  return (
    <section className={CARD}>
      <h2 className={H2}>Pricing posture — will this sell below asking?</h2>
      <div className="flex flex-wrap items-center gap-2">
        <PostureBadge posture={posture} />
        {posture.agreement === "diverge" && posture.spread_pct != null && (
          <span className="rounded bg-red-50 px-2 py-0.5 text-xs text-red-700">
            value estimates disagree by {(posture.spread_pct * 100).toFixed(0)}% — treat point
            values as soft
          </span>
        )}
      </div>

      {p != null && (
        <p className="mt-2 text-sm text-slate-700">
          <b>{Math.round(p * 100)}%</b> of homes with this exposure history sold below their
          asking price
          {posture.typical_sold_to_list != null && (
            <>
              ; the typical one closed at <b>{(posture.typical_sold_to_list * 100).toFixed(1)}%</b>{" "}
              of ask
            </>
          )}
          .
          {posture.withdrawal_share != null && (
            <>
              {" "}Separately, about <b>{Math.round(posture.withdrawal_share * 100)}%</b> of
              listings this far past the area median are withdrawn rather than sold — the
              percentage above counts only the ones that did sell.
            </>
          )}
        </p>
      )}
      <p className="mt-2 text-sm text-slate-600">{postureExplanation(posture)}</p>

      <h3 className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        The evidence
      </h3>
      {ex && (
        <p className="mt-1 text-xs text-slate-500">
          {ex.episode_count > 1 ? (
            <>
              Episode {ex.episode_count} of this campaign: <b>{ex.episode_days ?? "?"} days</b> at
              the current asking price, {ex.days ?? "?"} days cumulative across all episodes.
            </>
          ) : (
            <>
              <b>{ex.days ?? "?"} days</b> on the market at this asking price.
            </>
          )}{" "}
          The typical home in this area goes pending in{" "}
          <b>{ex.median_dom != null ? `${Math.round(ex.median_dom)} days` : "n/a"}</b>
          {ex.ratio != null && (
            <>
              , so this one is at <b>{ex.ratio.toFixed(1)}×</b> that
            </>
          )}
          .
        </p>
      )}
      <ul className="mt-2 space-y-2 text-xs">
        {posture.signals.map((s) => (
          <li key={s.id} className="flex gap-2">
            <span className={`w-10 shrink-0 text-right font-mono font-semibold ${
              s.points > 0 ? "text-red-600" : s.points < 0 ? "text-emerald-600" : "text-slate-400"
            }`}>
              {s.points > 0 ? "+" : ""}{s.points}
            </span>
            <span>
              <span className="text-slate-700">{s.label} — {s.detail}</span>
              {SIGNAL_WHY[s.id] && (
                <span className="mt-0.5 block text-slate-400">{SIGNAL_WHY[s.id]}</span>
              )}
            </span>
          </li>
        ))}
        {posture.signals.length === 0 && (
          <li className="text-slate-400">No evidence yet.</li>
        )}
      </ul>
      <p className="mt-2 text-[11px] text-slate-400">
        How to read the numbers: each row is a piece of evidence in log-odds. Red (positive)
        pushes toward "sells below asking", green (negative) toward "sells at or above". The rows
        add up to the probability at the top. The weights were fitted on this area's own sales
        history and are re-checked by every golden backtest, so "7 in 10" means that roughly 7 in
        10 past listings in that situation really did sell below asking.
      </p>

      <h3 className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Deliberately not counted
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        {posture.value_gap_pct != null ? (
          <>
            The asking price sits {Math.abs(posture.value_gap_pct * 100).toFixed(1)}%{" "}
            {posture.value_gap_pct < 0 ? "below" : "above"} the model's own value estimate.{" "}
          </>
        ) : null}
        Value estimates (the CMA, the overbid model, outside AVMs) are shown elsewhere on this
        page but do not feed this probability: once you know how long a home has sat, they do
        not predict whether it clears asking — lingering homes sold below asking at the same
        rate whether the estimate said they were cheap or dear. The market's behaviour is the
        harder evidence, so that is what this panel scores.
      </p>

      {pulledDown && adjusted && (
        <p className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-800">
          <b>Why the predicted sale price at the top is lower than the model's estimate:</b> the
          model on its own valued this home at {money(posture.unadjusted_point)}, but exposure
          past the area median says the market is not paying {money(listPrice)}, so the served
          value is pulled toward 98% of asking (weight {posture.rejection_weight.toFixed(2)} of
          1.00), giving <b>{money(adjusted.point)}</b>. Lingering homes here really do close near
          asking, so this is the number to anchor an offer on.
        </p>
      )}
    </section>
  );
}

function OverbidPanel({ listingId, rejectionWeight }: { listingId: string; rejectionWeight: number }) {
  const q = useQuery({ queryKey: ["overbid", listingId], queryFn: () => getOverbid(listingId) });
  const d = q.data;
  return (
    <section className={CARD}>
      <h2 className={H2}>Overbid model</h2>
      {q.isLoading && <p className="text-sm text-slate-400">…</p>}
      {d && d.n_comps === 0 && (
        <p className="text-sm text-slate-400">Not enough recent comps to model a sale range yet.</p>
      )}
      {d && d.n_comps > 0 && d.predicted && (
        <>
          <p className="text-sm">
            <span className="text-lg font-bold">
              {money(d.predicted.low)} – {money(d.predicted.high)}
            </span>{" "}
            <span className="text-slate-500">
              median {pct(d.p50, 1)} of {money(d.list_price)} list · n={d.n_comps} {d.basis}
            </span>
          </p>
          <div className="mt-2">
            <OverbidHistogram overbid={d} />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {d.basis === "stale" ? "Stale" : "Fresh"} distribution — {d.basis_reason} ·{" "}
            {d.window_days}-day window.
          </p>
          {rejectionWeight > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              Range shown is pre-adjustment — prolonged exposure pulls the served
              value lower (see Pricing posture).
            </p>
          )}
          {d.atypical_pricing && (
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
              ⚠ List price is atypical for this home — the ratio and the CMA disagree;
              see the posture panel for which evidence to trust.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function AvmSpreadPanel({
  propertyId,
  snapshots,
  onRefreshed,
}: {
  propertyId: string;
  snapshots: AvmSnapshotOut[];
  onRefreshed: () => void;
}) {
  const qc = useQueryClient();
  const [quota, setQuota] = useState<number | null>(null);
  const enrich = useMutation({
    mutationFn: () => enrichProperty(propertyId),
    onSuccess: (r) => {
      setQuota(r.rentcast_quota_remaining);
      qc.invalidateQueries({ queryKey: ["health"] });
      onRefreshed();
    },
  });
  return (
    <section className={CARD}>
      <div className="mb-2 flex items-center justify-between">
        <h2 className={H2 + " mb-0"}>AVM spread</h2>
        <button
          onClick={() => enrich.mutate()}
          disabled={enrich.isPending}
          className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
        >
          {enrich.isPending ? "Refreshing…" : "Refresh estimates"}
        </button>
      </div>
      <AvmSpreadBar snapshots={snapshots} />
      {quota != null && (
        <p className="mt-2 text-xs text-slate-400">RentCast quota remaining: {quota}</p>
      )}
      {enrich.isError && (
        <p className="mt-2 text-xs text-red-500">Enrich failed — check API keys / network.</p>
      )}
    </section>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { getTours, getTracked, patchTracked, TRACKER_STAGES, untrack, type TrackedItem } from "../api/client";
import MoneyInput from "../components/MoneyInput";
import { useConfig } from "../lib/config";
import { money, openHouseWindow } from "../lib/format";
import { statusLabel, statusPillClass } from "../lib/status";

function daysUntil(date: string | null): number | null {
  return date ? Math.ceil((new Date(date).getTime() - Date.now()) / 86_400_000) : null;
}

export default function Tracker() {
  const qc = useQueryClient();
  const tracked = useQuery({ queryKey: ["tracked"], queryFn: getTracked });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["tracked"] });
  // The disclosure checklist is the pack's (the forms differ by state); its keys
  // are the storage contract of tracked_listings.disclosure_checklist (docs/04).
  const config = useConfig();
  const checklist = config.data?.pack.tracker_checklist ?? [];

  // stage moves are drag-driven: optimistic so a dropped card never snaps back
  const stageMut = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) => patchTracked(id, { stage }),
    onMutate: async ({ id, stage }) => {
      await qc.cancelQueries({ queryKey: ["tracked"] });
      const prev = qc.getQueryData<TrackedItem[]>(["tracked"]);
      qc.setQueryData<TrackedItem[]>(["tracked"], (old) =>
        (old ?? []).map((t) => (t.id === id ? { ...t, stage } : t)),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(["tracked"], ctx.prev),
    onSettled: invalidate,
  });
  const patchMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof patchTracked>[1] }) =>
      patchTracked(id, body),
    onSettled: invalidate,
  });
  const untrackMut = useMutation({ mutationFn: untrack, onSettled: invalidate });

  const [overStage, setOverStage] = useState<string | null>(null);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const dragging = useRef(false);

  const items = tracked.data ?? [];
  const drawerItem = items.find((t) => t.id === drawerId) ?? null;

  return (
    <div>
      <h1 className="mb-4 text-2xl font-bold">Tracker</h1>
      {items.length === 0 && (
        <p className="text-sm text-slate-400">
          Nothing tracked yet — star listings from the Listings page, or use
          "Add to tracker" on any listing detail page.
        </p>
      )}
      <div className="flex gap-3 overflow-x-auto pb-4">
        {TRACKER_STAGES.map((stage) => {
          const cards = items.filter((t) => t.stage === stage);
          return (
            <div
              key={stage}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                setOverStage(stage);
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node)) setOverStage(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                setOverStage(null);
                const id = e.dataTransfer.getData("text/plain");
                const item = items.find((t) => t.id === id);
                if (id && item && item.stage !== stage) stageMut.mutate({ id, stage });
              }}
              className={`min-w-[16rem] flex-1 rounded-lg border bg-slate-100/60 p-2 ${
                overStage === stage ? "border-blue-400 ring-2 ring-blue-400" : "border-slate-200"
              }`}
            >
              <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {stage.replace("_", " ")} · {cards.length}
              </p>
              <div className="space-y-2">
                {cards.map((t) => {
                  const days = daysUntil(t.offer_due_at);
                  const sold = t.listing.status === "sold";
                  return (
                    <div
                      key={t.id}
                      draggable
                      onDragStart={(e) => {
                        dragging.current = true;
                        e.dataTransfer.setData("text/plain", t.id);
                        e.dataTransfer.effectAllowed = "move";
                        e.currentTarget.classList.add("opacity-50");
                      }}
                      onDragEnd={(e) => {
                        e.currentTarget.classList.remove("opacity-50");
                        // let the click handler see the flag before clearing it
                        setTimeout(() => (dragging.current = false), 0);
                      }}
                      onClick={() => !dragging.current && setDrawerId(t.id)}
                      className="cursor-grab rounded-lg border border-slate-200 bg-white p-2 text-sm shadow-sm hover:border-slate-300"
                    >
                      {/* not draggable itself, so dragging the photo moves the card */}
                      {t.listing.photo_url
                        ? <img src={t.listing.photo_url} alt="" loading="lazy" draggable={false}
                               className="mb-2 h-28 w-full rounded object-cover" />
                        : <div className="mb-2 h-28 w-full rounded bg-slate-100" />}
                      <Link
                        to="/listings/$listingId"
                        params={{ listingId: t.listing.id }}
                        onClick={(e) => e.stopPropagation()}
                        className="font-medium text-blue-700 hover:underline"
                      >
                        {t.listing.address}
                      </Link>
                      <p className="text-xs text-slate-500">
                        {money(t.listing.list_price)}
                        {sold ? (
                          <>
                            {" · "}sold {money(t.listing.sold_price)}
                            {t.listing.sold_date && ` on ${t.listing.sold_date}`}
                          </>
                        ) : (
                          t.overbid_point != null && <> · pred {money(t.overbid_point)}</>
                        )}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                        <span className={`rounded-full px-2 py-0.5 font-medium ${statusPillClass(t.listing.status)}`}>
                          {statusLabel(t.listing.status)}
                        </span>
                        {t.listing.cumulative_dom != null && (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
                            {t.listing.cumulative_dom}d CDOM
                          </span>
                        )}
                        {t.listing.next_open_house && (
                          <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-700"
                                title="next scheduled open house">
                            Open {openHouseWindow(t.listing.next_open_house.start_at,
                                                  t.listing.next_open_house.end_at)}
                          </span>
                        )}
                        {days != null && days >= 0 && (
                          <span
                            className={`font-semibold ${days < 3 ? "text-red-600" : "text-slate-500"}`}
                          >
                            offers in {days}d
                          </span>
                        )}
                        {t.my_max_bid != null && (
                          <span className="text-slate-600">max {money(t.my_max_bid)}</span>
                        )}
                      </div>
                      {(t.deal_id || ["won", "closing"].includes(t.stage)) && (
                        <Link
                          to="/closing"
                          onClick={(e) => e.stopPropagation()}
                          className="mt-1 inline-block text-xs font-medium text-emerald-700 hover:underline"
                        >
                          {t.deal_id ? "Closing tracker →" : "Start closing tracker →"}
                        </Link>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {drawerItem && (
        <>
          <div className="fixed inset-0 z-30 bg-black/20" onClick={() => setDrawerId(null)} />
          <div className="fixed inset-y-0 right-0 z-40 w-full max-w-96 space-y-4 overflow-y-auto bg-white p-4 shadow-xl">
            <div className="flex items-start justify-between gap-2">
              <div>
                <Link
                  to="/listings/$listingId"
                  params={{ listingId: drawerItem.listing.id }}
                  className="font-semibold text-blue-700 hover:underline"
                >
                  {drawerItem.listing.address}
                </Link>
                <p className="text-xs text-slate-500">
                  {drawerItem.listing.city} {drawerItem.listing.zip} ·{" "}
                  {money(drawerItem.listing.list_price)} · {drawerItem.stage}
                </p>
                <p className="mt-1 text-xs font-semibold text-slate-700">
                  <span className={`mr-1 rounded-full px-2 py-0.5 font-medium ${statusPillClass(drawerItem.listing.status)}`}>
                    {statusLabel(drawerItem.listing.status)}
                  </span>
                  {drawerItem.listing.status === "sold" && (
                    <>
                      {money(drawerItem.listing.sold_price)}
                      {drawerItem.listing.sold_date && ` on ${drawerItem.listing.sold_date}`}
                    </>
                  )}
                </p>
              </div>
              <button onClick={() => setDrawerId(null)} className="text-slate-400 hover:text-slate-700">
                ✕
              </button>
            </div>

            <TourSummary listingId={drawerItem.listing.id} />

            <label className="block text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                My max bid ($)
              </span>
              <MoneyInput
                value={drawerItem.my_max_bid}
                onSave={(v) =>
                  patchMut.mutate({ id: drawerItem.id, body: { my_max_bid: v as number } })
                }
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
              />
            </label>

            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Disclosure checklist
              </p>
              <div className="space-y-1.5 text-sm">
                {checklist.map(({ key, label, kind }) => {
                  const value = drawerItem.disclosure_checklist?.[key];
                  const save = (v: unknown) =>
                    patchMut.mutate({ id: drawerItem.id, body: { disclosure_checklist: { [key]: v } } });
                  return (
                    <label key={key} className="flex items-center justify-between gap-2">
                      <span className="text-slate-600">{label}</span>
                      {kind === "bool" ? (
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(e) => save(e.target.checked)}
                        />
                      ) : (
                        <input
                          type={kind === "number" ? "number" : "text"}
                          defaultValue={value == null ? "" : String(value)}
                          onBlur={(e) => {
                            const raw = e.target.value;
                            const v = raw === "" ? null : kind === "number" ? Number(raw) : raw;
                            if (v !== (value ?? null)) save(v);
                          }}
                          className="w-28 rounded border border-slate-300 px-1 py-0.5 text-right text-xs"
                        />
                      )}
                    </label>
                  );
                })}
              </div>
            </div>

            <label className="block text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Notes</span>
              <textarea
                defaultValue={drawerItem.notes ?? ""}
                rows={5}
                onBlur={(e) =>
                  e.target.value !== (drawerItem.notes ?? "") &&
                  patchMut.mutate({ id: drawerItem.id, body: { notes: e.target.value } })
                }
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </label>

            <button
              onClick={() => {
                untrackMut.mutate(drawerItem.id);
                setDrawerId(null);
              }}
              className="text-xs text-slate-400 hover:text-red-600"
            >
              remove from tracker
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/** Tour observations live on the detail page (docs/08 §3 item 6c); the drawer
 * shows enough to tell whether this home has actually been walked. */
function TourSummary({ listingId }: { listingId: string }) {
  const q = useQuery({ queryKey: ["tours", listingId], queryFn: () => getTours(listingId) });
  const tours = q.data ?? [];
  const latest = tours[0];
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Tours
      </p>
      {!latest ? (
        <p className="text-sm text-slate-400">
          Not toured yet — capture the visit in Field mode, or start one from the listing page.
        </p>
      ) : (
        <div className="text-sm text-slate-600">
          <p>
            {tours.length} visit{tours.length === 1 ? "" : "s"}, latest {latest.toured_on}
            {latest.gut_score != null && ` · gut ${latest.gut_score}/5`}
            {latest.verdict && ` · ${latest.verdict}`}
          </p>
          {latest.flags.length > 0 && (
            <p className="text-red-700">
              {latest.flags.length} flagged · deferred maintenance {money(latest.costs.low)}{" "}
              – {money(latest.costs.high)}
            </p>
          )}
          {latest.unanswered.length > 0 && (
            <p className="text-xs text-slate-400">
              {latest.unanswered.length} checklist items still unverified
            </p>
          )}
        </div>
      )}
      <Link
        to="/listings/$listingId"
        params={{ listingId }}
        className="text-xs text-blue-600 underline"
      >
        open tour log ↗
      </Link>
    </div>
  );
}

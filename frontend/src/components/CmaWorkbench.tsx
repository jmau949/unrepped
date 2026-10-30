import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, lazy, Suspense } from "react";
import {
  getCmaRun,
  getCmaRuns,
  patchCmaAdjustments,
  patchCmaComp,
  runCma,
  type CmaRun,
} from "../api/client";
import AdjustmentGrid from "./AdjustmentGrid";
import { money } from "../lib/format";

/** Same reasoning as LazyMapView: keep maplibre-gl out of the detail-page
 * chunk so the CMA numbers render before the map engine lands. */
const CmaMap = lazy(() => import("./CmaMap"));

const CONF: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-red-100 text-red-800",
};

/** Full CMA workbench, embedded in the listing detail page (docs/08 §3/§4).
 *  On mount it auto-loads the latest run, or creates the first one if none
 *  exists — so the estimate is present on first view (no separate page trip). */
export default function CmaWorkbench({ propertyId }: { propertyId: string }) {
  const qc = useQueryClient();
  const [run, setRun] = useState<CmaRun | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const init = useRef(false);

  const runs = useQuery({
    queryKey: ["cmaRuns", propertyId],
    queryFn: () => getCmaRuns(propertyId),
  });
  const refreshRuns = () => qc.invalidateQueries({ queryKey: ["cmaRuns", propertyId] });
  const onNewRun = (r: CmaRun) => {
    setRun(r);
    refreshRuns();
  };

  const runMut = useMutation({ mutationFn: () => runCma(propertyId), onSuccess: onNewRun });
  const loadMut = useMutation({ mutationFn: (id: string) => getCmaRun(id), onSuccess: setRun });
  const toggleMut = useMutation({
    mutationFn: (v: { saleId: string; included: boolean }) =>
      patchCmaComp(run!.id, v.saleId, v.included),
    onSuccess: onNewRun,
  });
  const overrideMut = useMutation({
    mutationFn: (v: { saleId: string; overrides: Record<string, number> }) =>
      patchCmaAdjustments(run!.id, v.saleId, v.overrides),
    onSuccess: onNewRun,
  });

  useEffect(() => {
    if (init.current || runs.isLoading) return;
    init.current = true;
    if (runs.data && runs.data.length > 0) loadMut.mutate(runs.data[0].id);
    else runMut.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.isLoading]);

  const busy =
    runMut.isPending || toggleMut.isPending || overrideMut.isPending || loadMut.isPending;

  const included = run?.comps.filter((c) => c.included) ?? [];
  const drawer = run?.comps.filter((c) => !c.included) ?? [];

  return (
    <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          CMA Workbench
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <select
            className="rounded border border-slate-300 px-2 py-1"
            value={run?.id ?? ""}
            onChange={(e) => loadMut.mutate(e.target.value)}
            disabled={busy || !runs.data?.length}
          >
            {runs.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.created_at.slice(0, 16).replace("T", " ")} · {money(r.estimate)} · {r.confidence}
              </option>
            ))}
          </select>
          <button
            onClick={() => runMut.mutate()}
            disabled={busy}
            className="rounded bg-slate-900 px-3 py-1 font-medium text-white disabled:opacity-50"
          >
            Re-run fresh
          </button>
        </div>
      </div>

      {run && run.estimate != null && (
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div>
            <div className="text-3xl font-bold">{money(run.estimate)}</div>
            <div className="text-sm text-slate-500">
              range {money(run.low)} – {money(run.high)}
            </div>
          </div>
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${CONF[run.confidence] ?? "bg-slate-100 text-slate-600"}`}
          >
            {run.confidence} confidence
          </span>
          {run.confidence_reasons?.length > 0 && (
            <span className="text-xs text-slate-500">{run.confidence_reasons.join(" · ")}</span>
          )}
          {run.index_source && (
            <span className="ml-auto text-xs text-slate-400">index: {run.index_source}</span>
          )}
        </div>
      )}

      {!run && <p className="text-sm text-slate-400">Building CMA…</p>}
      {run && run.estimate == null && (
        <p className="text-sm text-red-500">
          No usable comps for this property ({run.confidence_reasons?.join(", ")}).
        </p>
      )}

      {run && run.subject && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="h-[28rem] min-w-0">
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center rounded-lg border border-slate-200 bg-slate-50">
                  <span className="animate-pulse text-sm text-slate-400">Loading map…</span>
                </div>
              }
            >
              <CmaMap subject={run.subject} comps={included} hoveredSaleId={hovered} />
            </Suspense>
          </div>
          <div
            className="min-w-0 rounded-lg border border-slate-200 bg-white p-3"
            onMouseLeave={() => setHovered(null)}
          >
            <AdjustmentGrid
              comps={included}
              busy={busy}
              onToggle={(saleId, inc) => toggleMut.mutate({ saleId, included: inc })}
              onOverride={(saleId, overrides) => overrideMut.mutate({ saleId, overrides })}
            />
          </div>
        </div>
      )}

      {drawer.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Candidate drawer — next best excluded comps
          </h3>
          <ul className="divide-y divide-slate-100 text-sm">
            {drawer.map((c) => (
              <li key={c.sale_id} className="flex items-center gap-3 py-1"
                  onMouseEnter={() => setHovered(c.sale_id)} onMouseLeave={() => setHovered(null)}>
                <span className="flex-1 truncate" title={c.address}>{c.address}</span>
                <span className="text-slate-500">{money(c.sale_price)}</span>
                <span className="text-slate-400">{c.distance_mi ?? "—"} mi</span>
                <span className="text-slate-400">score {c.similarity_score.toFixed(3)}</span>
                <button
                  onClick={() => toggleMut.mutate({ saleId: c.sale_id, included: true })}
                  disabled={busy}
                  className="rounded bg-sky-600 px-2 py-0.5 text-xs font-medium text-white disabled:opacity-50"
                >
                  swap in
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

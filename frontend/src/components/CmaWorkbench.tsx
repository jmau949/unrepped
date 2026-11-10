import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, lazy, Suspense } from "react";
import {
  getCmaRun,
  getCmaRuns,
  patchCmaAdjustments,
  patchCmaComp,
  runCma,
  type CmaComp,
  type CmaRun,
  type CmaSubject,
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

/** The engine's confidence reasons (engine/cma.py `_confidence`), in words. */
const REASON: Record<string, string> = {
  "n<3": "fewer than 3 comps",
  "spread>10%": "comps disagree by over 10%",
  "gross adjustment>20%": "a comp needed adjustments over 20% of its price",
  unbracketed: "no comps on both sides of this home's size or price",
  "n>=5": "5+ comps",
  "spread<=6%": "agree within 6%",
  "adjustments<=15%": "small adjustments",
  "medium spread/coverage": "comps roughly agree",
  "no comps": "no similar sales nearby",
  "no included comps": "no comps selected",
  "no coordinates": "location unknown",
};
const reasonText = (reasons: string[] | undefined) =>
  (reasons ?? []).map((r) => REASON[r] ?? r).join(" · ");

/** One living-space adjustment from this run, spelled out. */
function WorkedExample({ subject, comps }: { subject: CmaSubject; comps: CmaComp[] }) {
  if (subject.sqft == null) return null;
  const withIdx = comps
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => c.sqft != null && c.sqft !== subject.sqft && c.adjustments.sqft !== 0);
  if (withIdx.length === 0) return null;
  // a subtraction when there is one — the minus sign is what needs explaining
  const minus = withIdx.filter(({ c }) => c.adjustments.sqft < 0);
  const { c, i } = (minus.length ? minus : withIdx).reduce((a, b) =>
    Math.abs(b.c.adjustments.sqft) > Math.abs(a.c.adjustments.sqft) ? b : a);
  const diff = c.sqft! - subject.sqft;
  return (
    <p className="mt-1">
      Example: #{i + 1} is {Math.abs(diff).toLocaleString()} sqft{" "}
      {diff > 0 ? "bigger" : "smaller"}, so <b>{money(Math.abs(c.adjustments.sqft), false)}</b>{" "}
      {c.adjustments.sqft < 0 ? "comes off" : "is added to"} its price (about $
      {Math.round(Math.abs(c.adjustments.sqft / diff)).toLocaleString()}/sqft).
    </p>
  );
}

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
    // a run stores the app's own estimate, which the listing payload carries to
    // the estimates panel and the predicted sale price
    qc.invalidateQueries({ queryKey: ["listing"] });
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
          Value from comparable sales
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="cma-version" className="text-xs text-slate-500">Version</label>
          <select
            id="cma-version"
            title="Each edit saves a new version"
            className="rounded border border-slate-300 px-2 py-1"
            value={run?.id ?? ""}
            onChange={(e) => loadMut.mutate(e.target.value)}
            disabled={busy || !runs.data?.length}
          >
            {runs.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.created_at.slice(0, 16).replace("T", " ")} · {money(r.estimate)} · {r.confidence} confidence
              </option>
            ))}
          </select>
          <button
            onClick={() => runMut.mutate()}
            disabled={busy}
            title="Drop your edits and re-pick comps"
            className="rounded bg-slate-900 px-3 py-1 font-medium text-white disabled:opacity-50"
          >
            Reset
          </button>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        A <b>CMA</b> (comparative market analysis): this home's value from recent nearby sales,
        called <b>comps</b>.
      </p>

      {run && run.estimate != null && (
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div>
            <div className="text-xs font-medium text-slate-500">Estimated value</div>
            <div className="text-3xl font-bold">{money(run.estimate)}</div>
            <div className="text-sm text-slate-500">
              likely {money(run.low)} – {money(run.high)}
            </div>
          </div>
          <div className="min-w-0 flex-1 basis-64 text-xs text-slate-500">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${CONF[run.confidence] ?? "bg-slate-100 text-slate-600"}`}
            >
              {run.confidence} confidence
            </span>{" "}
            {reasonText(run.confidence_reasons)}
          </div>
        </div>
      )}

      {run && run.subject && included.length > 0 && (
        <div className="rounded-lg border border-sky-100 bg-sky-50/60 p-3 text-xs leading-relaxed text-slate-600">
          <p>
            An <b>adjustment</b> is dollars added to or taken off a comp's sale price for one
            difference from this home: <b className="text-rose-700">−</b> the comp was better
            (bigger, more baths), <b className="text-emerald-700">+</b> this home is. The estimate
            is the middle of the adjusted prices, weighted toward closer matches.
          </p>
          <WorkedExample subject={run.subject} comps={included} />
          <p className="mt-1">Click an amount to change it; untick a comp to drop it.</p>
        </div>
      )}

      {!run && <p className="text-sm text-slate-400">Finding comps…</p>}
      {run && run.estimate == null && (
        <p className="text-sm text-red-500">
          No estimate: {reasonText(run.confidence_reasons) || "no usable comps"}.
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
              subject={run.subject}
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
            Other nearby sales
          </h3>
          <ul className="divide-y divide-slate-100 text-sm">
            {drawer.map((c) => (
              <li key={c.sale_id} className="flex items-center gap-3 py-1"
                  onMouseEnter={() => setHovered(c.sale_id)} onMouseLeave={() => setHovered(null)}>
                <span className="flex-1 truncate" title={c.address}>{c.address}</span>
                <span className="text-slate-500">{money(c.sale_price)}</span>
                <span className="text-slate-400">
                  {c.distance_mi != null ? `${c.distance_mi.toFixed(2)} mi` : "—"}
                </span>
                <button
                  onClick={() => toggleMut.mutate({ saleId: c.sale_id, included: true })}
                  disabled={busy}
                  className="rounded bg-sky-600 px-2 py-0.5 text-xs font-medium text-white disabled:opacity-50"
                >
                  use
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

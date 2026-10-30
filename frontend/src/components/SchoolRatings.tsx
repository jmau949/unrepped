import type { SchoolRating, SchoolSourceRating } from "../api/client";
import { useConfig } from "../lib/config";

const CARD = "rounded-lg border border-slate-200 bg-white p-4";
const H2 = "mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500";

const LEVEL_LABEL: Record<string, string> = {
  elementary: "Elementary",
  middle: "Middle",
  high: "High",
};

/** 1-10 rating badge: green (8-10), amber (5-7), red (1-4), slate when
 *  unrated. */
function ratingCls(rating: number | null): string {
  if (rating == null) return "bg-slate-100 text-slate-500";
  if (rating >= 8) return "bg-emerald-100 text-emerald-800";
  if (rating >= 5) return "bg-amber-100 text-amber-800";
  return "bg-red-100 text-red-800";
}

/** One labeled rating line: [badge] Source · native detail. */
function SourceLine({ r, source }: { r: SchoolSourceRating; source: string }) {
  const n = r.rating_10 != null ? Math.round(r.rating_10) : null;
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span
        className={`w-7 shrink-0 rounded px-1 py-0.5 text-center text-xs font-semibold ${ratingCls(n)}`}
      >
        {n ?? "—"}
      </span>
      <span className="font-medium text-slate-600">{source}</span>
      {r.label && <span className="text-slate-400">· {r.label}</span>}
    </span>
  );
}

/** Assigned elementary/middle/high for this home (docs/08 §3): matched by NCES
 *  district boundary (point-in-polygon), then nearest non-charter school within
 *  that district. Rows fall back to plain nearest (flagged) or ZIP when the
 *  boundary or coordinates are missing. Every rating is labeled with its
 *  source so the data provenance is visible without hovering; the sources and
 *  what their numbers mean are the pack's (config.pack.rating_sources). */
export default function SchoolRatings({ schools }: { schools: SchoolRating[] }) {
  const config = useConfig();
  const sources = config.data?.pack.rating_sources ?? [];
  const sourceLabel = (key: string) => sources.find((s) => s.key === key)?.label ?? key;
  const legend = sources.map((s) => `${s.label} = ${s.blurb}`).join(". ");
  const anyFallback = schools.some((s) => s.assignment && s.assignment !== "district");
  return (
    <section className={CARD}>
      <h2 className={H2}>Schools</h2>
      {schools.length === 0 ? (
        <p className="text-sm text-slate-400">No schools found for this listing.</p>
      ) : (
        <>
          <ul className="divide-y divide-slate-100 text-sm">
            {schools.map((s, i) => (
              <li key={i} className="py-2">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="min-w-0 truncate font-medium"
                    title={s.district ? `${s.name} — ${s.district}` : s.name}
                  >
                    {s.name}
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5 text-slate-400">
                    {s.assignment && s.assignment !== "district" && (
                      <span
                        className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500"
                        title={
                          s.assignment === "zip"
                            ? "no coordinates — top-rated school in this ZIP; may not be the assigned school"
                            : "no district boundary match — nearest school shown; may not be the assigned school"
                        }
                      >
                        {s.assignment}
                      </span>
                    )}
                    {LEVEL_LABEL[s.level] ?? s.level}
                    {s.distance_mi != null ? ` · ${s.distance_mi.toFixed(1)} mi` : ""}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
                  {s.ratings?.length ? (
                    s.ratings.map((r) => (
                      <SourceLine key={r.source} r={r} source={sourceLabel(r.source)} />
                    ))
                  ) : (
                    <span className="text-slate-400">— not yet rated</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-400">
            {anyFallback
              ? "Some rows are nearest-school fallbacks (marked) — verify with the district."
              : "Assigned by school-district boundary (NCES 2024–25), nearest in-district school per level."}
            {legend && ` ${legend}.`}
            {" Private schools not included."}
          </p>
        </>
      )}
    </section>
  );
}

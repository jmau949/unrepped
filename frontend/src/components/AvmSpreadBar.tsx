import type { AvmSnapshotOut } from "../api/client";
import { money } from "../lib/format";

const SOURCE_LABEL: Record<string, string> = {
  own_cma: "This app (comps)",
  realtor_estimate: "Realtor.com",
  rentcast: "RentCast",
  zestimate: "Zestimate",
};

/** Every value estimate for the home as a dot plot on one labelled dollar axis:
 *  a dot per estimate, a bar for the low–high range its source gives, and the
 *  asking price as a reference line (docs/06 §7, docs/08 §3 item 5). A plot is
 *  drawn only when there is something to compare a dot against. */
export default function AvmSpreadBar({
  snapshots, listPrice,
}: {
  snapshots: AvmSnapshotOut[];
  listPrice: number | null;
}) {
  const valued = snapshots.filter((s) => s.value > 0).sort((a, b) => b.value - a.value);
  if (valued.length === 0) {
    return <p className="text-sm text-slate-400">No estimates yet.</p>;
  }
  const values = valued.map((s) => s.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const spread = median ? (max - min) / median : 0;

  // thresholds mirror backend posture.AGREE_PCT / DIVERGE_PCT (0.07 / 0.15) —
  // keep in sync so this verdict and the posture agreement never contradict
  const verdict =
    spread > 0.15
      ? { cls: "text-red-700", text: "Big gap — trust the comparable sales over any one number." }
      : spread < 0.07
        ? { cls: "text-emerald-700", text: "They agree." }
        : { cls: "text-slate-600", text: "Moderate gap — treat each as approximate." };

  const hasRange = (s: AvmSnapshotOut) =>
    s.low != null && s.high != null && s.low > 0 && s.high > s.low;
  // one axis for every row: all estimates, their ranges and the asking price,
  // padded so nothing sits on the edge
  const points = [
    ...values,
    ...valued.filter(hasRange).flatMap((s) => [s.low!, s.high!]),
    ...(listPrice ? [listPrice] : []),
  ];
  const comparable = points.length > 1;
  const lo0 = Math.min(...points);
  const hi0 = Math.max(...points);
  const pad = (hi0 - lo0) * 0.08;
  const lo = lo0 - pad;
  const hi = hi0 + pad;
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => lo + t * (hi - lo));
  const anyRange = valued.some(hasRange);

  return (
    <div>
      {comparable ? (
        <div className="text-xs">
          {valued.map((s) => {
            const own = s.source === "own_cma";
            return (
              <div key={s.source} className="flex items-center gap-2">
                <span className={`w-36 shrink-0 truncate ${own ? "font-semibold text-slate-800" : "text-slate-600"}`}>
                  {SOURCE_LABEL[s.source] ?? s.source}
                </span>
                <div className="relative h-7 min-w-0 flex-1 border-l border-r border-slate-200">
                  {ticks.slice(1, -1).map((t) => (
                    <div key={t} className="absolute inset-y-0 w-px bg-slate-100"
                         style={{ left: `${pos(t)}%` }} />
                  ))}
                  {listPrice ? (
                    <div className="absolute inset-y-0 border-l border-dashed border-slate-500"
                         style={{ left: `${pos(listPrice)}%` }} />
                  ) : null}
                  {hasRange(s) && (
                    <div
                      className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded ${own ? "bg-slate-400" : "bg-sky-200"}`}
                      style={{ left: `${pos(s.low!)}%`, width: `${pos(s.high!) - pos(s.low!)}%` }}
                      title={`${money(s.low)} – ${money(s.high)}`}
                    />
                  )}
                  <div
                    className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 ${
                      own ? "border-slate-900 bg-slate-900" : "border-sky-600 bg-white"
                    }`}
                    style={{ left: `${pos(s.value)}%` }}
                    title={money(s.value)}
                  />
                </div>
                <span className="w-14 shrink-0 text-right font-semibold tabular-nums text-slate-900">
                  {money(s.value)}
                </span>
              </div>
            );
          })}
          {/* the dollar axis all rows share */}
          <div className="flex gap-2">
            <span className="w-36 shrink-0" />
            <div className="relative h-4 min-w-0 flex-1 border-t border-slate-300 text-[10px] text-slate-400">
              {ticks.map((t, i) => (
                <span key={t} className="absolute top-0.5 whitespace-nowrap tabular-nums"
                      style={i === 0 ? { left: 0 } : i === ticks.length - 1 ? { right: 0 }
                        : { left: `${pos(t)}%`, transform: "translateX(-50%)" }}>
                  {money(t)}
                </span>
              ))}
            </div>
            <span className="w-14 shrink-0" />
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            ● estimate{anyRange ? " · bar = its low–high range" : ""}
            {listPrice ? ` · dashed line = asking ${money(listPrice)}` : ""}
          </p>
        </div>
      ) : (
        <p className="text-sm">
          <span className="text-slate-600">{SOURCE_LABEL[valued[0].source] ?? valued[0].source}</span>{" "}
          <b>{money(valued[0].value)}</b>
        </p>
      )}
      {valued.length > 1 ? (
        <p className="mt-2 text-xs text-slate-700">
          <b>Spread {money(max - min)} ({(spread * 100).toFixed(1)}%).</b>{" "}
          <span className={verdict.cls}>{verdict.text}</span>
        </p>
      ) : (
        <p className="mt-2 text-xs text-slate-500">
          Only one estimate — no spread to measure.
        </p>
      )}
    </div>
  );
}

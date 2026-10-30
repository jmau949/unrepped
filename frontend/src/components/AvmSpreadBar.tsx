import type { AvmSnapshotOut } from "../api/client";
import { money } from "../lib/format";

const SOURCE_LABEL: Record<string, string> = {
  own_cma: "Our CMA",
  realtor_estimate: "Realtor.com",
  rentcast: "RentCast",
  zestimate: "Zestimate",
};

/** Multi-AVM spread on one axis with a verdict line (docs/06 §7, docs/08 §3 item 5). */
export default function AvmSpreadBar({ snapshots }: { snapshots: AvmSnapshotOut[] }) {
  const valued = snapshots.filter((s) => s.value > 0);
  if (valued.length === 0) {
    return <p className="text-sm text-slate-400">No estimates yet — refresh to fetch AVMs.</p>;
  }
  const values = valued.map((s) => s.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const spread = median ? (max - min) / median : 0;
  const span = max - min || 1;
  const pos = (v: number) => (valued.length === 1 ? 50 : ((v - min) / span) * 100);

  // thresholds mirror backend posture.AGREE_PCT / DIVERGE_PCT (0.07 / 0.15) —
  // keep in sync so this verdict and the posture agreement never contradict
  const verdict =
    spread > 0.15
      ? { text: "High uncertainty — comp quality matters more than any single number.", cls: "text-red-700" }
      : spread < 0.07
        ? { text: "Estimates agree.", cls: "text-emerald-700" }
        : { text: "Moderate spread across sources.", cls: "text-slate-600" };

  return (
    <div>
      <div className="relative mt-6 mb-8 h-1 rounded bg-slate-200">
        {valued.map((s) => {
          const own = s.source === "own_cma";
          return (
            <div key={s.source} className="absolute -translate-x-1/2" style={{ left: `${pos(s.value)}%` }}>
              <div className={`mx-auto h-3 w-3 rounded-full border-2 ${own ? "border-slate-900 bg-slate-900" : "border-sky-600 bg-white"}`} />
              <div className="mt-1 whitespace-nowrap text-center text-[10px] leading-tight text-slate-600">
                <div className={own ? "font-semibold" : ""}>{SOURCE_LABEL[s.source] ?? s.source}</div>
                <div>{money(s.value)}</div>
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-xs">
        <span className="font-medium">Spread {(spread * 100).toFixed(1)}%</span>{" "}
        <span className={verdict.cls}>· {verdict.text}</span>
      </p>
    </div>
  );
}

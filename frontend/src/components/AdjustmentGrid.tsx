import { useState } from "react";
import type { CmaComp } from "../api/client";
import { money } from "../lib/format";

interface Props {
  comps: CmaComp[];
  onToggle: (saleId: string, included: boolean) => void;
  onOverride: (saleId: string, overrides: Record<string, number>) => void;
  busy?: boolean;
}

const ADJ_ROWS: { key: keyof CmaComp["adjustments"]; label: string }[] = [
  { key: "time", label: "Time adj" },
  { key: "sqft", label: "Sqft adj" },
  { key: "baths", label: "Baths adj" },
  { key: "lot", label: "Lot adj" },
  { key: "condition", label: "Condition adj" },
];

function EditableCell({
  value,
  onCommit,
  disabled,
}: {
  value: number;
  onCommit: (v: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string>(String(value));
  // keep the draft in sync when the underlying value changes (recompute)
  const [seen, setSeen] = useState(value);
  if (seen !== value) {
    setSeen(value);
    setDraft(String(value));
  }
  const commit = () => {
    const n = Math.round(Number(draft));
    if (!Number.isNaN(n) && n !== value) onCommit(n);
    else setDraft(String(value));
  };
  return (
    <input
      className="w-24 rounded border border-slate-200 px-1 py-0.5 text-right text-xs tabular-nums focus:border-sky-500 focus:outline-none disabled:opacity-50"
      value={draft}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

/** One editable column per comp (docs/08 §4). Cells for the five adjustment
 *  line items round-trip through PATCH /cma/runs/:id/adjustments; the include
 *  toggle through PATCH /cma/runs/:id/comps. */
export default function AdjustmentGrid({ comps, onToggle, onOverride, busy }: Props) {
  if (comps.length === 0) {
    return <p className="text-sm text-slate-400">No comps in this run.</p>;
  }
  const cell = "border-b border-slate-100 px-2 py-1 text-right tabular-nums";
  const rowLabel = "sticky left-0 bg-white px-2 py-1 text-left font-medium text-slate-500";

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className={`${rowLabel} align-bottom`}>Comp</th>
            {comps.map((c, i) => (
              <th key={c.sale_id} className="border-b border-slate-200 px-2 py-1 text-right align-bottom">
                <div className="font-semibold text-slate-700">#{i + 1}</div>
                <div className="max-w-[7rem] truncate font-normal text-slate-500" title={c.address}>
                  {c.address}
                </div>
                <div className="font-normal text-slate-400">{c.distance_mi ?? "—"} mi</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className={rowLabel}>Sale price</td>
            {comps.map((c) => <td key={c.sale_id} className={cell}>{money(c.sale_price)}</td>)}
          </tr>
          <tr>
            <td className={rowLabel}>Sold / sqft / bd</td>
            {comps.map((c) => (
              <td key={c.sale_id} className={`${cell} text-slate-500`}>
                {c.sale_date} · {c.sqft ?? "—"} · {c.beds ?? "—"}bd
              </td>
            ))}
          </tr>
          {ADJ_ROWS.map((r) => (
            <tr key={r.key}>
              <td className={rowLabel}>{r.label}</td>
              {comps.map((c) => (
                <td key={c.sale_id} className={cell}>
                  <EditableCell
                    value={c.adjustments[r.key]}
                    disabled={busy}
                    onCommit={(v) => onOverride(c.sale_id, { [r.key]: v })}
                  />
                </td>
              ))}
            </tr>
          ))}
          <tr>
            <td className={`${rowLabel} font-semibold text-slate-700`}>Adjusted price</td>
            {comps.map((c) => (
              <td key={c.sale_id} className={`${cell} font-semibold text-slate-900`}>
                {money(c.adjusted_price)}
              </td>
            ))}
          </tr>
          <tr>
            <td className={rowLabel}>Similarity</td>
            {comps.map((c) => (
              <td key={c.sale_id} className={`${cell} text-slate-500`}>
                {c.similarity_score.toFixed(3)}
              </td>
            ))}
          </tr>
          <tr>
            <td className={rowLabel}>Include</td>
            {comps.map((c) => (
              <td key={c.sale_id} className={cell}>
                <input
                  type="checkbox"
                  checked={c.included}
                  disabled={busy}
                  onChange={(e) => onToggle(c.sale_id, e.target.checked)}
                  className="h-4 w-4 cursor-pointer accent-sky-600"
                />
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

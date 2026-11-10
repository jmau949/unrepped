import { useState, type ReactNode } from "react";
import type { CmaComp, CmaSubject } from "../api/client";
import { money, signedMoney } from "../lib/format";

interface Props {
  subject: CmaSubject;
  comps: CmaComp[];
  onToggle: (saleId: string, included: boolean) => void;
  onOverride: (saleId: string, overrides: Record<string, number>) => void;
  busy?: boolean;
}

type AdjKey = keyof CmaComp["adjustments"];

const n0 = (v: number) => Math.round(v).toLocaleString();

/** What the comp is, next to how it differs from the subject — the fact each
 *  dollar adjustment stands for. Describes the homes, never the amount, so it
 *  stays true when the buyer types their own number over the computed one. */
function difference(key: AdjKey, c: CmaComp, s: CmaSubject): string {
  switch (key) {
    case "time": {
      const f = c.time_adj_factor;
      if (f == null || Math.abs(f - 1) < 0.0005) return "prices flat";
      return `prices ${f > 1 ? "up" : "down"} ${(Math.abs(f - 1) * 100).toFixed(1)}%`;
    }
    case "sqft": {
      if (c.sqft == null || s.sqft == null) return "size unknown";
      const d = c.sqft - s.sqft;
      if (d === 0) return `${n0(c.sqft)} sqft · same size`;
      return `${n0(c.sqft)} sqft · ${n0(Math.abs(d))} ${d > 0 ? "bigger" : "smaller"}`;
    }
    case "baths": {
      if (c.baths == null || s.baths == null) return "baths unknown";
      const d = c.baths - s.baths;
      if (d === 0) return `${c.baths} · same`;
      return `${c.baths} · ${Math.abs(d)} ${d > 0 ? "more" : "fewer"}`;
    }
    case "lot": {
      if (c.lot_sqft == null || s.lot_sqft == null) return "lot size unknown";
      const d = c.lot_sqft - s.lot_sqft;
      if (d === 0) return `${n0(c.lot_sqft)} sqft · same`;
      return `${n0(c.lot_sqft)} sqft · ${n0(Math.abs(d))} ${d > 0 ? "bigger" : "smaller"}`;
    }
    case "condition": {
      if (!c.condition_tag || !s.condition_tag) return c.condition_tag ?? "not known";
      return c.condition_tag === s.condition_tag ? `${c.condition_tag} · same` : c.condition_tag;
    }
  }
}

function rows(s: CmaSubject): { key: AdjKey; label: string; hint: string }[] {
  return [
    { key: "time", label: "Market since sale", hint: "price trend since it sold" },
    { key: "sqft", label: "Living space",
      hint: s.sqft != null ? `this home: ${n0(s.sqft)} sqft` : "this home: unknown" },
    { key: "baths", label: "Bathrooms",
      hint: s.baths != null ? `this home: ${s.baths}` : "this home: unknown" },
    { key: "lot", label: "Lot size",
      hint: s.lot_sqft != null ? `this home: ${n0(s.lot_sqft)} sqft` : "this home: unknown" },
    { key: "condition", label: "Condition",
      hint: s.condition_tag
        ? `this home: ${s.condition_tag}`
        : "this home: not set (top of page)" },
  ];
}

/** A dollar adjustment that reads as money (+$15k / −$149k) and turns into a
 *  number box when clicked. */
function EditableAmount({
  value, onCommit, disabled,
}: {
  value: number;
  onCommit: (v: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  if (draft == null) {
    const tone = value > 0 ? "text-emerald-700" : value < 0 ? "text-rose-700" : "text-slate-400";
    return (
      <button
        type="button"
        disabled={disabled}
        onClick={() => setDraft(String(value))}
        title={`${signedMoney(value, false)} — click to type your own amount`}
        className={`rounded px-1 font-semibold tabular-nums underline decoration-slate-300 decoration-dotted underline-offset-2 hover:bg-slate-100 disabled:opacity-50 ${tone}`}
      >
        {value === 0 ? "no change" : signedMoney(value)}
      </button>
    );
  }
  const commit = () => {
    const n = Math.round(Number(draft));
    if (draft.trim() !== "" && !Number.isNaN(n) && n !== value) onCommit(n);
    setDraft(null);
  };
  return (
    <input
      autoFocus
      inputMode="numeric"
      className="w-24 rounded border border-sky-500 px-1 py-0.5 text-right text-xs tabular-nums focus:outline-none"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setDraft(null);
      }}
    />
  );
}

function RowLabel({ label, hint, strong }: { label: string; hint?: ReactNode; strong?: boolean }) {
  return (
    <td className="sticky left-0 z-10 w-40 min-w-40 bg-white px-2 py-1.5 text-left align-top">
      <div className={strong ? "font-semibold text-slate-800" : "font-medium text-slate-600"}>
        {label}
      </div>
      {hint && <div className="text-[11px] font-normal leading-tight text-slate-400">{hint}</div>}
    </td>
  );
}

/** One column per comparable sale (docs/08 §4): what it sold for, a dollar
 *  adjustment for each way it differs from this home, and the adjusted price.
 *  The five adjustments round-trip through PATCH /cma/runs/:id/adjustments;
 *  the "use this sale" tick through PATCH /cma/runs/:id/comps. */
export default function AdjustmentGrid({ subject, comps, onToggle, onOverride, busy }: Props) {
  if (comps.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No comps selected. Add one below, or reset.
      </p>
    );
  }
  const cell = "border-b border-slate-100 px-2 py-1.5 text-right align-top tabular-nums";
  // the estimate is a weighted middle of the adjusted prices; the raw similarity
  // score is only meaningful as each sale's share of that weight
  const totalScore = comps.reduce((sum, c) => sum + c.similarity_score, 0);

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-white px-2 py-1 text-left align-bottom font-medium text-slate-500">
              Comp
            </th>
            {comps.map((c, i) => (
              <th key={c.sale_id} className="border-b border-slate-200 px-2 py-1 text-right align-bottom">
                <div className="font-semibold text-slate-700">#{i + 1}</div>
                <div className="max-w-[8rem] truncate font-normal text-slate-500" title={c.address}>
                  {c.address}
                </div>
                <div className="font-normal text-slate-400">
                  {c.distance_mi != null ? `${c.distance_mi.toFixed(2)} mi` : "—"}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <RowLabel label="Sold for" />
            {comps.map((c) => (
              <td key={c.sale_id} className={cell}>
                <div className="font-semibold text-slate-800">{money(c.sale_price)}</div>
                <div className="text-[11px] text-slate-400">{c.sale_date}</div>
                <div className="text-[11px] text-slate-400">
                  {c.beds ?? "—"} bd · {c.baths ?? "—"} ba
                </div>
              </td>
            ))}
          </tr>
          <tr>
            <td colSpan={comps.length + 1}
                className="bg-slate-50 px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Adjustments · <span className="text-emerald-700">+ this home better</span> ·{" "}
              <span className="text-rose-700">− comp better</span>
            </td>
          </tr>
          {rows(subject).map((r) => (
            <tr key={r.key}>
              <RowLabel label={r.label} hint={r.hint} />
              {comps.map((c) => (
                <td key={c.sale_id} className={cell}>
                  <EditableAmount
                    value={c.adjustments[r.key]}
                    disabled={busy}
                    onCommit={(v) => onOverride(c.sale_id, { [r.key]: v })}
                  />
                  <div className="text-[11px] leading-tight text-slate-400">
                    {difference(r.key, c, subject)}
                  </div>
                </td>
              ))}
            </tr>
          ))}
          <tr className="bg-slate-50">
            <RowLabel strong label="Adjusted price" />
            {comps.map((c) => (
              <td key={c.sale_id} className={`${cell} bg-slate-50 font-semibold text-slate-900`}>
                {money(c.adjusted_price)}
              </td>
            ))}
          </tr>
          <tr>
            <RowLabel label="Weight" hint="closer matches count more" />
            {comps.map((c) => (
              <td key={c.sale_id} className={`${cell} text-slate-500`}>
                {totalScore > 0 ? `${Math.round((c.similarity_score / totalScore) * 100)}%` : "—"}
              </td>
            ))}
          </tr>
          <tr>
            <RowLabel label="Use" />
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

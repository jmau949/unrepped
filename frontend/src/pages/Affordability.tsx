import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { calcAffordability, getProfile, putProfile, solveOffer, type Profile } from "../api/client";
import MoneyInput from "../components/MoneyInput";
import { useCities, useConfig } from "../lib/config";
import { money } from "../lib/format";

// every query whose answer depends on the buyer profile — a profile edit must
// refetch them all, or cached results keep computing with the previous down
// payment (PMI and cash-needed from a stale profile)
const PROFILE_DEPENDENT_KEYS = ["afford-page", "afford", "offer", "offer-inverse", "compare"];

const CARD = "space-y-3 rounded-lg border border-slate-200 bg-white p-4";
const H2 = "text-sm font-semibold uppercase tracking-wide text-slate-500";
const INPUT = "w-36 rounded border border-slate-300 px-2 py-1 text-right";

// the calculator's payment lines, in reading order
const BREAKDOWN: [string, string][] = [
  ["pi", "Mortgage (principal + interest)"],
  ["tax", "Property tax"],
  ["insurance", "Home insurance"],
  ["earthquake", "Earthquake insurance"],
  ["pmi", "Mortgage insurance (PMI)"],
  ["hoa", "HOA"],
];

export default function Affordability() {
  const qc = useQueryClient();
  const config = useConfig();
  const cities = useCities();
  const pack = config.data?.pack;
  const band = config.data?.geography.price_band;
  const profile = useQuery({ queryKey: ["profile"], queryFn: getProfile });
  const saveMut = useMutation({
    mutationFn: putProfile,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      for (const key of PROFILE_DEPENDENT_KEYS) qc.invalidateQueries({ queryKey: [key] });
    },
  });

  // Until the user picks, the calculator sits on the configured market: the first
  // target city, at the middle of the shopping band.
  const [pricePick, setPricePick] = useState<number | null>(null);
  const [cityPick, setCityPick] = useState<string | null>(null);
  const price = pricePick ?? (band ? Math.round((band.min + band.max) / 2) : 0);
  const city = cityPick ?? cities[0] ?? "";
  const [hoa, setHoa] = useState(0);
  const calc = useQuery({
    queryKey: ["afford-page", price, city, hoa],
    queryFn: () => calcAffordability({ price, city, hoa_monthly: hoa }),
    enabled: price > 0 && city !== "",
  });
  // profile-only answer; profile edits invalidate ["profile"], so key on its data
  const inverse = useQuery({
    queryKey: ["offer-inverse", city, profile.data],
    queryFn: () => solveOffer({ city }),
    enabled: !!profile.data && city !== "",
  });

  if (!profile.data) return <p className="text-sm text-slate-400">Loading…</p>;
  const p = profile.data;
  const save = (patch: Partial<Profile>) => saveMut.mutate({ ...p, ...patch });
  const liveRate = calc.data && p.rate_assumption == null ? calc.data.rate_used : null;

  const row = (label: string, hint: string, input: ReactNode) => (
    <label className="flex items-start justify-between gap-3 text-sm">
      <span>
        <span className="text-slate-700">{label}</span>
        {hint && <span className="block text-xs text-slate-400">{hint}</span>}
      </span>
      {input}
    </label>
  );
  const money$ = (value: number, onSave: (v: number) => void, placeholder?: string) => (
    <MoneyInput value={value || null} onSave={(v) => onSave(v ?? 0)} placeholder={placeholder}
                className={INPUT} />
  );

  const inv = inverse.data;
  const limits = inv?.limits;
  const binding = inv?.ltv_capped ? "down_payment" : inv?.payment_capped ? "payment" : "cash";
  const limitRow = (key: string, label: string, value: number | null, note?: string) => (
    <li key={key} className={"flex justify-between gap-4 " + (key === binding ? "font-semibold text-slate-900" : "text-slate-500")}>
      <span>{label}{note && <span className="block text-xs font-normal text-slate-400">{note}</span>}</span>
      <span className="tabular-nums">{value == null ? "—" : `up to ${money(value, false)}`}</span>
    </li>
  );

  return (
    <div className="grid max-w-4xl gap-6 lg:grid-cols-2">
      <section className={`${CARD} lg:col-span-2`}>
        <h2 className={H2}>What can I afford?</h2>
        {inv && limits ? (
          <>
            {/* Without income the only limits are cash and the 20% floor, which
                ignore the monthly payment entirely — a number then misleads. */}
            {limits.payment == null ? (
              <p className="text-lg font-semibold text-slate-700">
                Enter your yearly income below to see what you can afford.
                <span className="block text-sm font-normal text-slate-500">
                  The monthly payment your income supports is usually the real limit; without
                  it, only your cash and down payment are checked.
                </span>
              </p>
            ) : (
              <>
                <p className="text-3xl font-bold">
                  {money(inv.max_defensible_bid, false)}
                  <span className="ml-2 text-base font-normal text-slate-500">in {city}</span>
                </p>
                <p className="text-sm text-slate-600">{inv.verdict}</p>
              </>
            )}
            {limits.payment != null && (
              <>
                <ul className="space-y-1 text-sm">
                  {limitRow("payment", "Monthly payment lenders allow on your income", limits.payment)}
                  {limitRow("down_payment", "Your down payment as 20% of the price", limits.down_payment)}
                  {limitRow("cash", "Cash for down payment, closing costs and a 6-month reserve", limits.cash)}
                </ul>
                <p className="text-xs text-slate-400">The lowest of the three is what you can afford.</p>
              </>
            )}
          </>
        ) : (
          <p className="text-sm text-slate-400">Loading…</p>
        )}
      </section>

      <section className={CARD}>
        <h2 className={H2}>Your numbers</h2>
        {/* Two amounts that never overlap. The profile stores the total
            (cash_available = down payment + other savings), which the solver uses;
            changing the down payment keeps the other savings as they are. */}
        {row("Down payment", "what you'll put into the home",
             money$(p.down_payment, (v) => save({
               down_payment: v,
               cash_available: v + Math.max(p.cash_available - p.down_payment, 0),
             })))}
        {row("Other savings", "left after the down payment, for closing costs and a cushion",
             money$(Math.max(p.cash_available - p.down_payment, 0),
                    (v) => save({ cash_available: p.down_payment + v })))}
        {row("Yearly income", "before tax, everyone on the loan",
             money$(p.annual_income, (v) => save({ annual_income: v })))}
        {row("Other monthly debts", "car, student loans, credit-card minimums",
             money$(p.monthly_debts, (v) => save({ monthly_debts: v })))}
        {row("Interest rate (%)", "leave blank for today's rate",
             <input type="number" step={0.125} key={`rate-${p.rate_assumption}`}
                    defaultValue={p.rate_assumption ?? ""}
                    placeholder={liveRate != null ? `today ${liveRate.toFixed(2)}` : ""}
                    onBlur={(e) => {
                      const v = e.target.value === "" ? null : Number(e.target.value) || null;
                      if (v !== p.rate_assumption) save({ rate_assumption: v });
                    }}
                    className={INPUT} />)}
        {row("Home insurance per month", "",
             money$(p.insurance_monthly_est, (v) => save({ insurance_monthly_est: v })))}
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={p.include_earthquake_ins}
                 onChange={(e) => save({ include_earthquake_ins: e.target.checked })} />
          {pack
            ? `Include ${pack.affordability.optional_insurance_label} (~$${pack.affordability.earthquake_monthly_default}/mo)`
            : "Include the optional hazard insurance"}
        </label>
        <details className="text-sm">
          <summary className="cursor-pointer text-slate-500">Advanced</summary>
          <div className="mt-2">
            {row("Extra above the appraisal (%)",
                 "if a home appraises below your offer, how much more you'd pay in cash; used for bid advice on listings",
                 <input type="number" step={1} min={0} max={100}
                        key={`gap-${p.appraisal_gap_tolerance_pct}`}
                        defaultValue={Math.round(p.appraisal_gap_tolerance_pct * 100)}
                        onBlur={(e) => {
                          const v = Number(e.target.value) / 100;
                          if (v !== p.appraisal_gap_tolerance_pct) save({ appraisal_gap_tolerance_pct: v });
                        }}
                        className={INPUT} />)}
          </div>
        </details>
        <p className="text-xs text-slate-400">Saved automatically.</p>
      </section>

      <section className={CARD}>
        <h2 className={H2}>Check a price</h2>
        {row("Price", "", money$(price, (v) => setPricePick(v)))}
        {row("City", "sets the property-tax rate",
             <select value={city} onChange={(e) => setCityPick(e.target.value)}
                     className="w-36 rounded border border-slate-300 px-2 py-1">
               {cities.map((c) => <option key={c}>{c}</option>)}
             </select>)}
        {row("HOA per month", "", money$(hoa, setHoa, "0"))}

        {calc.data && (
          <div className="border-t border-slate-100 pt-3">
            <p className="text-3xl font-bold">
              {money(calc.data.piti, false)}
              <span className="text-base font-normal text-slate-500">/mo</span>
            </p>
            {calc.data.payment_limit != null && (
              <p className={calc.data.payment_ok ? "text-sm text-emerald-700" : "text-sm text-red-600"}>
                {calc.data.payment_ok ? "✓ Within" : "⚠ Over"} the {money(calc.data.payment_limit, false)}/mo
                lenders allow on your income
              </p>
            )}
            <table className="mt-2 w-full text-sm">
              <tbody>
                {BREAKDOWN.filter(([k]) => (calc.data.breakdown[k] ?? 0) > 0).map(([k, label]) => (
                  <tr key={k}>
                    <td className="text-slate-500">{label}</td>
                    <td className="text-right tabular-nums">{money(calc.data.breakdown[k], false)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-xs text-slate-400">
              at {calc.data.rate_used.toFixed(2)}% interest and {(calc.data.tax_rate_used * 100).toFixed(2)}% property tax
            </p>
            <div className="mt-3 space-y-1 text-sm">
              <p>
                Cash needed: <b>{money(calc.data.cash_needed, false)}</b>
                <span className="text-slate-500"> ({money(p.down_payment, false)} down + {money(calc.data.closing_est, false)} closing costs)</span>
              </p>
              <p className={calc.data.reserves_ok ? "text-emerald-700" : "text-red-600"}>
                {calc.data.reserves_ok
                  ? `✓ Leaves ${money(calc.data.reserves_after, false)}, more than 6 months of payments`
                  : `⚠ Leaves ${money(calc.data.reserves_after, false)}, less than 6 months of payments`}
              </p>
              <p className="text-xs text-slate-500">{calc.data.supplemental_tax_note}</p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

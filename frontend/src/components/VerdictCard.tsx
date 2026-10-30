import { useQuery } from "@tanstack/react-query";
import { solveOffer } from "../api/client";
import { money } from "../lib/format";

/** Offer helper (docs/08 §3 item 7): posture-driven recommendation (UNDERBID /
 * AT LIST / OVERBID), suggested opening range, value-justified ceiling, and the
 * plain-language verdict from POST /api/offer/solve. The cash-constrained max
 * defensible bid is the secondary number — what you CAN pay, not what you
 * SHOULD. */
const REC_STYLE: Record<string, { cls: string; label: string; meaning: string }> = {
  underbid: {
    cls: "bg-red-600 text-white",
    label: "UNDERBID",
    meaning:
      "Open below asking and stop at the ceiling. This home has sat past the point where the " +
      "typical listing goes pending, and most homes in that situation sell for a little less " +
      "than they ask. The ceiling is the most the evidence justifies — at or just under asking — " +
      "however much cash you have.",
  },
  at_list: {
    cls: "bg-slate-600 text-white",
    label: "BID AT LIST",
    meaning:
      "Bid around asking. The home is near the point where the typical listing goes pending " +
      "and past listings at this stage split close to even, so the model value, not the asking " +
      "price, sets the ceiling.",
  },
  overbid: {
    cls: "bg-amber-500 text-white",
    label: "OVERBID",
    meaning:
      "Expect competition. The listing is early and most homes here sell above asking, so the " +
      "asking price is a floor for bidding. The ceiling is the top of the likely sale range — " +
      "the most the evidence justifies, not what a bidding war might demand.",
  },
};

export default function VerdictCard({ listingId }: { listingId: string }) {
  const q = useQuery({
    queryKey: ["offer", listingId],
    queryFn: () => solveOffer({ listing_id: listingId }),
  });
  const d = q.data;
  const rec = d?.recommendation ? REC_STYLE[d.recommendation] : null;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Offer helper
      </h2>
      {q.isLoading && <p className="text-sm text-slate-400">…</p>}
      {q.isError && (
        <p className="text-sm text-red-500">Solver unavailable — set up your buyer profile first.</p>
      )}
      {d && (
        <>
          {rec && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded px-3 py-1 text-sm font-bold tracking-wide ${rec.cls}`}>
                  {rec.label}
                </span>
                {d.confidence && (
                  <span
                    className="text-xs text-slate-500"
                    title="How firmly the evidence points one way: high when the share of past listings that sold below (or above) asking is 80% or more, medium at 65%, low below that. Capped at medium when the value estimates disagree with each other."
                  >
                    {d.confidence} confidence
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs text-slate-500">{rec.meaning}</p>
            </>
          )}
          <p className="mt-2 flex flex-wrap items-baseline gap-2">
            <span className="text-3xl font-bold">{money(d.ceiling, false)}</span>
            <span className="text-sm text-slate-500">ceiling — don't bid past this</span>
          </p>
          {d.opening_range && (
            <p className="mt-1 text-sm text-slate-700">
              Suggested opening: <b>{money(d.opening_range.low, false)}</b> –{" "}
              <b>{money(d.opening_range.high, false)}</b>
            </p>
          )}
          <p className="mt-1 text-xs text-slate-500">
            Escalation-clause cap: <b>{money(d.escalation_cap, false)}</b> · cash ceiling
            (max defensible bid): {money(d.max_defensible_bid, false)}
          </p>
          <p className="mt-1 text-[11px] text-slate-400">
            Opening is where to start; the ceiling is where to stop, and it is what an
            escalation clause should cap at. The cash ceiling is a different number — the most
            your down payment, closing costs and appraisal-gap tolerance can support — and the
            ceiling is never above it.
          </p>
          {d.ltv_capped && (
            <p className="mt-2 rounded bg-sky-50 px-2 py-1 text-xs text-sky-800">
              ℹ Cash ceiling set by the 20%-minimum-down lender floor — raising your down
              payment raises it.
            </p>
          )}
          {d.limits.payment == null && (
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
              ⚠ No income on the Affordability page, so this max ignores the monthly payment.
              Add it there for a realistic number.
            </p>
          )}
          {d.payment_capped && (
            <p className="mt-2 rounded bg-sky-50 px-2 py-1 text-xs text-sky-800">
              ℹ Ceiling set by the monthly payment lenders allow on your income (Affordability
              page).
            </p>
          )}
          <p className="mt-2 text-sm text-slate-700">{d.verdict}</p>
          {d.confidence && d.confidence !== "high" && d.posture?.agreement === "diverge" && (
            <p className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-800">
              ⚠ Value estimates disagree
              {d.posture.spread_pct != null &&
                ` by ${(d.posture.spread_pct * 100).toFixed(0)}%`}
              {" "}— lean on the market-behaviour evidence, not any single number.
            </p>
          )}
          {d.gap_capped && (
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
              ⚠ The appraisal-gap tolerance in your profile is what caps the cash ceiling —
              more cash won't raise it.
            </p>
          )}
        </>
      )}
    </section>
  );
}

import type { Posture, PostureOut } from "../api/client";

/** Per-listing pricing-posture chip (docs/06 §5.6): the calibrated share of
 * homes with this exposure history that sell below (or at/above) the asking
 * price, with the typical clear beside it. No confidence adjective — the
 * number is the confidence. The "bid floor" framing appears only when the
 * classifier actually says the list is bait. The plain-language helpers here
 * are shared by the detail page's posture panel and the chip's tooltip. */
const STYLE: Record<Posture, string> = {
  underpriced: "bg-amber-100 text-amber-800",
  near_market: "bg-slate-100 text-slate-700",
  overpriced: "bg-red-100 text-red-800",
  unknown: "bg-slate-100 text-slate-500",
};

function tenths(p: number): { below: number; over: number } {
  const below = Math.round(p * 10);
  return { below, over: 10 - below };
}

function pctUnder(typ: number | null): string {
  return typ != null && typ < 1 ? `${((1 - typ) * 100).toFixed(1)}%` : "";
}

function pctOver(typ: number | null): string {
  return typ != null && typ > 1 ? `${((typ - 1) * 100).toFixed(1)}%` : "";
}

export function postureLabel(posture: PostureOut | null): string {
  if (!posture || posture.posture === "unknown" || posture.p_below_list == null) {
    return "pricing posture unknown — no exposure data";
  }
  const { below, over } = tenths(posture.p_below_list);
  const typ = posture.typical_sold_to_list;
  switch (posture.posture) {
    case "overpriced":
      return (
        `lingering — ~${below} in 10 such homes sell below asking` +
        (pctUnder(typ) ? ` (typ. ${pctUnder(typ)} under)` : "")
      );
    case "underpriced":
      return (
        `bid floor — ~${over} in 10 such homes sell at or above asking` +
        (pctOver(typ) ? ` (typ. ${pctOver(typ)} over)` : "")
      );
    default:
      return `market-tested — ~${below} in 10 sell below asking, ~${over} in 10 at or above`;
  }
}

/** What the chip means for THIS home, in a sentence or three — the paragraph
 * under the chip on the detail page and the first line of the tooltip. */
export function postureExplanation(posture: PostureOut | null): string | null {
  if (!posture || posture.posture === "unknown" || posture.p_below_list == null) {
    return (
      "No exposure data yet — the listing has no usable list date, or there is no " +
      "area median days-on-market to compare it against — so there is no probability " +
      "to show. Any price cut or relist is still listed below as a fact."
    );
  }
  const { below, over } = tenths(posture.p_below_list);
  const med = posture.exposure?.median_dom;
  const medStr = med != null ? `about ${Math.round(med)} days` : "the area median";
  const typ = posture.typical_sold_to_list;
  switch (posture.posture) {
    case "overpriced":
      return (
        `This home has been on the market longer than the typical home here takes to go ` +
        `pending (${medStr}), and nobody has taken it at this price. Among past listings ` +
        `in this area with the same exposure, about ${below} in 10 sold for less than ` +
        `asking${pctUnder(typ) ? `, typically ${pctUnder(typ)} less` : ""}. That is a ` +
        `probability, not a verdict on this house: about ${over} in 10 still sold at or ` +
        `above asking. The offer helper below turns it into an opening bid and a ceiling.`
      );
    case "underpriced":
      return (
        `This listing is early. Most homes here draw offers within ${medStr} and sell ` +
        `above asking, so the asking price is best read as a floor for bidding, not a cap. ` +
        `Among past listings at this stage, about ${over} in 10 sold at or above ` +
        `asking${pctOver(typ) ? `, typically ${pctOver(typ)} over` : ""}. If it is still ` +
        `active a couple of weeks from now, that picture changes.`
      );
    default:
      return (
        `This home is right around the point where the typical home here goes pending ` +
        `(${medStr}). Past listings at this stage split close to even: about ${below} in ` +
        `10 sold below asking and ${over} in 10 at or above. The market has not made up ` +
        `its mind at this price yet.`
      );
  }
}

/** Why each piece of evidence counts — the muted line under each signal row. */
export const SIGNAL_WHY: Record<string, string> = {
  exposure:
    "How long this asking price has gone untaken, measured against the area median — the " +
    "time the typical home here takes to go pending. Inside half the median most homes sell " +
    "above asking; past about 1.25× the median most sell below it. This signal carries nearly " +
    "all the weight.",
  price_cuts:
    "The seller already conceded a higher ask. Once exposure is counted this adds little: the " +
    "current ask is judged by how long it has gone untaken, not by how it got there.",
  relist:
    "The home was taken off the market and brought back. The exposure clock restarted with the " +
    "new asking price, because a new price is a new test; the cumulative days are shown for " +
    "context.",
  offer_passed:
    "A published offer date came and went with no pending sale — someone named a date and " +
    "nobody showed up. Only counted on live listings.",
};

export default function PostureBadge({ posture }: { posture: PostureOut | null }) {
  const p = posture?.posture ?? "unknown";
  const lines = [postureExplanation(posture) ?? ""];
  if (posture?.signals.length) {
    lines.push("", "Evidence (log-odds of selling below asking; the rows add up to the share above):");
    lines.push(...posture.signals.map((s) => `${s.points > 0 ? "+" : ""}${s.points} ${s.detail}`));
  }
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${STYLE[p]}`} title={lines.join("\n")}>
      {postureLabel(posture)}
    </span>
  );
}

import type { FieldHome, TourItem } from "../api/client";

/** Mirrors hb.tour_spec._is_flagged — the rules are data on `item.flag_when`, so
 * the same tiny interpreter runs in the in-app tour panel (TourPanel.tsx) and on
 * the Field page (Field.tsx), with no round trip. `year` is the tour year, for
 * the age-based conditions (`older_than`). */
export function isFlagged(item: TourItem, value: unknown, year: number): boolean {
  const c = item.flag_when as Record<string, unknown>;
  if (!c || value === null || value === undefined || value === "") return false;
  if (Array.isArray(c.in)) return (c.in as unknown[]).includes(value);
  if ("is_true" in c) return Boolean(value) === c.is_true;
  if ("older_than" in c) {
    const v = Number(value);
    return !Number.isNaN(v) && v > 1800 && year - v >= Number(c.older_than);
  }
  if ("gte" in c) {
    const v = Number(value);
    return !Number.isNaN(v) && v >= Number(c.gte);
  }
  return false;
}

export interface CostBand {
  key: string;
  label: string;
  low: number;
  high: number;
}

export interface FieldRollup {
  flaggedKeys: Set<string>;
  bands: CostBand[];
  low: number;
  high: number;
}

/** Deferred-maintenance roll-up for the Field page, deduped by cost band exactly
 * like hb.tour_spec.evaluate — a home with both a Federal Pacific panel and fuses
 * pays for one panel. Runs against the seeded spec (which carries `cost_band`), so
 * it updates with every tap and no round trip. */
export function rollupFlags(
  spec: FieldHome["spec"],
  checklist: Record<string, unknown>,
  year: number,
): FieldRollup {
  const flaggedKeys = new Set<string>();
  const bands = new Map<string, CostBand>();
  for (const section of spec.sections) {
    for (const item of section.items) {
      if (isFlagged(item, checklist[item.key], year)) {
        flaggedKeys.add(item.key);
        if (item.cost_band) bands.set(item.cost_band.key, item.cost_band);
      }
    }
  }
  const ordered = [...bands.values()].sort((a, b) => b.low - a.low);
  return {
    flaggedKeys,
    bands: ordered,
    low: ordered.reduce((s, b) => s + b.low, 0),
    high: ordered.reduce((s, b) => s + b.high, 0),
  };
}

import type { HazardFlagOut, HazardTone } from "../api/client";
import { useConfig } from "../lib/config";

// Tailwind only ships the classes it can see in the source, so the API names a
// tone and the tone -> class mapping lives here.
const TONE: Record<HazardTone, string> = {
  sky: "bg-sky-100 text-sky-800",
  orange: "bg-orange-100 text-orange-800",
  amber: "bg-amber-100 text-amber-800",
  purple: "bg-purple-100 text-purple-800",
  rose: "bg-rose-100 text-rose-800",
  slate: "bg-slate-100 text-slate-600",
};

/** Presence-based hazard chips (docs/08 §3 item 8); tooltip carries the zone value.
 *  Label and tone come from the pack's hazard layers (config.pack.hazards); a key
 *  the pack does not name is shown as itself, in slate. */
export default function HazardChips({ flags }: { flags: HazardFlagOut[] }) {
  const config = useConfig();
  if (!flags.length) return null;
  const layers = config.data?.pack.hazards ?? [];
  return (
    <span className="inline-flex flex-wrap gap-1">
      {flags.map((f) => {
        const layer = layers.find((h) => h.key === f.hazard);
        const cls = (layer && TONE[layer.tone]) ?? TONE.slate;
        return (
          <span
            key={f.hazard}
            title={f.zone_value ?? undefined}
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
          >
            {layer?.label ?? f.hazard}
          </span>
        );
      })}
    </span>
  );
}

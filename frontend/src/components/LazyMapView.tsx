import { lazy, Suspense, type ComponentProps } from "react";

/** `maplibre-gl` is the single heaviest dependency in the app, and the split
 * views on Listings / Recently Sold render the map beside the table. Loading it
 * eagerly meant neither table painted until the whole map engine had arrived —
 * so the map is its own chunk and streams in while the rows are already usable.
 * Same props as MapView; drop-in replacement. */
const MapView = lazy(() => import("./MapView"));

export default function LazyMapView(props: ComponentProps<typeof MapView>) {
  return (
    <Suspense
      fallback={
        <div className="flex h-full min-h-[16rem] items-center justify-center rounded-lg border border-slate-200 bg-slate-50 lg:min-h-[24rem]">
          <span className="animate-pulse text-sm text-slate-400">Loading map…</span>
        </div>
      }
    >
      <MapView {...props} />
    </Suspense>
  );
}

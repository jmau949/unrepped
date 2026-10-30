import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import type { ListingSummary } from "../api/client";
import { useConfig } from "../lib/config";
import { money } from "../lib/format";

/** The whole contiguous US — where the map opens if the config is not in yet. */
const FALLBACK_VIEW = { center: [-98.5, 39.8] as [number, number], zoom: 4 };

const OSM_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

/** Viewport rectangle in degrees, as the parent needs it to filter its table. */
export interface MapBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

interface Props {
  listings: ListingSummary[];
  hoveredId: string | null;
  onSelect: (id: string) => void;
  /** marker hover, so the parent can highlight the matching row */
  onHover?: (id: string | null) => void;
  /** current viewport after every pan/zoom (and once the map first settles) */
  onBoundsChange?: (bounds: MapBounds) => void;
  /** bump to re-fit the viewport around every marker */
  refitKey?: number;
  /** pin text; default is the headline price */
  pinLabel?: (l: ListingSummary) => string;
  /** an extra "home" pin (the open-house distance origin), included in the fit */
  home?: { lat: number; lon: number } | null;
}

export default function MapView({ listings, hoveredId, onSelect, onHover,
                                  onBoundsChange, refitKey, pinLabel, home }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Map<string, maplibregl.Marker>>(new Map());
  // callbacks live in a ref so parent re-renders (e.g. hover state) never
  // retrigger the marker effect — rebuilding markers refit the bounds and
  // snapped the map back to its start position
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const onBoundsRef = useRef(onBoundsChange);
  onBoundsRef.current = onBoundsChange;
  const pinLabelRef = useRef(pinLabel);
  pinLabelRef.current = pinLabel;
  const homeMarker = useRef<maplibregl.Marker | null>(null);
  const lastSignature = useRef<string>("");
  // bounds of the current marker set, kept so an outside "reset map" can refit
  const fitted = useRef<maplibregl.LngLatBounds | null>(null);

  // The start view is the configured market (geography.map). The map is built
  // once, so if the config is still in flight at mount it opens on the whole
  // country and jumps to the market when the config lands — unless the user has
  // already moved it or a result set has already been fitted.
  const config = useConfig();
  const configView = config.data?.geography.map;
  const configViewRef = useRef(configView);
  configViewRef.current = configView;
  const homed = useRef(false);
  const userMoved = useRef(false);

  useEffect(() => {
    if (!container.current || map.current) return;
    const start = configViewRef.current ?? FALLBACK_VIEW;
    homed.current = configViewRef.current != null;
    map.current = new maplibregl.Map({
      container: container.current,
      style: OSM_STYLE,
      center: start.center,
      zoom: start.zoom,
    });
    map.current.addControl(new maplibregl.NavigationControl());
    // a gesture carries its DOM event; programmatic moves (fitBounds, jumpTo) do not
    map.current.on("movestart", (e) => {
      if (e.originalEvent) userMoved.current = true;
    });
    // `moveend` also covers the programmatic fitBounds below, so the parent
    // learns the real viewport once the map settles on the result set
    const emit = () => {
      const b = map.current?.getBounds();
      if (b) onBoundsRef.current?.({
        west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth(),
      });
    };
    map.current.on("load", emit);
    map.current.on("moveend", emit);
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !configView || homed.current) return;
    homed.current = true;
    if (userMoved.current || fitted.current) return;
    m.jumpTo({ center: configView.center, zoom: configView.zoom });
  }, [configView]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    // rebuild markers only when the actual listing set changes
    const signature = listings.map((l) => l.id).join(",") + `|${home?.lat},${home?.lon}`;
    if (signature === lastSignature.current) return;
    lastSignature.current = signature;

    markers.current.forEach((marker) => marker.remove());
    markers.current.clear();

    const bounds = new maplibregl.LngLatBounds();
    listings.forEach((l) => {
      if (l.lat == null || l.lon == null) return;
      const el = document.createElement("div");
      el.className =
        "rounded-full border border-white bg-slate-900 px-1.5 py-0.5 text-[10px] font-bold text-white shadow cursor-pointer";
      // a closed sale's headline number is what it sold for, matching the table
      const price = l.status === "sold" ? l.sold_price ?? l.list_price : l.list_price;
      el.textContent = pinLabelRef.current ? pinLabelRef.current(l) : price ? money(price) : "?";
      el.onclick = () => onSelectRef.current(l.id);
      el.onmouseenter = () => onHoverRef.current?.(l.id);
      el.onmouseleave = () => onHoverRef.current?.(null);
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([l.lon, l.lat])
        .addTo(m);
      markers.current.set(l.id, marker);
      bounds.extend([l.lon, l.lat]);
    });
    homeMarker.current?.remove();
    homeMarker.current = null;
    if (home) {
      const el = document.createElement("div");
      el.className =
        "rounded-full border-2 border-white bg-emerald-600 px-1.5 py-0.5 text-[10px] font-bold text-white shadow";
      el.textContent = "Home";
      homeMarker.current = new maplibregl.Marker({ element: el })
        .setLngLat([home.lon, home.lat])
        .addTo(m);
      bounds.extend([home.lon, home.lat]);
    }
    fitted.current = bounds.isEmpty() ? null : bounds;
    if (fitted.current) m.fitBounds(fitted.current, { padding: 40, maxZoom: 13 });
  }, [listings, home]);

  // refit on demand — the marker effect above already fits whenever the set
  // itself changes, so this only handles an unchanged set the user panned away
  // from. The mount pass is skipped or it would double-fit.
  const lastRefit = useRef(refitKey);
  useEffect(() => {
    if (refitKey === lastRefit.current) return;
    lastRefit.current = refitKey;
    if (map.current && fitted.current) {
      map.current.fitBounds(fitted.current, { padding: 40, maxZoom: 13 });
    }
  }, [refitKey]);

  useEffect(() => {
    markers.current.forEach((marker, id) => {
      const el = marker.getElement();
      el.style.background = id === hoveredId ? "#dc2626" : "#0f172a";
      el.style.zIndex = id === hoveredId ? "10" : "1";
    });
  }, [hoveredId]);

  return <div ref={container} className="h-full min-h-[16rem] w-full rounded-lg lg:min-h-[24rem]" />;
}

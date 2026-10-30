import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { CmaComp, CmaSubject } from "../api/client";

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

function ring(lat: number, lon: number, miles: number, pts = 64): number[][] {
  const latR = miles / 69;
  const lonR = miles / (69 * Math.cos((lat * Math.PI) / 180));
  const out: number[][] = [];
  for (let i = 0; i <= pts; i++) {
    const a = (i / pts) * 2 * Math.PI;
    out.push([lon + lonR * Math.cos(a), lat + latR * Math.sin(a)]);
  }
  return out;
}

// Filled polygons (0.5 + 1.0 mi) so the radius reads clearly, not just a faint line.
function radiiGeoJSON(lat: number, lon: number): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [1.0, 0.5].map((mi) => ({
      type: "Feature",
      properties: { mi },
      geometry: { type: "Polygon", coordinates: [ring(lat, lon, mi)] },
    })),
  };
}

interface Props {
  subject: CmaSubject;
  comps: CmaComp[];
  hoveredSaleId?: string | null;
}

export default function CmaMap({ subject, comps, hoveredSaleId }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Map<string, maplibregl.Marker>>(new Map());
  const subjectMarker = useRef<maplibregl.Marker | null>(null);
  // Drives marker (re)rendering. Set on map load, cleared on teardown — so under
  // StrictMode's mount→cleanup→mount, the marker effect re-runs on the new map
  // (otherwise only the radius, re-added on load, would show).
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!container.current || map.current || subject.lat == null || subject.lon == null) return;
    const m = new maplibregl.Map({
      container: container.current,
      style: OSM_STYLE,
      center: [subject.lon, subject.lat],
      zoom: 13,
    });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.on("load", () => {
      m.addSource("radii", { type: "geojson", data: radiiGeoJSON(subject.lat!, subject.lon!) });
      m.addLayer({
        id: "radii-fill", type: "fill", source: "radii",
        paint: { "fill-color": "#0284c7", "fill-opacity": 0.07 },
      });
      m.addLayer({
        id: "radii-line", type: "line", source: "radii",
        paint: {
          "line-color": "#0284c7", "line-width": 1.5,
          "line-dasharray": [2, 2], "line-opacity": 0.85,
        },
      });
      setReady(true);
    });
    return () => {
      m.remove();
      map.current = null;
      markers.current.clear();
      subjectMarker.current = null;
      setReady(false);
    };
  }, [subject.lat, subject.lon]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || subject.lat == null || subject.lon == null) return;

    subjectMarker.current?.remove();
    markers.current.forEach((mk) => mk.remove());
    markers.current.clear();

    const bounds = new maplibregl.LngLatBounds();
    ring(subject.lat, subject.lon, 1.0).forEach((c) => bounds.extend(c as [number, number]));

    const subjEl = document.createElement("div");
    subjEl.className =
      "flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-amber-500 text-xs text-white shadow-md";
    subjEl.textContent = "★";
    subjectMarker.current = new maplibregl.Marker({ element: subjEl })
      .setLngLat([subject.lon, subject.lat])
      .addTo(m);

    comps.forEach((c, i) => {
      if (c.lat == null || c.lon == null) return;
      const el = document.createElement("div");
      el.dataset.sale = c.sale_id;
      el.className = `flex h-6 w-6 items-center justify-center rounded-full border-2 border-white text-[11px] font-bold shadow-md ${
        c.included ? "bg-slate-900 text-white" : "bg-white text-slate-500"
      }`;
      el.textContent = String(i + 1);
      const mk = new maplibregl.Marker({ element: el }).setLngLat([c.lon, c.lat]).addTo(m);
      markers.current.set(c.sale_id, mk);
      bounds.extend([c.lon, c.lat]);
    });

    const src = m.getSource("radii") as maplibregl.GeoJSONSource | undefined;
    src?.setData(radiiGeoJSON(subject.lat, subject.lon));
    if (!bounds.isEmpty()) m.fitBounds(bounds, { padding: 48, maxZoom: 15 });
  }, [ready, comps, subject.lat, subject.lon]);

  useEffect(() => {
    markers.current.forEach((mk, id) => {
      const el = mk.getElement();
      el.style.outline = id === hoveredSaleId ? "3px solid #dc2626" : "";
      el.style.zIndex = id === hoveredSaleId ? "1" : "";
    });
  }, [hoveredSaleId]);

  return (
    <div className="relative h-full min-h-[24rem] w-full">
      <div ref={container} className="h-full w-full overflow-hidden rounded-lg" />
      <div className="pointer-events-none absolute bottom-2 left-2 z-10 rounded bg-white/85 px-2 py-1 text-[11px] leading-4 text-slate-600 shadow">
        <div><span className="text-amber-500">★</span> subject</div>
        <div><span className="font-bold text-slate-900">●</span> comp (# = rank)</div>
        <div><span className="text-sky-600">◌</span> 0.5 / 1 mi radius</div>
      </div>
    </div>
  );
}

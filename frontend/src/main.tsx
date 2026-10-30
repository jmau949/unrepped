import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient, type Query } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { getSchedule } from "./api/client";
import "./index.css";
import { router } from "./router";

const PERSIST_MAX_AGE = 7 * 24 * 60 * 60_000;

// Valuations/listings change at most daily; without a staleTime every window
// refocus re-ran the full overbid/CMA pipeline server-side.
// Mutations invalidate explicitly, and polling queries keep their intervals.
const queryClient = new QueryClient({
  defaultOptions: {
    // gcTime matches the persister's maxAge, or a restored entry with no observer
    // would be collected before the Open Houses page mounts to read it
    queries: { staleTime: 5 * 60_000, refetchOnWindowFocus: false, gcTime: PERSIST_MAX_AGE },
  },
});

// Open Houses must be readable at the open house, where the LAN is out of reach
// (docs/08 §14). The page's own queries — the slot list, My schedule, and each day's
// route (a POST, which no HTTP cache would hold) — are persisted to localStorage and
// restored on boot, so a tab opened on wifi keeps rendering them after the connection
// drops. Offline, the default networkMode "online" pauses their fetches, so the
// restored data renders as-is; back online, stale entries refetch. Only these keys
// persist: everything else is heavier, and none of it is meant to be served stale.
const PERSISTED_KEYS = new Set(["open-houses", "open-house-schedule", "open-house-route"]);
// Bump when an open-house response shape changes; a mismatch drops the saved copy.
const PERSIST_BUSTER = "2";

function makePersister() {
  try {
    return createSyncStoragePersister({ storage: window.localStorage, key: "hb.query.v1" });
  } catch {
    return createSyncStoragePersister({ storage: undefined }); // private mode: no-op
  }
}

// My schedule is persisted even if the Open Houses page is never opened on wifi.
// Same key and fetcher as the page's SchedulePanel.
if (navigator.onLine) {
  void queryClient.prefetchQuery({ queryKey: ["open-house-schedule"], queryFn: getSchedule });
}

// The app has no service worker. One registered for this origin by whatever ran
// on this port before would keep being polled for, and could serve its own
// cached pages here, so any registration found is removed. public/sw.js does
// the same from the worker's side for the common name.
if ("serviceWorker" in navigator) {
  void navigator.serviceWorker
    .getRegistrations()
    .then((regs) => Promise.all(regs.map((r) => r.unregister())))
    .catch(() => null);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister: makePersister(),
        maxAge: PERSIST_MAX_AGE,
        buster: PERSIST_BUSTER,
        dehydrateOptions: {
          shouldDehydrateQuery: (q: Query) =>
            q.state.status === "success" && PERSISTED_KEYS.has(String(q.queryKey[0])),
        },
      }}
    >
      <RouterProvider router={router} />
    </PersistQueryClientProvider>
  </StrictMode>,
);

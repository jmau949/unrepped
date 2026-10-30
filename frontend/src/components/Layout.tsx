import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getAlerts, getHealth } from "../api/client";
import { useConfig } from "../lib/config";

interface NavItem {
  to: string;
  label: string;
  match: (pathname: string) => boolean;
  /** search params the link carries */
  search?: Record<string, unknown>;
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", match: (p) => p === "/" },
  { to: "/prep", label: "Get Ready", match: (p) => p.startsWith("/prep") },
  { to: "/listings", label: "Listings", match: (p) => p.startsWith("/listings") },
  { to: "/open-houses", label: "Open Houses", match: (p) => p.startsWith("/open-houses") },
  { to: "/sold", label: "Recently Sold", match: (p) => p.startsWith("/sold") },
  { to: "/tracker", label: "Tracker", match: (p) => p.startsWith("/tracker") },
  { to: "/watchlist", label: "Watchlist", match: (p) => p.startsWith("/watchlist") },
  { to: "/closing", label: "Closing", match: (p) => p.startsWith("/closing") },
  // `pick` asks for the picker even when a set is remembered on this device (Field.tsx)
  { to: "/field", label: "Field", match: (p) => p.startsWith("/field"), search: { ids: "", pick: true } },
  { to: "/compare", label: "Compare", match: (p) => p.startsWith("/compare") },
  { to: "/affordability", label: "Affordability", match: (p) => p.startsWith("/affordability") },
  { to: "/alerts", label: "Alerts", match: (p) => p.startsWith("/alerts") },
  { to: "/supply", label: "Supply", match: (p) => p.startsWith("/supply") },
  { to: "/data-log", label: "Data Log", match: (p) => p.startsWith("/data-log") },
];

export default function Layout() {
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 60_000 });
  // alerts no channel has delivered yet; the Alerts page's ack invalidates ["alerts"]
  const pending = useQuery({
    queryKey: ["alerts", "undelivered"],
    queryFn: () => getAlerts(100, true),
    refetchInterval: 60_000,
  });
  const pendingCount = pending.data?.length;
  // Every page reads the configured geography and pack from this one cached
  // query — mount it in the shell so it is in flight before the first page asks.
  useConfig();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  // Router navigation renders inside a React transition, so the URL-derived
  // active state waits for the destination page to finish rendering. This
  // optimistic override shades the clicked item instantly, then defers back
  // to the real pathname once the navigation commits.
  const [clicked, setClicked] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => {
    setClicked(null);
    setNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    document.body.style.overflow = navOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [navOpen]);

  const isActive = (item: NavItem) =>
    clicked !== null ? clicked === item.to : item.match(pathname);

  const navLinks = (
    <nav className="space-y-1">
      {NAV.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          search={item.search}
          onClick={() => {
            setClicked(item.to);
            setNavOpen(false);
          }}
          className={
            isActive(item)
              ? "block rounded px-3 py-2 text-sm bg-slate-900 text-white"
              : "block rounded px-3 py-2 text-sm hover:bg-slate-100"
          }
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );

  // The shell owns the window height (`dvh` so mobile browser chrome does not
  // overshoot) and `main` does the scrolling. Split views like Listings size
  // themselves with `h-full`, which needs a definite height above them — with a
  // page-level scroll their map grows to the full table height and runs
  // thousands of pixels past the fold.
  return (
    <div className="flex h-dvh bg-slate-50 text-slate-900">
      <aside className="hidden w-56 shrink-0 border-r border-slate-200 bg-white p-4 md:block">
        <div className="mb-6 text-lg font-bold">🏠 Home Buying</div>
        {navLinks}
      </aside>

      {navOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setNavOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 max-w-[80vw] overflow-y-auto bg-white p-4 shadow-xl">
            <div className="mb-6 flex items-center justify-between">
              <span className="text-lg font-bold">🏠 Home Buying</span>
              <button
                onClick={() => setNavOpen(false)}
                aria-label="Close navigation"
                className="p-1 text-slate-400 hover:text-slate-700"
              >
                ✕
              </button>
            </div>
            {navLinks}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 text-sm md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              onClick={() => setNavOpen(true)}
              aria-label="Open navigation"
              className="rounded p-1 text-xl leading-none hover:bg-slate-100 md:hidden"
            >
              ☰
            </button>
            <div className="text-slate-500">
              {health.isLoading && "checking…"}
              {/* This badge is the only signal that the server is gone, so carry
                  the real error in the tooltip — "unreachable" alone covers a
                  dead server, a 500 out of /api/ops/health, and a device that is
                  not on the LAN, which are very different fixes. */}
              {health.isError && (
                <span className="text-red-600" title={String(health.error)}>
                  {navigator.onLine ? "API unreachable" : "offline"}
                </span>
              )}
              {health.data && (
                <>
                  {/* a missed scan slot must be loud at every width: listings and
                      open houses silently go stale otherwise */}
                  {health.data.scan_overdue_since && (
                    <span className="mr-4 rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-700"
                          title={`No completed listing scan since the slot at ${health.data.scan_overdue_since}`}>
                      scans stale since {new Date(health.data.scan_overdue_since).toLocaleString()}
                    </span>
                  )}
                  <span className="mr-4">
                    db: <span className="font-medium text-emerald-600">{health.data.db}</span>
                  </span>
                  <span className="mr-4 hidden sm:inline">
                    last scan:{" "}
                    <span className="font-medium">{health.data.last_scan ?? "never"}</span>
                  </span>
                  {health.data.rentcast_quota_remaining != null && (
                    <span className="hidden sm:inline">
                      RentCast quota:{" "}
                      <span className="font-medium">{health.data.rentcast_quota_remaining}</span>
                    </span>
                  )}
                </>
              )}
            </div>
          </div>
          <Link to="/alerts" title="Alerts not yet delivered by any channel"
                className={`rounded-full px-3 py-1 text-xs ${pendingCount
                  ? "bg-amber-100 font-medium text-amber-800" : "bg-slate-100 text-slate-500"}`}>
            alerts: {pendingCount == null ? "–" : pendingCount >= 100 ? "100+" : pendingCount}
          </Link>
        </header>

        <main className="min-h-0 flex-1 overflow-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

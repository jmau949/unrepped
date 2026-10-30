import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
} from "@tanstack/react-router";
import Layout from "./components/Layout";

// Every page is a separate chunk. Statically importing all 15 built one 1.9MB
// bundle, so opening Listings also paid for Supply's charts, Closing, Compare
// and the rest before anything rendered. Only Layout (the shell) is eager.
const Affordability = lazyRouteComponent(() => import("./pages/Affordability"));
const Alerts = lazyRouteComponent(() => import("./pages/Alerts"));
const Closing = lazyRouteComponent(() => import("./pages/Closing"));
const Compare = lazyRouteComponent(() => import("./pages/Compare"));
const Dashboard = lazyRouteComponent(() => import("./pages/Dashboard"));
const DataLog = lazyRouteComponent(() => import("./pages/DataLog"));
const Field = lazyRouteComponent(() => import("./pages/Field"));
const ListingDetail = lazyRouteComponent(() => import("./pages/ListingDetail"));
const Listings = lazyRouteComponent(() => import("./pages/Listings"));
const OpenHouses = lazyRouteComponent(() => import("./pages/OpenHouses"));
const Prep = lazyRouteComponent(() => import("./pages/Prep"));
const Sold = lazyRouteComponent(() => import("./pages/Sold"));
const Supply = lazyRouteComponent(() => import("./pages/Supply"));
const Tracker = lazyRouteComponent(() => import("./pages/Tracker"));
const Watchlist = lazyRouteComponent(() => import("./pages/Watchlist"));

const rootRoute = createRootRoute({ component: Layout });

const routes = [
  createRoute({ getParentRoute: () => rootRoute, path: "/", component: Dashboard }),
  createRoute({ getParentRoute: () => rootRoute, path: "/prep", component: Prep }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/listings",
    component: Listings,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/listings/$listingId",
    component: ListingDetail,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/open-houses",
    component: OpenHouses,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/sold",
    component: Sold,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/tracker",
    component: Tracker,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/watchlist",
    component: Watchlist,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/closing",
    component: Closing,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/field",
    component: Field,
    // `pick` asks for the home picker even when a set is remembered on this device — bare
    // /field otherwise resumes that set (Field.tsx).
    validateSearch: (search: Record<string, unknown>): { ids: string; pick?: boolean } => ({
      ids: typeof search.ids === "string" ? search.ids : "",
      ...(search.pick ? { pick: true } : {}),
    }),
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/compare",
    component: Compare,
    validateSearch: (search: Record<string, unknown>): { ids: string } => ({
      ids: typeof search.ids === "string" ? search.ids : "",
    }),
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/affordability",
    component: Affordability,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/alerts",
    component: Alerts,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/supply",
    component: Supply,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/data-log",
    component: DataLog,
  }),
];

export const router = createRouter({
  routeTree: rootRoute.addChildren(routes),
  // shown while a page chunk is in flight — the nav shell stays put, so a page
  // switch never blanks the whole window
  defaultPendingComponent: () => <p className="text-sm text-slate-400">Loading…</p>,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

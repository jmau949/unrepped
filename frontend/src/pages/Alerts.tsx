import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  getAlertRules, getAlerts, putAlertRules, readAlert, readAllAlerts, type AlertItem,
} from "../api/client";
import { useConfig } from "../lib/config";
import { clock, dayParts, groupByDay } from "../lib/format";

const TYPE_ICON: Record<string, string> = {
  price_cut: "↓", relist: "↻", back_on_market: "↩", new_listing_match: "✦",
  offer_date_soon: "⏰", new_comp_sold: "🏷", rate_move: "%", scan_failure: "⚠",
  watched_status: "👁", deal_deadline_soon: "📅", deal_deadline_overdue: "‼",
};

export default function Alerts() {
  const qc = useQueryClient();
  const tz = useConfig().data?.geography.timezone;
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => getAlerts(), refetchInterval: 60_000 });
  const rules = useQuery({ queryKey: ["alert-rules"], queryFn: getAlertRules });
  // the row flips before the request lands, so leaving for the home and coming
  // back never shows it bold again for a moment; the header pill shares the
  // ["alerts"] prefix and refetches on the invalidation
  const readMut = useMutation({
    mutationFn: readAlert,
    onMutate: (id: string) => {
      const now = new Date().toISOString();
      qc.setQueryData<AlertItem[]>(["alerts"], (old) =>
        old?.map((a) => (a.id === id ? { ...a, read_at: now } : a)));
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const readAllMut = useMutation({
    mutationFn: readAllAlerts,
    onSettled: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const toggleMut = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      putAlertRules({ [name]: { ...(rules.data?.[name] ?? {}), enabled } }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  const items = alerts.data ?? [];
  const unread = items.filter((a) => a.read_at === null).length;
  // newest day first; inside a day the API's newest-first order holds
  const groups = groupByDay(items, (a) => a.created_at, tz, "desc");

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Alerts</h1>
        {alerts.data && (
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            unread ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-500"}`}>
            {unread ? `${unread} unread` : "all read"}
          </span>
        )}
        {unread > 0 && (
          <button type="button" onClick={() => readAllMut.mutate()} disabled={readAllMut.isPending}
                  className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            Mark all read
          </button>
        )}
      </div>

      <section className="rounded-lg border border-slate-200 bg-white">
        {alerts.data?.length === 0 && (
          <p className="p-6 text-sm text-slate-400">No alerts yet — they fire from the daily scan.</p>
        )}
        {groups.map((g, i) => {
          const d = dayParts(g.iso, tz);
          const dayUnread = g.items.filter((a) => a.read_at === null).length;
          return (
            <section key={g.key}>
              <h2 className={`sticky top-0 z-10 flex items-baseline gap-2 bg-slate-800 px-3 py-1.5 text-white ${
                i === 0 ? "rounded-t-lg" : ""}`}>
                <span className="font-bold">{d.relative ?? d.weekday}</span>
                <span className="text-sm text-slate-300">{d.relative ? `${d.short} ${d.date}` : d.date}</span>
                <span className="ml-auto text-xs text-slate-300">
                  {g.items.length} alert{g.items.length === 1 ? "" : "s"}
                  {dayUnread > 0 && <span className="text-amber-300"> · {dayUnread} unread</span>}
                </span>
              </h2>
              <ul className="divide-y divide-slate-100">
                {g.items.map((a) => (
                  <li key={a.id}>
                    <AlertRow a={a} tz={tz}
                              onOpen={() => { if (a.read_at === null) readMut.mutate(a.id); }} />
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Rules</h2>
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          {Object.entries(rules.data ?? {}).map(([name, cfg]) => (
            <label key={name} className="flex items-center gap-2">
              <input type="checkbox" checked={cfg.enabled !== false}
                     onChange={(e) => toggleMut.mutate({ name, enabled: e.target.checked })} />
              {name.replace(/_/g, " ")}
            </label>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-400">
          Delivery channels come from ALERT_CHANNELS in .env: log, toast (Windows), pushover, email (SMTP settings); default toast,log.
        </p>
      </section>
    </div>
  );
}

/** One alert: the unread-mail look shared with Recently Sold and Open Houses
 *  (blue dot and bold until opened, then dimmed with a ✓), and the whole row
 *  is the link — to the home, or to the page that explains an alert without
 *  one (a closing deadline → Closing, a failed scan → Data Log). Opening it
 *  marks it read. */
function AlertRow({ a, tz, onOpen }: { a: AlertItem; tz: string | undefined; onOpen: () => void }) {
  const read = a.read_at !== null;
  const cls = `flex w-full items-start gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
    read ? "text-slate-400" : "font-medium"}`;
  const body = (
    <>
      <span className="text-lg leading-none">{TYPE_ICON[a.type] ?? "•"}</span>
      <span className="flex min-w-0 flex-1 items-start gap-1.5">
        {!read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-blue-500" title="Not opened yet" />}
        <span className="min-w-0">{a.message}</span>
        {read && (
          <span className="shrink-0 text-xs font-normal text-slate-300"
                title={`Opened ${dayParts(a.read_at!, tz).date}, ${clock(a.read_at!, tz)}`}>
            ✓
          </span>
        )}
      </span>
      <span className="shrink-0 text-xs font-normal text-slate-400">{clock(a.created_at, tz)}</span>
    </>
  );
  if (a.listing_id)
    return (
      <Link to="/listings/$listingId" params={{ listingId: a.listing_id }} onClick={onOpen} className={cls}>
        {body}
      </Link>
    );
  if (a.type.startsWith("deal_deadline"))
    return <Link to="/closing" onClick={onOpen} className={cls}>{body}</Link>;
  if (a.type === "scan_failure")
    return <Link to="/data-log" onClick={onOpen} className={cls}>{body}</Link>;
  return <button type="button" onClick={onOpen} className={cls}>{body}</button>;
}

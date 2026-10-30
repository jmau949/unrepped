import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ackAlert, getAlertRules, getAlerts, putAlertRules } from "../api/client";

const TYPE_ICON: Record<string, string> = {
  price_cut: "↓", relist: "↻", back_on_market: "↩", new_listing_match: "✦",
  offer_date_soon: "⏰", new_comp_sold: "🏷", rate_move: "%", scan_failure: "⚠",
  watched_status: "👁",
};

export default function Alerts() {
  const qc = useQueryClient();
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: () => getAlerts(), refetchInterval: 60_000 });
  const rules = useQuery({ queryKey: ["alert-rules"], queryFn: getAlertRules });
  const ackMut = useMutation({
    mutationFn: ackAlert,
    onSettled: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const toggleMut = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      putAlertRules({ [name]: { ...(rules.data?.[name] ?? {}), enabled } }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold">Alerts</h1>

      <section className="rounded-lg border border-slate-200 bg-white">
        {alerts.data?.length === 0 && (
          <p className="p-6 text-sm text-slate-400">No alerts yet — they fire from the daily scan.</p>
        )}
        <ul className="divide-y divide-slate-100">
          {alerts.data?.map((a) => (
            <li key={a.id} onClick={() => !a.delivered_at && ackMut.mutate(a.id)}
                className={`flex items-start gap-3 p-3 text-sm ${a.delivered_at ? "text-slate-500" : "cursor-pointer font-medium hover:bg-slate-50"}`}>
              <span className="text-lg leading-none">{TYPE_ICON[a.type] ?? "•"}</span>
              <div className="min-w-0 flex-1">
                <p>{a.message}</p>
                <p className="text-xs text-slate-400">
                  {a.created_at.slice(0, 16).replace("T", " ")}
                  {a.listing_id && (
                    <>
                      {" · "}
                      <Link to="/listings/$listingId" params={{ listingId: a.listing_id }}
                            className="text-blue-600 hover:underline"
                            onClick={(e) => e.stopPropagation()}>
                        open listing
                      </Link>
                    </>
                  )}
                </p>
              </div>
              {!a.delivered_at && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-blue-500" />}
            </li>
          ))}
        </ul>
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

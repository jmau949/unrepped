import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getPipelineRuns, type PipelineRunInfo } from "../api/client";

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-700",
  noop: "bg-slate-100 text-slate-500",
  partial: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-700",
  running: "bg-blue-100 text-blue-700",
};

const JOBS = ["all", "redfin-market", "zillow-research", "fred", "build-index", "listing-scan", "enrich"];

function durationSec(r: PipelineRunInfo): string {
  if (!r.finished_at) return "…";
  const ms = new Date(r.finished_at).getTime() - new Date(r.started_at).getTime();
  return `${Math.max(0, Math.round(ms / 1000))}s`;
}

function localDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function localTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function DataLog() {
  const [jobFilter, setJobFilter] = useState("all");
  const runs = useQuery({
    queryKey: ["pipeline-runs", "log", jobFilter],
    queryFn: () => getPipelineRuns(jobFilter === "all" ? undefined : jobFilter, 200),
    refetchInterval: 60_000,
  });

  // group by local calendar day, newest first (API already sorts desc)
  const days = new Map<string, PipelineRunInfo[]>();
  (runs.data ?? []).forEach((r) => {
    const day = localDay(r.started_at);
    days.set(day, [...(days.get(day) ?? []), r]);
  });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">Data Log</h1>
        <select
          value={jobFilter}
          onChange={(e) => setJobFilter(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          {JOBS.map((j) => (
            <option key={j} value={j}>
              {j === "all" ? "All jobs" : j}
            </option>
          ))}
        </select>
      </div>

      {runs.data?.length === 0 && (
        <p className="text-sm text-slate-400">No runs recorded yet — run `hb pipeline daily`.</p>
      )}

      <div className="space-y-6">
        {[...days.entries()].map(([day, dayRuns]) => {
          const failed = dayRuns.filter((r) => r.status === "failed").length;
          const partial = dayRuns.filter((r) => r.status === "partial").length;
          return (
            <section key={day} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="mb-2 flex items-baseline justify-between">
                <h2 className="text-sm font-semibold">{day}</h2>
                <span className="text-xs text-slate-500">
                  {dayRuns.length} run{dayRuns.length === 1 ? "" : "s"}
                  {failed > 0 && <span className="ml-2 text-red-600">{failed} failed</span>}
                  {partial > 0 && <span className="ml-2 text-amber-600">{partial} partial</span>}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="py-1.5 pr-4">Time</th>
                      <th className="py-1.5 pr-4">Job</th>
                      <th className="py-1.5 pr-4">Status</th>
                      <th className="py-1.5 pr-4">Duration</th>
                      <th className="py-1.5 pr-4">Items</th>
                      <th className="py-1.5 pr-4">Upserted</th>
                      <th className="py-1.5">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dayRuns.map((r) => (
                      <tr key={r.id} className="border-b border-slate-100 last:border-0">
                        <td className="whitespace-nowrap py-1.5 pr-4 text-slate-500">
                          {localTime(r.started_at)}
                        </td>
                        <td className="py-1.5 pr-4 font-medium">{r.job}</td>
                        <td className="py-1.5 pr-4">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[r.status] ?? ""}`}
                          >
                            {r.status}
                          </span>
                        </td>
                        <td className="py-1.5 pr-4">{durationSec(r)}</td>
                        <td className="py-1.5 pr-4">{r.items_seen}</td>
                        <td className="py-1.5 pr-4">{r.items_upserted}</td>
                        <td
                          className="max-w-md truncate py-1.5 text-xs text-slate-500"
                          title={r.error_summary ?? ""}
                        >
                          {r.error_summary ?? ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

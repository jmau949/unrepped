import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { getPrep, patchPrep, type PrepPhase, type PrepTask } from "../api/client";

const CARD = "rounded-lg border border-slate-200 bg-white p-4";
const H2 = "mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500";
const FIELD = "rounded border border-slate-300 px-2 py-1 text-sm";

const OWNER_STYLE: Record<string, string> = {
  you: "bg-slate-800 text-white",
  lender: "bg-indigo-100 text-indigo-800",
  attorney: "bg-rose-100 text-rose-800",
  inspector: "bg-sky-100 text-sky-800",
  insurer: "bg-violet-100 text-violet-800",
  cpa: "bg-amber-100 text-amber-800",
};

export default function Prep() {
  const qc = useQueryClient();
  const prep = useQuery({ queryKey: ["prep"], queryFn: getPrep });
  const mut = useMutation({
    mutationFn: patchPrep,
    onSuccess: (data) => qc.setQueryData(["prep"], data),
  });

  const data = prep.data;
  const roll = data?.rollup;

  return (
    <div>
      <h1 className="mb-4 text-2xl font-bold">Get Ready</h1>

      <details className={`${CARD} mb-4`} open>
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
          What this page is for
        </summary>
        <div className="mt-3 space-y-2 text-sm text-slate-600">
          <p>
            Everything to have in place <strong>before</strong> you start touring and bidding.
            The rest of the app covers what comes after: watch the market on the{" "}
            <Link to="/" className="text-sky-700 underline">
              Dashboard
            </Link>
            , capture tours in{" "}
            <Link to="/field" search={{ ids: "", pick: true }} className="text-sky-700 underline">
              Field
            </Link>{" "}
            mode, run your pipeline on the{" "}
            <Link to="/tracker" className="text-sky-700 underline">
              Tracker
            </Link>
            , and once an offer is accepted, work the escrow on{" "}
            <Link to="/closing" className="text-sky-700 underline">
              Closing
            </Link>
            .
          </p>
          <p>
            <strong>Do the amber ones first.</strong> They are gated by calendar time you
            cannot compress — a credit dispute takes 30–60 days whether you start it in month
            one or the week you find a house. Everything else you can do in an evening.
          </p>
          <p className="text-slate-500">
            Tick saves immediately. Click “why &amp; how” on any item for what it's for and
            exactly what to do. Full reasoning: <code>docs/15</code>.
          </p>
        </div>
      </details>

      {roll && (
        <div className="mb-4 grid gap-4 md:grid-cols-3">
          <div className={CARD}>
            <h2 className={H2}>Progress</h2>
            <div className="text-2xl font-semibold tabular-nums">
              {roll.done} <span className="text-base text-slate-400">/ {roll.total}</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded bg-slate-100">
              <div
                className="h-full rounded bg-emerald-500"
                style={{ width: `${roll.total ? (roll.done / roll.total) * 100 : 0}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {roll.before_tour_open.length} left before you tour ·{" "}
              {roll.before_offer_open.length} before you offer
            </p>
          </div>

          <div className={`${CARD} ${roll.long_lead_open.length ? "border-amber-300 bg-amber-50" : ""}`}>
            <h2 className={H2}>Start these first</h2>
            {roll.long_lead_open.length === 0 ? (
              <p className="text-sm text-slate-500">
                Nothing slow is outstanding. Good — the rest is up to you.
              </p>
            ) : (
              <ul className="space-y-1 text-sm">
                {roll.long_lead_open.slice(0, 4).map((t) => (
                  <li key={t.key}>
                    <span className="font-medium text-slate-800">{t.label}</span>
                    <span className="block text-xs text-amber-800">{t.lead_time}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={CARD}>
            <h2 className={H2}>Next up</h2>
            {roll.next_action ? (
              <>
                <div className="font-semibold text-slate-800">{roll.next_action.label}</div>
                <p className="mt-1 text-sm text-slate-600">{roll.next_action.why}</p>
              </>
            ) : (
              <p className="text-sm text-slate-500">
                All done. You are as prepared as this list can make you.
              </p>
            )}
          </div>
        </div>
      )}

      {prep.isLoading && <p className="text-sm text-slate-400">Loading…</p>}

      {data?.phases.map((phase) => (
        <PhaseBlock
          key={phase.key}
          phase={phase}
          onToggle={(task, done) =>
            mut.mutate({
              [task.key]: { done_on: done ? new Date().toISOString().slice(0, 10) : null },
            })
          }
          onNote={(task, note) => mut.mutate({ [task.key]: { note } })}
        />
      ))}
    </div>
  );
}

function PhaseBlock({
  phase,
  onToggle,
  onNote,
}: {
  phase: PrepPhase;
  onToggle: (task: PrepTask, done: boolean) => void;
  onNote: (task: PrepTask, note: string) => void;
}) {
  const done = phase.tasks.filter((t) => t.done).length;
  return (
    <details className={`${CARD} mb-3`} open={done < phase.tasks.length}>
      <summary className="cursor-pointer list-none">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-semibold text-slate-800">{phase.title}</span>
          <span className="text-xs tabular-nums text-slate-400">
            {done} / {phase.tasks.length}
          </span>
        </div>
        <p className="mt-1 text-sm text-slate-500">{phase.blurb}</p>
      </summary>
      <div className="mt-3 space-y-1">
        {phase.tasks.map((t) => (
          <TaskRow key={t.key} task={t} onToggle={onToggle} onNote={onNote} />
        ))}
      </div>
    </details>
  );
}

function TaskRow({
  task,
  onToggle,
  onNote,
}: {
  task: PrepTask;
  onToggle: (task: PrepTask, done: boolean) => void;
  onNote: (task: PrepTask, note: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const slow = !task.done && task.lead_time;

  return (
    <div
      className={`rounded border p-2 ${
        slow ? "border-amber-200 bg-amber-50" : "border-slate-100"
      }`}
    >
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 cursor-pointer accent-emerald-600"
          title={task.done ? "Untick to mark not done" : "Tick when done — saves immediately"}
          checked={task.done}
          onChange={(e) => onToggle(task, e.target.checked)}
        />
        <div className="min-w-0 flex-1">
          <button
            className="text-left text-sm font-medium text-slate-800"
            onClick={() => setOpen((v) => !v)}
          >
            <span className={task.done ? "text-slate-400 line-through" : ""}>{task.label}</span>
          </button>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span
              className={`rounded px-1.5 py-0.5 ${OWNER_STYLE[task.owner] ?? "bg-slate-100 text-slate-600"}`}
            >
              {task.owner}
            </span>
            <span>{task.needed_by}</span>
            {task.lead_time && (
              <span className="rounded bg-amber-200 px-1.5 py-0.5 font-medium text-amber-900">
                takes {task.lead_time}
              </span>
            )}
            <button
              className="font-medium text-sky-700 underline"
              onClick={() => setOpen((v) => !v)}
            >
              {open ? "hide" : "why & how"}
            </button>
          </div>
          {open && (
            <div className="mt-2 space-y-2 border-l-2 border-slate-200 pl-3 text-sm">
              <p className="text-slate-700">{task.why}</p>
              <p className="text-slate-500">{task.how}</p>
              <input
                className={`${FIELD} w-full`}
                placeholder="Your note — who you called, what they quoted, what they said…"
                defaultValue={task.note ?? ""}
                onBlur={(e) =>
                  e.target.value !== (task.note ?? "") && onNote(task, e.target.value)
                }
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

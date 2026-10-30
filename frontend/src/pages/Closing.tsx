import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  addDealContact,
  CONTACT_KINDS,
  createDeal,
  deleteDeal,
  deleteDealContact,
  getClosingSpec,
  getDeal,
  getDeals,
  getTracked,
  patchDeal,
  type ClosingPhase,
  type ClosingTask,
  type Deal,
} from "../api/client";
import MarkdownGuide, { openGuideSection, useClosingGuide } from "../components/MarkdownGuide";
import MoneyInput from "../components/MoneyInput";
import { useConfig } from "../lib/config";
import { money } from "../lib/format";

const CARD = "rounded-lg border border-slate-200 bg-white p-4";
const H2 = "mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500";
const FIELD = "rounded border border-slate-300 px-2 py-1 text-sm";

const OWNER_STYLE: Record<string, string> = {
  you: "bg-slate-800 text-white",
  lender: "bg-indigo-100 text-indigo-800",
  escrow: "bg-emerald-100 text-emerald-800",
  title: "bg-emerald-100 text-emerald-800",
  seller: "bg-amber-100 text-amber-800",
  inspector: "bg-sky-100 text-sky-800",
  insurer: "bg-violet-100 text-violet-800",
  attorney: "bg-rose-100 text-rose-800",
};

/** The three contingency clocks plus COE, in the order they fall due. */
const CLOCKS: { anchor: string; label: string }[] = [
  { anchor: "emd", label: "Deposit due" },
  { anchor: "investigation_removal", label: "Investigation" },
  { anchor: "appraisal_removal", label: "Appraisal" },
  { anchor: "loan_removal", label: "Loan" },
  { anchor: "coe", label: "Close of escrow" },
];

function daysUntil(date: string | null | undefined): number | null {
  if (!date) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((new Date(`${date}T00:00:00`).getTime() - today.getTime()) / 86_400_000);
}

function countdown(days: number | null): string {
  if (days == null) return "—";
  if (days === 0) return "today";
  return days < 0 ? `${-days}d ago` : `in ${days}d`;
}

export default function Closing() {
  const qc = useQueryClient();
  const deals = useQuery({ queryKey: ["deals"], queryFn: getDeals });
  const tracked = useQuery({ queryKey: ["tracked"], queryFn: getTracked });
  const config = useConfig();
  const pack = config.data?.pack;
  // null when the pack ships no guide — then nothing on the page links into it
  const guide = useClosingGuide();
  const firstChapter = guide.data?.sections[0]?.id;

  const [selected, setSelected] = useState<string | null>(null);
  const items = deals.data ?? [];
  const activeId = (selected && items.some((d) => d.id === selected) ? selected : items[0]?.id) ?? null;

  // The LIST endpoint omits `spec` and `contacts` on purpose (68 tasks per deal is a
  // lot of payload for a picker). The task list, the whole point of this page, lives
  // in the detail payload — so fetch that for the selected deal rather than rendering
  // from the list row.
  const detail = useQuery({
    queryKey: ["deal", activeId],
    queryFn: () => getDeal(activeId as string),
    enabled: activeId != null,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["deals"] });
    qc.invalidateQueries({ queryKey: ["deal"] });
    qc.invalidateQueries({ queryKey: ["tracked"] });
  };

  const createMut = useMutation({
    mutationFn: createDeal,
    onSuccess: (d) => setSelected(d.id),
    onSettled: invalidate,
  });
  const deleteMut = useMutation({
    mutationFn: deleteDeal,
    onSuccess: () => setSelected(null),
    onSettled: invalidate,
  });

  const deal = detail.data ?? null;

  // Homes that reached "won" but have no deal yet — the hand-off from the kanban.
  const candidates = (tracked.data ?? []).filter(
    (t) => !t.deal_id && ["offered", "won", "closing"].includes(t.stage),
  );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Closing</h1>
        {items.length > 1 && (
          <select
            className={FIELD}
            value={activeId ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {items.map((d) => (
              <option key={d.id} value={d.id}>
                {d.address ?? d.listing_id} — {d.status}
              </option>
            ))}
          </select>
        )}
        {activeId && (
          // Started one by mistake? Removing it drops you back to the read-only
          // playbook, and never touches the listing or the tour.
          <button
            className="ml-auto text-xs text-slate-400 underline hover:text-rose-700"
            onClick={() => deleteMut.mutate(activeId)}
          >
            Remove this closing tracker
          </button>
        )}
      </div>

      <details className={`${CARD} mb-4`} open>
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
          How this page works
        </summary>
        <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-slate-600">
          <li>
            <strong>Fill in the Contract card first.</strong> Acceptance date, close of escrow,
            price, and the three contingency day-counts — read them off your signed contract.
            Every date on this page is calculated from those five numbers, so if one is wrong,
            everything below it is wrong.
          </li>
          <li>
            <strong>Tick a task when it's done.</strong> It saves immediately — there is no save
            button. Untick to undo.
          </li>
          <li>
            <strong>Click “why” on any task</strong> for what it's actually for and how to do it,
            plus a box to leave yourself a note.
          </li>
          <li>
            <strong>Watch the colours.</strong> A red{" "}
            <span className="rounded bg-rose-600 px-1 text-[10px] font-bold text-white">
              BLOCKING
            </span>{" "}
            badge means the deal can fail or the deposit can be lost if you skip it. An amber row
            is due within 3 days; a red row is already overdue.
          </li>
          <li>
            <strong>Didn't negotiate a contingency?</strong> Hit “waive” next to it in the
            Contract card — that clock disappears along with every task that depended on it.
          </li>
          {firstChapter && (
            <li>
              <strong>New to this?</strong> The full playbook — forms, the contingency clock,
              inspections, insurance, cash to close — is in{" "}
              <button
                className="text-sky-700 underline"
                onClick={() => openGuideSection(firstChapter)}
              >
                The closing playbook
              </button>{" "}
              below, one chapter per stage.
            </li>
          )}
          <li>
            The grey chips at the top are your deadlines at a glance. The tag on each task
            (<span className="rounded bg-slate-800 px-1 text-[10px] text-white">you</span>,{" "}
            <span className="rounded bg-emerald-100 px-1 text-[10px] text-emerald-800">escrow</span>
            , …) is who actually performs it.
          </li>
        </ol>
        <p className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <strong>These dates are arithmetic, not authority.</strong> They are computed from the
          numbers you entered off your own contract — the contract governs. This is not legal
          advice; with no buyer's agent, {pack?.attorney_phrase ?? "a real estate attorney"} on
          a flat fee is the highest-value thing you can buy.
        </p>
      </details>

      <MarkdownGuide defaultOpen={activeId == null} />

      {candidates.length > 0 && (
        <div className={`${CARD} mb-4`}>
          <h2 className={H2}>Start a closing tracker</h2>
          <div className="flex flex-wrap gap-2">
            {candidates.map((t) => (
              <button
                key={t.id}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
                onClick={() => createMut.mutate({ listing_id: t.listing.id })}
              >
                + {t.listing.address}
              </button>
            ))}
          </div>
        </div>
      )}

      {activeId == null && <EmptyState />}
      {activeId != null && !deal && (
        <p className="text-sm text-slate-400">Loading the deal…</p>
      )}
      {deal && (
        <DealView
          deal={deal}
          trackedStage={
            (tracked.data ?? []).find((t) => t.listing.id === deal.listing_id)?.stage ?? null
          }
          onChanged={invalidate}
        />
      )}
    </div>
  );
}

/** With no accepted offer there is still a reason to be here: read it early. */
function EmptyState() {
  const spec = useQuery({ queryKey: ["closing-spec"], queryFn: () => getClosingSpec() });
  const investigation = spec.data?.contingency.investigation_days;
  return (
    <div>
      <p className="mb-4 text-sm text-slate-500">
        No deal yet. This page covers what happens <strong>after</strong> an offer is
        accepted — for what to do before you tour and bid, see{" "}
        <Link to="/prep" className="text-sky-700 underline">
          Get Ready
        </Link>
        . Move a home to <strong>offered</strong> or <strong>won</strong> on the{" "}
        <Link to="/tracker" className="text-sky-700 underline">
          Tracker
        </Link>{" "}
        to start a tracker here — or read the process below now, which is the point of
        reading it before {investigation != null ? `a ${investigation}-day` : "the"} clock is
        running.
      </p>
      {spec.data?.phases.map((p) => (
        <PhaseBlock key={p.key} phase={p} preview />
      ))}
    </div>
  );
}

function DealView({
  deal,
  trackedStage,
  onChanged,
}: {
  deal: Deal;
  trackedStage: string | null;
  onChanged: () => void;
}) {
  const patchMut = useMutation({
    mutationFn: (body: Parameters<typeof patchDeal>[1]) => patchDeal(deal.id, body),
    onSettled: onChanged,
  });
  const roll = deal.rollup;

  return (
    <div className="space-y-4">
      <ClockStrip deal={deal} />

      {trackedStage && !["won", "closing"].includes(trackedStage) && (
        // Dragging the kanban card back does NOT cancel escrow — the deal holds your
        // checklist, escrow number and contacts, and silently destroying that on a drag
        // would be worse than leaving it. Say what happened and offer the undo.
        <div className="rounded border border-slate-300 bg-slate-50 p-3 text-sm text-slate-700">
          This home is back at <strong>{trackedStage.replace("_", " ")}</strong> on the Tracker,
          but its closing tracker still exists — moving the card does not cancel escrow or
          throw away your checklist. If you started this by mistake, use{" "}
          <strong>Remove this closing tracker</strong> above.
        </div>
      )}

      {!deal.close_of_escrow_on && (
        // Without a COE anchor the final-week and post-close tasks cannot be dated, so
        // they are pruned — say so, rather than quietly showing a shorter list.
        <div className="rounded border border-sky-300 bg-sky-50 p-3 text-sm text-sky-900">
          <strong>Set your close-of-escrow date</strong> in the contract card below. Until you
          do, the final week (Closing Disclosure, walkthrough, signing, funding) and everything
          after close are hidden — they are dated backwards from COE and there is nothing to
          count back from.
        </div>
      )}

      {roll.overdue.length > 0 && (
        <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">
          <strong>{roll.overdue.length} overdue.</strong>{" "}
          {roll.overdue
            .filter((t) => t.blocking)
            .slice(0, 3)
            .map((t) => t.label)
            .join(" · ") || roll.overdue.slice(0, 3).map((t) => t.label).join(" · ")}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <DealFacts deal={deal} patch={patchMut.mutate} />
        <NextUp roll={roll} />
        <CostPanel roll={roll} />
      </div>

      {!deal.spec?.phases.length && (
        <p className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">
          The task list did not load. Reload the page — if it stays empty, the deal is
          missing its acceptance date.
        </p>
      )}

      {deal.spec?.phases.map((p) => (
        <PhaseBlock
          key={p.key}
          phase={p}
          onToggle={(task, done) =>
            patchMut.mutate({
              checklist: {
                [task.key]: { done_on: done ? new Date().toISOString().slice(0, 10) : null },
              },
            })
          }
          onNote={(task, note) => patchMut.mutate({ checklist: { [task.key]: { note } } })}
        />
      ))}

      <DealTeam deal={deal} onChanged={onChanged} />
    </div>
  );
}

function ClockStrip({ deal }: { deal: Deal }) {
  const { anchors, waived } = deal.rollup;
  return (
    <div className="flex flex-wrap gap-2">
      {CLOCKS.map(({ anchor, label }) => {
        const isWaived = waived.includes(anchor);
        const date = anchors[anchor];
        const days = daysUntil(date);
        const tone = isWaived
          ? "border-slate-200 bg-slate-50 text-slate-400"
          : days == null
            ? "border-slate-200 bg-white text-slate-400"
            : days < 0
              ? "border-rose-300 bg-rose-50 text-rose-900"
              : days <= 3
                ? "border-amber-300 bg-amber-50 text-amber-900"
                : "border-slate-200 bg-white text-slate-700";
        return (
          <div key={anchor} className={`rounded-lg border px-3 py-2 ${tone}`}>
            <div className={`text-xs uppercase tracking-wide ${isWaived ? "line-through" : ""}`}>
              {label}
            </div>
            <div className="text-lg font-semibold tabular-nums">
              {isWaived ? "waived" : countdown(days)}
            </div>
            <div className="text-xs opacity-70">{isWaived ? "no contingency" : (date ?? "not set")}</div>
          </div>
        );
      })}
    </div>
  );
}

function DealFacts({
  deal,
  patch,
}: {
  deal: Deal;
  patch: (body: Parameters<typeof patchDeal>[1]) => void;
}) {
  // the pack's day-counts: what "restore" puts back, and the hint under the fields
  const defaults = deal.spec?.contingency;
  const dayField = (
    label: string,
    field: "investigation_days" | "appraisal_days" | "loan_days",
    waiveKey: string,
  ) => {
    const value = deal[field];
    return (
      <div className="flex items-center justify-between gap-2">
        <span className="text-slate-500">{label}</span>
        {value == null ? (
          <span className="flex items-center gap-2">
            <span className="text-xs text-slate-400">waived</span>
            <button
              className="text-xs text-sky-700 underline disabled:opacity-50"
              disabled={!defaults}
              title={defaults ? `${defaults[field]} days — the ${defaults.label}` : undefined}
              onClick={() =>
                defaults &&
                patch({ [field]: defaults[field] } as Parameters<typeof patchDeal>[1])
              }
            >
              restore
            </button>
          </span>
        ) : (
          <span className="flex items-center gap-2">
            <input
              type="number"
              className={`${FIELD} w-16 text-right`}
              defaultValue={value}
              onBlur={(e) =>
                Number(e.target.value) !== value &&
                patch({ [field]: Number(e.target.value) } as Parameters<typeof patchDeal>[1])
              }
            />
            <button
              className="text-xs text-slate-400 underline hover:text-rose-700"
              title="Waiving removes this contingency and every task that depends on it"
              onClick={() => patch({ waive: [waiveKey] })}
            >
              waive
            </button>
          </span>
        )}
      </div>
    );
  };

  return (
    <div className={CARD}>
      <h2 className={H2}>Contract</h2>
      <div className="space-y-2 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="text-slate-500">Accepted</span>
          <input
            type="date"
            className={FIELD}
            defaultValue={deal.accepted_on}
            onBlur={(e) =>
              e.target.value && e.target.value !== deal.accepted_on &&
              patch({ accepted_on: e.target.value })
            }
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-slate-500">Close of escrow</span>
          <input
            type="date"
            className={FIELD}
            defaultValue={deal.close_of_escrow_on ?? ""}
            onBlur={(e) =>
              e.target.value !== (deal.close_of_escrow_on ?? "") &&
              patch({ close_of_escrow_on: e.target.value })
            }
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-slate-500">Purchase price</span>
          <MoneyInput
            className={`${FIELD} w-32 text-right`}
            value={deal.purchase_price}
            onSave={(v) => patch({ purchase_price: v })}
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-slate-500">Deposit</span>
          <MoneyInput
            className={`${FIELD} w-32 text-right`}
            value={deal.emd_amount}
            onSave={(v) => patch({ emd_amount: v })}
          />
        </div>
        <hr className="border-slate-200" />
        <p className="text-xs text-slate-400">
          Contingency periods, calendar days after acceptance.
          {defaults &&
            ` ${defaults.label} are ${defaults.investigation_days}/${defaults.appraisal_days}/${defaults.loan_days}.`}
        </p>
        {dayField("Investigation", "investigation_days", "investigation")}
        {dayField("Appraisal", "appraisal_days", "appraisal")}
        {dayField("Loan", "loan_days", "loan")}
        <hr className="border-slate-200" />
        <div className="flex items-center justify-between gap-2">
          <span className="text-slate-500">Escrow #</span>
          <input
            className={`${FIELD} w-32 text-right`}
            defaultValue={deal.escrow_number ?? ""}
            onBlur={(e) =>
              e.target.value !== (deal.escrow_number ?? "") &&
              patch({ escrow_number: e.target.value })
            }
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-slate-500">Status</span>
          <select
            className={FIELD}
            value={deal.status}
            onChange={(e) => patch({ status: e.target.value })}
          >
            {["open", "closed", "cancelled"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

function NextUp({ roll }: { roll: Deal["rollup"] }) {
  const next = roll.next_action;
  return (
    <div className={CARD}>
      <h2 className={H2}>Next up</h2>
      {next ? (
        <>
          <div className="text-base font-semibold text-slate-800">{next.label}</div>
          <div className="mt-1 text-xs text-slate-500">
            due {next.due_on} · {countdown(daysUntil(next.due_on))}
            {next.blocking && <span className="ml-2 font-semibold text-rose-700">BLOCKING</span>}
          </div>
          <p className="mt-2 text-sm text-slate-600">{next.why}</p>
        </>
      ) : (
        <p className="text-sm text-slate-400">Everything on the list is done.</p>
      )}
      <div className="mt-3 border-t border-slate-200 pt-3 text-sm">
        <div className="flex justify-between">
          <span className="text-slate-500">Done</span>
          <span className="tabular-nums">
            {roll.done} / {roll.total}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Overdue</span>
          <span className={`tabular-nums ${roll.overdue.length ? "text-rose-700" : ""}`}>
            {roll.overdue.length}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Due within 3 days</span>
          <span className="tabular-nums">{roll.due_soon.length}</span>
        </div>
      </div>
    </div>
  );
}

function CostPanel({ roll }: { roll: Deal["rollup"] }) {
  const guide = useClosingGuide();
  const hasCashChapter = guide.data?.sections.some((s) => s.id === "cash") ?? false;
  return (
    <div className={CARD}>
      <h2 className={H2}>Estimated costs</h2>
      <div className="text-lg font-semibold">
        {money(roll.costs.low)} – {money(roll.costs.high)}
      </div>
      <p className="mb-2 text-xs text-slate-400">
        {roll.costs.year} {roll.costs.label}, deduped by line. Estimates, not quotes
        {hasCashChapter && (
          <>
            {" — "}
            <button className="text-sky-700 underline" onClick={() => openGuideSection("cash")}>
              cash to close, line by line
            </button>
          </>
        )}
        .
      </p>
      <table className="w-full text-sm">
        <tbody>
          {roll.costs.items.map((c) => (
            <tr key={c.key} className="border-t border-slate-100">
              <td className="py-1 text-slate-600">{c.label}</td>
              <td className="py-1 text-right tabular-nums text-slate-500">
                {money(c.low)}–{money(c.high)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PhaseBlock({
  phase,
  onToggle,
  onNote,
  preview = false,
}: {
  phase: ClosingPhase;
  onToggle?: (task: ClosingTask, done: boolean) => void;
  onNote?: (task: ClosingTask, note: string) => void;
  preview?: boolean;
}) {
  const guide = useClosingGuide();
  const links = guide.data?.phase_map[phase.key] ?? [];
  const done = phase.tasks.filter((t) => t.done || t.waived).length;
  // In preview there is nothing to track, so the page is purely something to read —
  // open it. On a live deal, collapse a phase once everything in it is done.
  return (
    <details className={`${CARD} mb-3`} open={preview || done < phase.tasks.length}>
      <summary className="cursor-pointer list-none">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-semibold text-slate-800">{phase.title}</span>
          {!preview && (
            <span className="text-xs tabular-nums text-slate-400">
              {done} / {phase.tasks.length}
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-500">{phase.blurb}</p>
        {links.length > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            Read the guide:{" "}
            {links.map((g, i) => (
              <span key={g.id}>
                {i > 0 && " · "}
                <button
                  className="text-sky-700 underline"
                  onClick={(e) => {
                    // a click inside <summary> would otherwise toggle the phase
                    e.preventDefault();
                    openGuideSection(g.id);
                  }}
                >
                  {g.label}
                </button>
              </span>
            ))}
          </p>
        )}
      </summary>
      <div className="mt-3 space-y-1">
        {phase.tasks.map((t) => (
          <TaskRow key={t.key} task={t} onToggle={onToggle} onNote={onNote} preview={preview} />
        ))}
      </div>
    </details>
  );
}

function TaskRow({
  task,
  onToggle,
  onNote,
  preview,
}: {
  task: ClosingTask;
  onToggle?: (task: ClosingTask, done: boolean) => void;
  onNote?: (task: ClosingTask, note: string) => void;
  preview?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const days = daysUntil(task.due_on);
  const late = !task.done && !task.waived && days != null && days < 0;
  const soon = !task.done && !task.waived && days != null && days >= 0 && days <= 3;

  return (
    <div
      className={`rounded border p-2 ${
        late ? "border-rose-200 bg-rose-50" : soon ? "border-amber-200 bg-amber-50" : "border-slate-100"
      }`}
    >
      <div className="flex items-start gap-2">
        {!preview && (
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 cursor-pointer accent-emerald-600"
            title={task.done ? "Untick to mark not done" : "Tick when done — saves immediately"}
            checked={task.done}
            onChange={(e) => onToggle?.(task, e.target.checked)}
          />
        )}
        <div className="min-w-0 flex-1">
          <button
            className="text-left text-sm font-medium text-slate-800"
            onClick={() => setOpen((v) => !v)}
          >
            <span className={task.done ? "text-slate-400 line-through" : ""}>{task.label}</span>
            {task.blocking && (
              <span className="ml-2 rounded bg-rose-600 px-1 text-[10px] font-bold text-white">
                BLOCKING
              </span>
            )}
            {task.form && (
              <span
                className="ml-2 rounded bg-slate-200 px-1 text-[10px] font-semibold text-slate-600"
                title={task.form_name ? `${task.form} — ${task.form_name}` : task.form}
              >
                {task.form}
              </span>
            )}
          </button>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span
              className={`rounded px-1.5 py-0.5 ${OWNER_STYLE[task.owner] ?? "bg-slate-100 text-slate-600"}`}
            >
              {task.owner}
            </span>
            <span className="tabular-nums">
              {task.due_on}
              {!preview && ` · ${countdown(days)}`}
            </span>
            {task.cost_band && (
              <span>
                {money(task.cost_band.low)}–{money(task.cost_band.high)}
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
              {task.form_name && (
                <p className="rounded bg-slate-50 p-2 text-xs text-slate-600">
                  <strong>Form {task.form} — {task.form_name}.</strong> {task.form_what}
                </p>
              )}
              {!preview && (
                <input
                  className={`${FIELD} w-full`}
                  placeholder="Your note — who you called, what it cost, what they said…"
                  defaultValue={task.note ?? ""}
                  onBlur={(e) =>
                    e.target.value !== (task.note ?? "") && onNote?.(task, e.target.value)
                  }
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DealTeam({ deal, onChanged }: { deal: Deal; onChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  const addMut = useMutation({
    mutationFn: (body: Parameters<typeof addDealContact>[1]) => addDealContact(deal.id, body),
    onSuccess: () => setAdding(false),
    onSettled: onChanged,
  });
  const delMut = useMutation({
    mutationFn: (id: string) => deleteDealContact(deal.id, id),
    onSettled: onChanged,
  });

  return (
    <div className={CARD}>
      <h2 className={H2}>Deal team</h2>
      <p className="mb-3 text-xs text-slate-400">
        Escrow and title are neutral by law; the listing agent represents the seller. Keep the
        escrow officer's direct line here — you need a number you trust to verify wire
        instructions, and it must not come from the email carrying them.
      </p>
      <table className="w-full text-sm">
        <tbody>
          {(deal.contacts ?? []).map((c) => (
            <tr key={c.id} className="border-t border-slate-100">
              <td className="py-1 pr-2 text-slate-500">{c.kind}</td>
              <td className="py-1 pr-2 font-medium">{c.name}</td>
              <td className="py-1 pr-2 text-slate-500">{c.company}</td>
              <td className="py-1 pr-2 tabular-nums text-slate-500">{c.phone}</td>
              <td className="py-1 text-right">
                <button
                  className="text-xs text-slate-400 underline hover:text-rose-700"
                  onClick={() => delMut.mutate(c.id)}
                >
                  remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {adding ? (
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            const name = String(f.get("name") ?? "").trim();
            if (!name) return;
            addMut.mutate({
              kind: String(f.get("kind")),
              name,
              company: String(f.get("company") ?? ""),
              phone: String(f.get("phone") ?? ""),
            });
          }}
        >
          <select name="kind" className={FIELD} defaultValue="escrow">
            {CONTACT_KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
          <input name="name" className={FIELD} placeholder="name" />
          <input name="company" className={FIELD} placeholder="company" />
          <input name="phone" className={FIELD} placeholder="phone" />
          <button className="rounded bg-slate-800 px-3 py-1 text-sm text-white" type="submit">
            Add
          </button>
          <button type="button" className="text-sm text-slate-500" onClick={() => setAdding(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <button className="mt-3 text-sm text-sky-700 underline" onClick={() => setAdding(true)}>
          + Add contact
        </button>
      )}
    </div>
  );
}

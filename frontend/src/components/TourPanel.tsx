import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  createTour,
  getCmaRuns,
  getTourChecklist,
  getTours,
  patchTour,
  type Tour,
  type TourItem,
} from "../api/client";
import MoneyInput from "./MoneyInput";
import { money } from "../lib/format";
import { isFlagged } from "../lib/tourFlags";

const CARD = "rounded-lg border border-slate-200 bg-white p-4";
const H2 = "mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500";
const FIELD_BASE =
  "rounded border border-slate-300 px-2 py-1 text-sm focus:border-slate-500 focus:outline-none";
const FIELD = `w-full ${FIELD_BASE}`;
// a separate constant rather than appending w-auto to FIELD: two width utilities in
// one class list resolve by stylesheet order, not string order, so w-full would win
const FIELD_INLINE = FIELD_BASE;

const KINDS = ["open_house", "private", "drive_by", "second_visit"];

export default function TourPanel({
  listingId,
  propertyId,
}: {
  listingId: string;
  propertyId: string;
}) {
  const qc = useQueryClient();
  const spec = useQuery({
    queryKey: ["tour-checklist", listingId],
    queryFn: () => getTourChecklist(listingId),
  });
  // shares the CmaWorkbench's cache key — the estimate the deduction runs against
  const cma = useQuery({
    queryKey: ["cma-runs", propertyId],
    queryFn: () => getCmaRuns(propertyId),
  });
  const cmaEstimate = cma.data?.[0]?.estimate ?? null;
  const tours = useQuery({
    queryKey: ["tours", listingId],
    queryFn: () => getTours(listingId),
  });
  const [openSection, setOpenSection] = useState<string | null>("systems");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["tours", listingId] });
  const create = useMutation({
    mutationFn: () => createTour({ listing_id: listingId }),
    onSuccess: invalidate,
  });
  const patch = useMutation({
    mutationFn: (body: Parameters<typeof patchTour>[1]) => patchTour(tour!.id, body),
    onSuccess: invalidate,
  });

  const list = tours.data ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const tour: Tour | undefined =
    list.find((t) => t.id === selectedId) ?? list[0];

  if (spec.isLoading || tours.isLoading) {
    return (
      <section className={CARD}>
        <h2 className={H2}>Tour log</h2>
        <p className="text-sm text-slate-400">…</p>
      </section>
    );
  }

  if (!tour) {
    return (
      <section className={CARD}>
        <h2 className={H2}>Tour log</h2>
        <p className="mb-3 text-sm text-slate-500">
          No tour recorded yet. Start one here, or capture it in{" "}
          <span className="font-medium">Field</span> mode — the checklist is pruned to this
          home's age, so work down it while you are standing in the house.
        </p>
        <button
          type="button"
          onClick={() => create.mutate()}
          disabled={create.isPending}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Record a tour
        </button>
      </section>
    );
  }

  const year = Number((tour.toured_on || "").slice(0, 4)) || new Date().getFullYear();
  const answered = (key: string) => tour.checklist[key];
  const setItem = (key: string, value: unknown) =>
    patch.mutate({ checklist: { [key]: value } });

  return (
    <section className={CARD}>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className={`${H2} mb-0`}>Tour log</h2>
        {list.length > 1 && (
          <select
            className={FIELD_INLINE}
            value={tour.id}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {list.map((t) => (
              <option key={t.id} value={t.id}>
                {t.toured_on} · {t.kind.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        )}
        <span className="text-sm text-slate-500">
          {tour.toured_on}
          {tour.source === "offline_kit" && " · from backup import"}
        </span>
        <select
          className={FIELD_INLINE}
          defaultValue={tour.kind}
          onChange={(e) => patch.mutate({ kind: e.target.value })}
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => create.mutate()}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600"
        >
          + today
        </button>
      </div>

      {(spec.data?.context_notes.length ?? 0) > 0 && (
        <div className="mb-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          {spec.data!.context_notes.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-4">
        <label className="text-sm text-slate-600">
          Gut score
          <span className="ml-2 inline-flex gap-1">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => patch.mutate({ gut_score: n })}
                className={
                  "h-7 w-7 rounded border text-xs " +
                  (tour.gut_score === n
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-300 text-slate-600")
                }
              >
                {n}
              </button>
            ))}
          </span>
        </label>
        <label className="text-sm text-slate-600">
          Verdict{" "}
          <select
            className={FIELD_INLINE}
            defaultValue={tour.verdict ?? ""}
            onChange={(e) => patch.mutate({ verdict: e.target.value })}
          >
            <option value="">—</option>
            <option value="offer">offer</option>
            <option value="maybe">maybe</option>
            <option value="pass">pass</option>
          </select>
        </label>
      </div>

      {spec.data?.sections.map((section) => {
        const open = openSection === section.key;
        const sectionFlags = section.items.filter((i) =>
          isFlagged(i, answered(i.key), year),
        ).length;
        return (
          <div key={section.key} className="border-t border-slate-100">
            <button
              type="button"
              onClick={() => setOpenSection(open ? null : section.key)}
              className="flex w-full items-center justify-between py-2 text-left text-sm font-medium text-slate-700"
            >
              <span>
                {section.title}
                {sectionFlags > 0 && (
                  <span className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-xs font-semibold text-red-800">
                    {sectionFlags}
                  </span>
                )}
              </span>
              <span className="text-slate-400">{open ? "▴" : "▾"}</span>
            </button>
            {open && (
              <div className="pb-2">
                <p className="mb-2 text-xs text-slate-500">{section.blurb}</p>
                {section.items.map((item) => (
                  <ItemRow
                    key={item.key}
                    item={item}
                    value={answered(item.key)}
                    flagged={isFlagged(item, answered(item.key), year)}
                    photoTaken={tour.checklist[`photo:${item.key}`] === true}
                    onSave={(v) => setItem(item.key, v)}
                    onPhoto={(v) => setItem(`photo:${item.key}`, v)}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      <div className="border-t border-slate-100">
        <button
          type="button"
          onClick={() => setOpenSection(openSection === "qa" ? null : "qa")}
          className="flex w-full items-center justify-between py-2 text-left text-sm font-medium text-slate-700"
        >
          <span>Questions for the agent</span>
          <span className="text-slate-400">{openSection === "qa" ? "▴" : "▾"}</span>
        </button>
        {openSection === "qa" && (
          <div className="space-y-2 pb-2">
            {spec.data?.agent_questions.map((q, i) => (
              <div key={q}>
                <label className="block text-sm text-slate-600">{q}</label>
                <textarea
                  rows={2}
                  className={FIELD}
                  defaultValue={tour.agent_answers[String(i)] ?? ""}
                  onBlur={(e) => {
                    if (e.target.value !== (tour.agent_answers[String(i)] ?? ""))
                      patch.mutate({ agent_answers: { [String(i)]: e.target.value } });
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-slate-100 pt-3">
        <label className={H2}>Notes</label>
        <textarea
          rows={3}
          className={FIELD}
          placeholder="Voice-memo transcript, top 3 loves, top 3 worries…"
          defaultValue={tour.notes ?? ""}
          onBlur={(e) => {
            if (e.target.value !== (tour.notes ?? ""))
              patch.mutate({ notes: e.target.value });
          }}
        />
      </div>

      <Rollup tour={tour} cmaEstimate={cmaEstimate} onOverride={patch.mutate} />
    </section>
  );
}

function ItemRow({
  item,
  value,
  flagged,
  photoTaken,
  onSave,
  onPhoto,
}: {
  item: TourItem;
  value: unknown;
  flagged: boolean;
  photoTaken: boolean;
  onSave: (v: unknown) => void;
  onPhoto: (v: boolean) => void;
}) {
  return (
    <div className="border-t border-slate-50 py-1.5">
      <label className="block text-sm text-slate-700">
        {item.label}
        {flagged && (
          <span className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-xs font-semibold text-red-800">
            check this
          </span>
        )}
      </label>
      {item.hint && <p className="mb-1 text-xs text-slate-500">{item.hint}</p>}
      {item.type === "choice" && (
        <select
          className={FIELD}
          defaultValue={(value as string) ?? ""}
          onChange={(e) => onSave(e.target.value)}
        >
          <option value="">—</option>
          {item.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      )}
      {item.type === "bool" && (
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={value === true}
            onChange={(e) => onSave(e.target.checked)}
          />
          yes
        </label>
      )}
      {item.type === "number" && (
        <input
          type="number"
          inputMode="numeric"
          className={FIELD}
          defaultValue={value === undefined || value === null ? "" : String(value)}
          onBlur={(e) => {
            const v = e.target.value === "" ? "" : Number(e.target.value);
            if (v !== value) onSave(v);
          }}
        />
      )}
      {item.type === "rating" && (
        <span className="inline-flex gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => onSave(n)}
              className={
                "h-7 w-7 rounded border text-xs " +
                (value === n
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 text-slate-600")
              }
            >
              {n}
            </button>
          ))}
        </span>
      )}
      {item.type === "text" && (
        <textarea
          rows={2}
          className={FIELD}
          defaultValue={(value as string) ?? ""}
          onBlur={(e) => {
            if (e.target.value !== ((value as string) ?? "")) onSave(e.target.value);
          }}
        />
      )}
      {item.photo && (
        <label className="mt-1 flex items-start gap-2 text-xs text-sky-700">
          <input
            type="checkbox"
            checked={photoTaken}
            onChange={(e) => onPhoto(e.target.checked)}
          />
          <span>Photo: {item.photo}</span>
        </label>
      )}
    </div>
  );
}

function Rollup({
  tour,
  cmaEstimate,
  onOverride,
}: {
  tour: Tour;
  cmaEstimate: number | null;
  onOverride: (body: { repair_low?: number; repair_high?: number }) => void;
}) {
  if (tour.flags.length === 0) {
    return (
      <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-500">
        Nothing flagged yet.{" "}
        {tour.unanswered.length > 0 &&
          `${tour.unanswered.length} checklist items still blank — the deep-dive brief lists them as unverified.`}
      </p>
    );
  }
  const { costs } = tour;
  return (
    <div className="mt-3 rounded border border-red-200 bg-red-50 p-3">
      <h3 className="mb-2 text-sm font-semibold text-red-900">
        Deferred maintenance ({tour.flags.length} flagged)
      </h3>
      <table className="w-full text-sm text-red-900">
        <tbody>
          {costs.items.map((c) => (
            <tr key={c.key}>
              <td className="py-0.5">{c.label}</td>
              <td className="py-0.5 text-right tabular-nums">
                {money(c.low)} – {money(c.high)}
              </td>
            </tr>
          ))}
          <tr className="border-t border-red-200 font-semibold">
            <td className="py-0.5">total</td>
            <td className="py-0.5 text-right tabular-nums">
              {money(costs.low)} – {money(costs.high)}
            </td>
          </tr>
        </tbody>
      </table>
      {cmaEstimate != null && (
        // full precision, not compact: at $4M a $47k deduction rounds to the same
        // "$4.08M" on both sides, which hides the entire point of the line
        <p className="mt-2 text-sm text-red-900">
          CMA estimate {money(cmaEstimate, false)} →{" "}
          <span className="font-semibold">
            condition-adjusted {money(cmaEstimate - costs.high, false)} –{" "}
            {money(cmaEstimate - costs.low, false)}
          </span>
        </p>
      )}
      <div className="mt-2 flex items-center gap-2 text-xs text-red-900">
        <span>Override with real quotes:</span>
        <MoneyInput
          value={tour.repair_low}
          placeholder="low"
          onSave={(v) => onOverride({ repair_low: v ?? 0 })}
          className="w-24 rounded border border-red-300 bg-white px-1.5 py-0.5"
        />
        <MoneyInput
          value={tour.repair_high}
          placeholder="high"
          onSave={(v) => onOverride({ repair_high: v ?? 0 })}
          className="w-24 rounded border border-red-300 bg-white px-1.5 py-0.5"
        />
      </div>
      <p className="mt-2 text-xs text-red-800">
        Cost bands are {costs.year} {costs.label}, deduped by trade. Estimates, not quotes.
      </p>
    </div>
  );
}

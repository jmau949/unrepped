import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  createTour,
  getFieldData,
  getListings,
  getSchedule,
  getTracked,
  patchTour,
  unscheduleOpenHouse,
  untrack,
  type FieldData,
  type FieldHome,
  type ListingSummary,
  type OpenHouse,
  type Tour,
  type TourItem,
  type TourSection,
  type TrackedItem,
} from "../api/client";
import { money, weekdayClock } from "../lib/format";
import { isFlagged, rollupFlags } from "../lib/tourFlags";

// Every tap writes to localStorage first and is then saved to the server, so a
// dropped connection or a reload never loses an answer (docs/08 §11). Versioned
// keys so a shape change is a clean reset, never a corrupt read.
const HOMES_KEY = "hb.field.homes.v1"; // Record<listingId, FieldHome> — the seed
const ANSWERS_KEY = "hb.field.answers.v1"; // Record<listingId, LocalTour> — answers
const PENDING_KEY = "hb.field.pending.v1"; // listingId[] — has unsynced edits
const SET_KEY = "hb.field.set.v1"; // listingId[] — the set bare /field resumes on this device

interface LocalTour {
  toured_on: string;
  kind: string;
  checklist: Record<string, unknown>;
  agent_answers: Record<string, string>;
  gut_score: number | null;
  verdict: string | null;
  notes: string | null;
}

function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJSON(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / quota — the on-screen state still holds until sync */
  }
}

const today = () => new Date().toISOString().slice(0, 10);

function blankTour(): LocalTour {
  return {
    toured_on: today(),
    kind: "open_house",
    checklist: {},
    agent_answers: {},
    gut_score: null,
    verdict: null,
    notes: null,
  };
}

/** Start local answers from a tour already on file, so field mode continues an
 * in-app tour rather than starting a blank one over the top of it. */
function seedTour(existing: Tour | null): LocalTour {
  if (!existing) return blankTour();
  return {
    toured_on: existing.toured_on || today(),
    kind: existing.kind || "open_house",
    checklist: { ...(existing.checklist || {}) },
    agent_answers: { ...(existing.agent_answers || {}) },
    gut_score: existing.gut_score,
    verdict: existing.verdict,
    notes: existing.notes,
  };
}

function countAnswers(t: LocalTour): number {
  let n = 0;
  for (const v of Object.values(t.checklist)) {
    if (v === null || v === undefined || v === "" || v === false) continue;
    n++;
  }
  for (const v of Object.values(t.agent_answers)) if (v && v.trim()) n++;
  if (t.gut_score != null) n++;
  if (t.verdict) n++;
  if (t.notes && t.notes.trim()) n++;
  return n;
}

/** Save every home with unsaved edits: per home POST (get-or-create the day's tour)
 * then PATCH the accumulated answers. PATCH overwrites scalars + merges JSON — the
 * answers just given are the authority. Deliberately not /import, which gap-fills
 * only. Shared by capture (auto-save, Save now) and the picker's Clear; one run at a
 * time, because two overlapping drains would POST the same home twice. Returns
 * whether everything pending was saved. */
let saving = false;
async function saveOutstanding(): Promise<boolean> {
  if (!navigator.onLine || saving) return false;
  const pend = readJSON<string[]>(PENDING_KEY, []);
  if (pend.length === 0) return true;
  const stored = readJSON<Record<string, LocalTour>>(ANSWERS_KEY, {});
  saving = true;
  const drained: string[] = [];
  try {
    for (const id of pend) {
      const local = stored[id];
      if (local) {
        const created = await createTour({
          listing_id: id,
          toured_on: local.toured_on,
          kind: local.kind,
        });
        await patchTour(created.id, {
          kind: local.kind,
          checklist: local.checklist,
          agent_answers: local.agent_answers,
          ...(local.gut_score != null ? { gut_score: local.gut_score } : {}),
          ...(local.verdict ? { verdict: local.verdict } : {}),
          ...(local.notes != null ? { notes: local.notes } : {}),
        });
      }
      drained.push(id);
    }
    return true;
  } catch {
    return false;
  } finally {
    saving = false;
    // A home edited while its requests were in flight stays pending: what was sent is
    // no longer what is stored.
    const now = readJSON<Record<string, LocalTour>>(ANSWERS_KEY, {});
    const sent = (id: string) => JSON.stringify(now[id]) === JSON.stringify(stored[id]);
    const left = readJSON<string[]>(PENDING_KEY, []).filter(
      (id) => !(drained.includes(id) && sent(id)),
    );
    writeJSON(PENDING_KEY, left);
  }
}

/** navigator.onLine, kept live — for the picker, which has no sync loop of its own. */
function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

export default function Field() {
  const { ids, pick } = useSearch({ from: "/field" });
  const idList = ids
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  if (idList.length === 0) {
    // Bare /field means "resume the set on this phone" (a bookmark, a reload); only an
    // explicit `pick` (sidebar, "Change homes") shows the picker.
    const remembered = pick ? [] : readJSON<string[]>(SET_KEY, []);
    if (remembered.length > 0) {
      return <Navigate to="/field" search={{ ids: remembered.join(",") }} replace />;
    }
    return <HomePicker />;
  }
  // key on the id set so switching sessions remounts with fresh local state
  return <Capture key={idList.join(",")} ids={idList} />;
}

// --- state 1: pick the homes -------------------------------------------------

const CARD = "rounded-lg border border-slate-200 bg-white p-4";
const CHIP = "rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600";
const SUBHEAD = "mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-400";
const HELP_KEY = "hb.field.help.v1"; // { open } — this phone's collapse of the how-to panel

/** One pickable home and the reasons it is on the list. A row with neither reason is a
 * search hit: reachable, but never shown unprompted. */
interface Row {
  id: string;
  address: string;
  city: string | null;
  zip: string;
  list_price: number | null;
  tracked: TrackedItem | null;
  slots: OpenHouse[];
}

function rowOf(l: ListingSummary): Row {
  return {
    id: l.id,
    address: l.address,
    city: l.city,
    zip: l.zip,
    list_price: l.list_price,
    tracked: null,
    slots: [],
  };
}

/** The same rule as `GET /api/listings?q=`: every token must hit the address or city, or
 * be a ZIP prefix — so the phone-side filter and the server search agree. */
function matches(row: Row, q: string): boolean {
  const hay = `${row.address} ${row.city ?? ""}`.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((t) => hay.includes(t) || row.zip.startsWith(t));
}

function HomePicker() {
  const qc = useQueryClient();
  const online = useOnline();
  // The tour in progress here — offered first, so it is one tap away, and clearable.
  const [inProgress, setInProgress] = useState(() => {
    const set = readJSON<string[]>(SET_KEY, []);
    const homes = readJSON<Record<string, FieldHome>>(HOMES_KEY, {});
    return set.filter((id) => homes[id]).map((id) => ({ id, address: homes[id].address }));
  });
  const [clearFailed, setClearFailed] = useState(false);
  // Clear saves anything outstanding first, then forgets the set and its stored homes —
  // an unsaved answer is never dropped: if the save fails, nothing is cleared.
  const clear = useMutation({
    mutationFn: async () => {
      if (!(await saveOutstanding())) throw new Error("not saved");
    },
    onSuccess: () => {
      const gone = new Set(inProgress.map((h) => h.id));
      const keep = <T,>(rec: Record<string, T>) =>
        Object.fromEntries(Object.entries(rec).filter(([id]) => !gone.has(id)));
      writeJSON(HOMES_KEY, keep(readJSON<Record<string, FieldHome>>(HOMES_KEY, {})));
      writeJSON(ANSWERS_KEY, keep(readJSON<Record<string, LocalTour>>(ANSWERS_KEY, {})));
      writeJSON(SET_KEY, []);
      setInProgress([]);
      setClearFailed(false);
      qc.invalidateQueries({ queryKey: ["tours"] });
    },
    onError: () => setClearFailed(true),
  });
  const tracked = useQuery({ queryKey: ["tracked"], queryFn: getTracked });
  // Same key and fetcher as Open Houses and the boot prefetch (main.tsx), so the schedule
  // is persisted to localStorage and this list still renders while a request is pending.
  const sched = useQuery({ queryKey: ["open-house-schedule"], queryFn: getSchedule });
  const tz = sched.data?.timezone;

  // Typing is cheap; a server search is not. Settle for 250ms first, as Listings does.
  const [queryText, setQueryText] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(queryText.trim()), 250);
    return () => clearTimeout(t);
  }, [queryText]);
  const search = useQuery({
    queryKey: ["listings", "field-search", q],
    queryFn: () => getListings({ q, status: "active", sort: "list_date" }, 50),
    enabled: q.length > 0,
  });

  // The default list is only what the buyer already said they care about — the Tracker
  // and the open-house schedule — each labelled with why it is here. Anything else is a
  // search away, never a wall of every active listing.
  const rows = useMemo(() => {
    const byId = new Map<string, Row>();
    for (const t of tracked.data ?? []) byId.set(t.listing.id, { ...rowOf(t.listing), tracked: t });
    const live = (sched.data?.items ?? []).filter(
      (i) => !i.cancelled && i.listing.status === "active",
    );
    for (const oh of live) {
      const row = byId.get(oh.listing_id) ?? rowOf(oh.listing);
      row.slots = [...row.slots, oh].sort((a, b) => a.start_at.localeCompare(b.start_at));
      byId.set(oh.listing_id, row);
    }
    return byId;
  }, [tracked.data, sched.data]);

  const [picked, setPicked] = useState<string[]>([]);
  // Row data for a picked home outlives the search that surfaced it, so clearing the
  // search never drops a home that is already ticked.
  const [pickedRows, setPickedRows] = useState<Record<string, Row>>({});
  const toggle = (row: Row) => {
    setPicked((p) => (p.includes(row.id) ? p.filter((x) => x !== row.id) : [...p, row.id]));
    setPickedRows((r) => ({ ...r, [row.id]: row }));
  };

  // ✕ removes at the source — the Tracker row and/or the scheduled slot(s) — so the home
  // leaves this list on every device, exactly as the ✕ on those two pages does.
  const remove = useMutation({
    mutationFn: async (row: Row) => {
      if (row.tracked) await untrack(row.tracked.id);
      for (const oh of row.slots) await unscheduleOpenHouse(oh.id);
    },
    onSuccess: (_result, row) => setPicked((p) => p.filter((x) => x !== row.id)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["tracked"] });
      qc.invalidateQueries({ queryKey: ["open-house-schedule"] });
      qc.invalidateQueries({ queryKey: ["open-houses"] });
    },
  });

  const [helpOpen, setHelpOpen] = useState(
    () => readJSON<{ open: boolean }>(HELP_KEY, { open: true }).open,
  );

  const isPicked = (id: string) => picked.includes(id);
  const all = [...rows.values()];
  const visible = (q ? all.filter((r) => matches(r, q)) : all).filter((r) => !isPicked(r.id));
  const scheduled = visible
    .filter((r) => r.slots.length > 0)
    .sort((a, b) => a.slots[0].start_at.localeCompare(b.slots[0].start_at));
  const trackedOnly = visible.filter((r) => r.slots.length === 0);
  const more = q
    ? (search.data?.items ?? []).filter((l) => !rows.has(l.id) && !isPicked(l.id)).map(rowOf)
    : [];
  const pickedList = picked
    .map((id) => rows.get(id) ?? pickedRows[id])
    .filter((r): r is Row => Boolean(r));

  // A paused query (no connection, nothing cached) stays pending forever; only a live
  // fetch is "loading", otherwise the empty state would never show while disconnected.
  const loading =
    (tracked.isPending && tracked.fetchStatus === "fetching") ||
    (sched.isPending && sched.fetchStatus === "fetching");
  const empty = online && !loading && !q && all.length === 0;
  const noMatch = q.length > 0 && visible.length === 0 && more.length === 0 && !search.isFetching;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Field mode</h1>
        <p className="mt-1 text-sm text-slate-600">
          Pick the homes you are about to see, then walk each one through the checklist, one
          screen at a time. Every answer is saved as you tap.
        </p>
      </div>

      <details
        className={CARD}
        open={helpOpen}
        onToggle={(e) => {
          const open = e.currentTarget.open;
          setHelpOpen(open);
          writeJSON(HELP_KEY, { open });
        }}
      >
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">
          How to use Field mode
        </summary>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-slate-600">
          <li>
            <strong>Pick the homes.</strong> This list is your Tracker plus your open-house
            schedule; search by address, city or ZIP for anything else. Tick the homes you will
            see and tap <strong>Start field mode</strong>.
          </li>
          <li>
            <strong>At the house.</strong> <strong>Tap the address at the top to jump between
            homes.</strong> Four screens per home — Outside → Systems → Inside → Agent &amp;
            verdict; every tap is saved, and the deferred-maintenance total updates as you go.
          </li>
          <li>
            <strong>Afterwards.</strong> Each visit shows on the listing's Tour log and on the
            Tracker.
          </li>
          <li>
            <strong>Different homes next time.</strong> <strong>Change homes</strong> (in the
            address menu, or on the finish screen) or <strong>Field</strong> in the sidebar
            returns here. <strong>Clear</strong> on the in-progress card empties the current
            set. ✕ removes a home from the Tracker or unschedules its open house.
          </li>
        </ol>
      </details>

      {inProgress.length > 0 && (
        <section className={`${CARD} border-slate-900`}>
          <h2 className="text-sm font-semibold text-slate-900">
            {inProgress.length} home{inProgress.length === 1 ? "" : "s"} in progress
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            {inProgress.map((h) => h.address).join(" · ")}
          </p>
          <div className="mt-3 flex gap-2">
            <Link
              to="/field"
              search={{ ids: inProgress.map((h) => h.id).join(",") }}
              className="flex-1 rounded-lg bg-slate-900 px-4 py-3 text-center text-base font-semibold text-white"
            >
              Continue
            </Link>
            <button
              type="button"
              onClick={() => clear.mutate()}
              disabled={clear.isPending}
              className="rounded-lg border border-slate-300 px-4 py-3 text-base text-slate-700 disabled:opacity-50"
            >
              {clear.isPending ? "Saving…" : "Clear"}
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Clear saves any answers first, then removes these from this list. Visits already
            recorded stay on each listing's Tour log.
          </p>
          {clearFailed && (
            <p className="mt-2 text-sm text-red-700">
              Couldn't save the latest answers, so nothing was cleared. Try again with a
              connection.
            </p>
          )}
        </section>
      )}
      {!online && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          No connection. Homes already loaded still work — loading new ones waits for the
          connection.
        </p>
      )}

      <section className={CARD}>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Pick the homes you are seeing
        </h2>
        <div className="relative">
          <input
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            placeholder="search address, city, ZIP…"
            aria-label="Search listings"
            className="w-full rounded border border-slate-300 py-2 pl-2 pr-8 text-sm"
          />
          {queryText && (
            <button
              type="button"
              onClick={() => setQueryText("")}
              aria-label="clear search"
              className="absolute right-1 top-1/2 -translate-y-1/2 px-2 text-slate-400 hover:text-slate-700"
            >
              ✕
            </button>
          )}
        </div>

        {empty && (
          <p className="mt-3 text-sm text-slate-400">
            Nothing on your Tracker or open-house schedule yet — search above, or star listings
            and schedule open houses first.
          </p>
        )}
        {noMatch && <p className="mt-3 text-sm text-slate-400">No active listings match.</p>}
        {search.isError && (
          <p className="mt-3 text-sm text-amber-700">
            Search needs a connection — the list below is what's already loaded.
          </p>
        )}

        <div className="max-h-[60vh] overflow-y-auto">
          {pickedList.length > 0 && <h3 className={SUBHEAD}>Picked</h3>}
          {pickedList.map((r) => (
            <PickRow key={r.id} row={r} tz={tz} checked onToggle={() => toggle(r)} />
          ))}
          {scheduled.length > 0 && <h3 className={SUBHEAD}>On your open-house schedule</h3>}
          {scheduled.map((r) => (
            <PickRow
              key={r.id}
              row={r}
              tz={tz}
              checked={false}
              onToggle={() => toggle(r)}
              onRemove={() => remove.mutate(r)}
              removing={remove.isPending}
            />
          ))}
          {trackedOnly.length > 0 && <h3 className={SUBHEAD}>On your tracker</h3>}
          {trackedOnly.map((r) => (
            <PickRow
              key={r.id}
              row={r}
              tz={tz}
              checked={false}
              onToggle={() => toggle(r)}
              onRemove={() => remove.mutate(r)}
              removing={remove.isPending}
            />
          ))}
          {more.length > 0 && <h3 className={SUBHEAD}>More listings</h3>}
          {more.map((r) => (
            <PickRow key={r.id} row={r} tz={tz} checked={false} onToggle={() => toggle(r)} />
          ))}
        </div>
      </section>

      <div className="sticky bottom-0 -mx-4 border-t border-slate-200 bg-white/95 p-4 backdrop-blur">
        <Link
          to="/field"
          search={{ ids: picked.join(",") }}
          disabled={picked.length === 0}
          className={
            "block rounded-lg px-4 py-3 text-center text-base font-semibold " +
            (picked.length
              ? "bg-slate-900 text-white"
              : "pointer-events-none bg-slate-200 text-slate-400")
          }
        >
          Start field mode ({picked.length} home{picked.length === 1 ? "" : "s"})
        </Link>
      </div>
    </div>
  );
}

function PickRow({
  row,
  tz,
  checked,
  onToggle,
  onRemove,
  removing,
}: {
  row: Row;
  tz: string | undefined;
  checked: boolean;
  onToggle: () => void;
  /** absent on a search hit — it is not "from" anywhere, so there is nothing to remove */
  onRemove?: () => void;
  removing?: boolean;
}) {
  const title =
    row.tracked && row.slots.length > 0
      ? "remove from tracker and schedule"
      : row.tracked
        ? "remove from tracker"
        : row.slots.length > 0
          ? "remove from schedule"
          : null;
  return (
    <div className="flex items-center gap-3 border-b border-slate-100 py-2 text-sm">
      <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
        <input
          type="checkbox"
          className="h-5 w-5 shrink-0"
          checked={checked}
          onChange={onToggle}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate">{row.address}</span>
          {(row.tracked || row.slots.length > 0) && (
            <span className="mt-0.5 flex flex-wrap gap-1">
              {row.tracked && <span className={CHIP}>{row.tracked.stage}</span>}
              {row.slots.map((oh) => (
                <span key={oh.id} className={CHIP}>
                  open house {weekdayClock(oh.start_at, tz)}
                </span>
              ))}
            </span>
          )}
        </span>
      </label>
      <span className="tabular-nums text-slate-500">{money(row.list_price)}</span>
      {onRemove && title && (
        <button
          type="button"
          onClick={onRemove}
          disabled={removing}
          aria-label={title}
          title={title}
          className="px-2 py-1 text-base leading-none text-slate-300 hover:text-red-600 disabled:opacity-50"
        >
          ✕
        </button>
      )}
    </div>
  );
}

// --- state 2: capture (runs in the house) -----------------------------------

type Part = { kind: "section"; section: TourSection } | { kind: "agentqa" };
type SyncState = "idle" | "syncing" | "synced" | "error";

// The seven walk sections collapse into four logical screens, so a tour is a few
// scrolls rather than seven Next taps. Order still follows the playbook walk;
// each screen stacks its sections under sub-headings. `agentqa` is a synthetic
// part (the agent Q&A block, which has no spec section).
const GROUP_LAYOUT: { title: string; sections: string[]; agentqa?: boolean }[] = [
  { title: "Outside", sections: ["street", "exterior"] },
  { title: "Systems", sections: ["systems"] },
  { title: "Inside", sections: ["interior", "life"] },
  { title: "Agent & verdict", sections: ["verdict"], agentqa: true },
];

function Capture({ ids }: { ids: string[] }) {
  const [homes, setHomes] = useState<Record<string, FieldHome>>(() =>
    readJSON<Record<string, FieldHome>>(HOMES_KEY, {}),
  );
  const [answers, setAnswers] = useState<Record<string, LocalTour>>(() => {
    const stored = readJSON<Record<string, LocalTour>>(ANSWERS_KEY, {});
    const seed = readJSON<Record<string, FieldHome>>(HOMES_KEY, {});
    let changed = false;
    for (const id of ids) {
      if (!stored[id] && seed[id]) {
        stored[id] = seedTour(seed[id].existing);
        changed = true;
      }
    }
    if (changed) writeJSON(ANSWERS_KEY, stored);
    return stored;
  });
  const [pending, setPending] = useState<Set<string>>(
    () => new Set(readJSON<string[]>(PENDING_KEY, [])),
  );
  const [online, setOnline] = useState(() => navigator.onLine);
  const [syncState, setSyncState] = useState<SyncState>("idle");
  const [seedError, setSeedError] = useState(false);

  const [homeIdx, setHomeIdx] = useState(0);
  const [groupIdx, setGroupIdx] = useState(0);
  const [done, setDone] = useState(false);
  const [showBackup, setShowBackup] = useState(false);
  const topRef = useRef<HTMLDivElement>(null);

  // Remember the set, so bare /field (a bookmark, a reload) lands back in this tour
  // instead of the picker.
  useEffect(() => {
    writeJSON(SET_KEY, ids);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);

  // Seed from the server whenever we have a connection. Never overwrites local answers —
  // in the field the phone is the authority; the network only fills what's missing.
  useEffect(() => {
    if (!navigator.onLine) return;
    let cancelled = false;
    getFieldData(ids)
      .then((data: FieldData) => {
        if (cancelled) return;
        // Keep the phone's store to this set plus anything still waiting to sync. A home
        // loaded some earlier night and long since synced is dead weight — each carries a
        // full spec — and a store that hits the quota makes writeJSON silently stop
        // persisting answers, the one failure this page must never have.
        const keep = new Set([...ids, ...readJSON<string[]>(PENDING_KEY, [])]);
        setHomes((prev) => {
          const next: Record<string, FieldHome> = {};
          for (const [id, h] of Object.entries(prev)) if (keep.has(id)) next[id] = h;
          for (const h of data.homes) next[h.listing_id] = h;
          writeJSON(HOMES_KEY, next);
          return next;
        });
        setAnswers((prev) => {
          const next: Record<string, LocalTour> = {};
          let changed = false;
          for (const [id, t] of Object.entries(prev)) {
            if (keep.has(id)) next[id] = t;
            else changed = true;
          }
          for (const h of data.homes) {
            if (!next[h.listing_id]) {
              next[h.listing_id] = seedTour(h.existing);
              changed = true;
            }
          }
          if (changed) writeJSON(ANSWERS_KEY, next);
          return next;
        });
        setSeedError(false);
      })
      .catch(() => {
        if (!cancelled) setSeedError(true);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);

  // Track connectivity; drain the pending queue when the connection comes back.
  useEffect(() => {
    const on = () => {
      setOnline(true);
      void syncAll();
    };
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const markPending = (id: string) => {
    setPending((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      writeJSON(PENDING_KEY, [...next]);
      return next;
    });
    setSyncState("idle");
  };

  // Write-through on every edit — synchronous, no debounce, so a tab killed the
  // instant after a tap has still persisted that tap.
  const updateTour = (id: string, fn: (t: LocalTour) => LocalTour) => {
    setAnswers((prev) => {
      const next = { ...prev, [id]: fn(prev[id] ?? blankTour()) };
      writeJSON(ANSWERS_KEY, next);
      return next;
    });
    markPending(id);
  };
  const setChecklist = (id: string, key: string, value: unknown) =>
    updateTour(id, (t) => ({ ...t, checklist: { ...t.checklist, [key]: value } }));
  const setAgentAnswer = (id: string, i: number, value: string) =>
    updateTour(id, (t) => ({ ...t, agent_answers: { ...t.agent_answers, [String(i)]: value } }));

  async function syncAll() {
    if (!navigator.onLine || saving || readJSON<string[]>(PENDING_KEY, []).length === 0) return;
    setSyncState("syncing");
    const ok = await saveOutstanding();
    setSyncState(ok ? "synced" : "error");
    setPending(new Set(readJSON<string[]>(PENDING_KEY, [])));
  }

  // Save to the server shortly after the last tap, so the Tour log and the Tracker are
  // current while you walk. A burst of taps is one save; after a failure, back off.
  useEffect(() => {
    if (!online || pending.size === 0) return;
    const t = setTimeout(() => void syncAll(), syncState === "error" ? 15000 : 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online, pending, answers, syncState]);

  const backupJSON = () => {
    const stored = readJSON<Record<string, LocalTour>>(ANSWERS_KEY, {});
    const tours = ids
      .filter((id) => stored[id])
      .map((id) => ({ listing_id: id, ...stored[id] }));
    return JSON.stringify({ tours }, null, 2);
  };

  const totalAnswers = ids.reduce((s, id) => s + (answers[id] ? countAnswers(answers[id]) : 0), 0);
  const loadedCount = ids.filter((id) => homes[id]).length;

  const currentId = ids[homeIdx];
  const home = homes[currentId];
  const tour = answers[currentId] ?? blankTour();
  const year = Number((tour.toured_on || "").slice(0, 4)) || new Date().getFullYear();

  const scrollTop = () => topRef.current?.scrollIntoView({ block: "start" });
  const goHome = (i: number) => {
    setDone(false);
    setHomeIdx(i);
    setGroupIdx(0);
    scrollTop();
  };

  if (done) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <StatusBar
          online={online}
          pending={pending.size}
          answers={totalAnswers}
          loaded={loadedCount}
          total={ids.length}
          syncState={syncState}
          onSync={() => void syncAll()}
        />
        <div className={CARD}>
          <h2 className="text-lg font-semibold text-slate-900">Walk-through captured</h2>
          <p className="mt-1 text-sm text-slate-600">
            {totalAnswers} answer{totalAnswers === 1 ? "" : "s"} across {ids.length} home
            {ids.length === 1 ? "" : "s"}.{" "}
            {pending.size > 0
              ? "Some are not saved yet — they save on their own."
              : "Everything is saved."}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {ids.map((id, i) => (
              <button
                key={id}
                type="button"
                onClick={() => goHome(i)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700"
              >
                Review {homes[id]?.address ?? `home ${i + 1}`}
              </button>
            ))}
          </div>
          <BackupControls show={showBackup} setShow={setShowBackup} json={backupJSON} />
          <Link
            to="/field"
            search={{ ids: "", pick: true }}
            className="mt-4 block text-center text-sm text-blue-600 underline"
          >
            Change homes
          </Link>
        </div>
        <PrintSheet ids={ids} homes={homes} answers={answers} />
      </div>
    );
  }

  if (!home) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <StatusBar
          online={online}
          pending={pending.size}
          answers={totalAnswers}
          loaded={loadedCount}
          total={ids.length}
          syncState={syncState}
          onSync={() => void syncAll()}
        />
        <div className={CARD}>
          <h2 className="text-base font-semibold text-slate-900">This home isn't loaded yet</h2>
          <p className="mt-1 text-sm text-slate-600">
            {seedError || !online
              ? "This home's checklist couldn't load. Check the connection and reopen this page."
              : "Loading this home…"}
          </p>
          {ids.length > 1 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {ids.map((id, i) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => goHome(i)}
                  className={
                    "rounded-lg border px-3 py-2 text-sm " +
                    (homes[id]
                      ? "border-slate-300 text-slate-700"
                      : "border-slate-200 text-slate-400")
                  }
                >
                  {homes[id]?.address ?? `Home ${i + 1}`}
                </button>
              ))}
            </div>
          )}
          <Link
            to="/field"
            search={{ ids: "", pick: true }}
            className="mt-3 block text-sm text-blue-600 underline"
          >
            Change homes
          </Link>
        </div>
      </div>
    );
  }

  const byKey: Record<string, TourSection> = Object.fromEntries(
    home.spec.sections.map((s) => [s.key, s]),
  );
  const groups = GROUP_LAYOUT.map((g) => {
    const parts: Part[] = [];
    if (g.agentqa) parts.push({ kind: "agentqa" });
    for (const key of g.sections) {
      const section = byKey[key];
      if (section) parts.push({ kind: "section", section });
    }
    return { title: g.title, parts };
  }).filter((g) => g.parts.length > 0);
  const gi = Math.min(groupIdx, groups.length - 1);
  const group = groups[gi];
  const roll = rollupFlags(home.spec, tour.checklist, year);

  const next = () => {
    if (gi < groups.length - 1) {
      setGroupIdx(gi + 1);
      scrollTop();
    } else if (homeIdx < ids.length - 1) {
      goHome(homeIdx + 1);
    } else {
      setDone(true);
      void syncAll();
      scrollTop();
    }
  };
  const back = () => {
    if (gi > 0) {
      setGroupIdx(gi - 1);
      scrollTop();
    } else if (homeIdx > 0) {
      goHome(homeIdx - 1);
    }
  };

  const lastGroup = gi === groups.length - 1;
  const lastHome = homeIdx === ids.length - 1;

  return (
    <div ref={topRef} className="mx-auto max-w-2xl pb-24 print:hidden">
      {/* sticky top: status + address + progress */}
      <div className="sticky top-0 z-20 -mx-4 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6">
        <StatusBar
          online={online}
          pending={pending.size}
          answers={totalAnswers}
          loaded={loadedCount}
          total={ids.length}
          syncState={syncState}
          onSync={() => void syncAll()}
        />
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            onClick={back}
            disabled={gi === 0 && homeIdx === 0}
            className="rounded-lg px-2 py-1 text-2xl leading-none text-slate-500 disabled:opacity-30"
            aria-label="Back"
          >
            ‹
          </button>
          <div className="min-w-0 flex-1">
            <HomeSwitcher ids={ids} homes={homes} current={homeIdx} onPick={goHome} />
            <div className="text-xs text-slate-500">
              {ids.length > 1 && `Home ${homeIdx + 1}/${ids.length} · `}
              {gi + 1}/{groups.length} · {group.title}
            </div>
          </div>
        </div>
        <div className="mt-2 flex gap-1">
          {groups.map((_, i) => (
            <div
              key={i}
              className={
                "h-1.5 flex-1 rounded-full " + (i <= gi ? "bg-slate-900" : "bg-slate-200")
              }
            />
          ))}
        </div>
      </div>

      {/* the screen: every part of the group, stacked under sub-headings */}
      <div className="space-y-4 py-4">
        {gi === 0 && home.spec.context_notes.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            {home.spec.context_notes.map((n) => (
              <p key={n}>{n}</p>
            ))}
          </div>
        )}

        {group.parts.map((part, pi) =>
          part.kind === "agentqa" ? (
            <div key={pi} className="space-y-3">
              <SectionHeading
                title="Questions for the agent"
                blurb="Ask before you leave — how many disclosure packets are out is the best competition tell."
              />
              <AgentQA home={home} tour={tour} onAnswer={(i, v) => setAgentAnswer(currentId, i, v)} />
            </div>
          ) : (
            <div key={pi} className="space-y-3">
              <SectionHeading title={part.section.title} blurb={part.section.blurb} />
              {part.section.key === "verdict" && (
                <VerdictControls
                  tour={tour}
                  onGut={(n) => updateTour(currentId, (t) => ({ ...t, gut_score: n }))}
                  onVerdict={(v) => updateTour(currentId, (t) => ({ ...t, verdict: v }))}
                />
              )}
              {part.section.items.map((item) => (
                <ItemInput
                  key={item.key}
                  item={item}
                  value={tour.checklist[item.key]}
                  flagged={isFlagged(item, tour.checklist[item.key], year)}
                  photoTaken={tour.checklist[`photo:${item.key}`] === true}
                  onChange={(v) => setChecklist(currentId, item.key, v)}
                  onPhoto={(v) => setChecklist(currentId, `photo:${item.key}`, v)}
                />
              ))}
              {part.section.key === "verdict" && (
                <>
                  <NotesField
                    value={tour.notes ?? ""}
                    onSave={(v) => updateTour(currentId, (t) => ({ ...t, notes: v || null }))}
                  />
                  {roll.low > 0 && <RollupSummary roll={roll} cmaEstimate={home.cma_estimate} />}
                  <BackupControls show={showBackup} setShow={setShowBackup} json={backupJSON} />
                </>
              )}
            </div>
          ),
        )}
      </div>

      {/* sticky footer: running deferred-maintenance range + Next */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white/95 px-4 py-2 backdrop-blur">
        <div className="mx-auto flex max-w-2xl items-center gap-3">
          <div className="min-w-0 flex-1 text-xs">
            {roll.low > 0 ? (
              <span className="font-medium text-red-700">
                {roll.flaggedKeys.size} flag{roll.flaggedKeys.size === 1 ? "" : "s"} ·{" "}
                {money(roll.low)}–{money(roll.high)}
              </span>
            ) : (
              <span className="text-slate-400">No deferred maintenance flagged yet</span>
            )}
          </div>
          <button
            type="button"
            onClick={next}
            className="rounded-lg bg-slate-900 px-5 py-2.5 text-base font-semibold text-white"
          >
            {lastGroup ? (lastHome ? "Finish" : "Next home") : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}

// --- home switcher -----------------------------------------------------------

/** The address line doubles as the way to jump between homes: a native <select>, so it
 * is the iOS wheel picker and needs no screen of its own. Its last entry leaves for the
 * picker. */
function HomeSwitcher({
  ids,
  homes,
  current,
  onPick,
}: {
  ids: string[];
  homes: Record<string, FieldHome>;
  current: number;
  onPick: (i: number) => void;
}) {
  const navigate = useNavigate();
  return (
    <select
      value={String(current)}
      onChange={(e) => {
        if (e.target.value === "pick") {
          void navigate({ to: "/field", search: { ids: "", pick: true } });
        } else {
          onPick(Number(e.target.value));
        }
      }}
      aria-label="Switch home"
      className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-sm font-semibold text-slate-900"
    >
      {ids.map((id, i) => (
        <option key={id} value={String(i)}>
          {ids.length > 1 ? `${i + 1}. ` : ""}
          {homes[id]?.address ?? `Home ${i + 1}`}
        </option>
      ))}
      <option value="pick">Change homes…</option>
    </select>
  );
}

// --- status bar --------------------------------------------------------------

function StatusBar({
  online,
  pending,
  answers,
  loaded,
  total,
  syncState,
  onSync,
}: {
  online: boolean;
  pending: number;
  answers: number;
  /** homes of the set whose checklist is on this phone, of `total` */
  loaded: number;
  total: number;
  syncState: SyncState;
  onSync: () => void;
}) {
  let tone = "bg-slate-100 text-slate-600";
  let text: string;
  if (syncState === "syncing") {
    tone = "bg-sky-100 text-sky-800";
    text = "Saving…";
  } else if (!online) {
    tone = "bg-amber-100 text-amber-900";
    text = `No connection · ${answers} answer${answers === 1 ? "" : "s"} kept, saved when it's back`;
  } else if (syncState === "error") {
    tone = "bg-red-100 text-red-800";
    text = "Save failed — retrying";
  } else if (pending > 0) {
    tone = "bg-amber-100 text-amber-900";
    text = `${pending} home${pending === 1 ? "" : "s"} not saved yet`;
  } else if (syncState === "synced" || answers > 0) {
    tone = "bg-emerald-100 text-emerald-800";
    text = "All answers saved ✓";
  } else if (loaded < total) {
    text = `Loading ${loaded}/${total} homes…`;
  } else {
    text = `${total} home${total === 1 ? "" : "s"} loaded`;
  }
  return (
    <div className={"flex items-center justify-between rounded-lg px-3 py-1.5 text-xs " + tone}>
      <span>{text}</span>
      {online && pending > 0 && syncState !== "syncing" && (
        <button type="button" onClick={onSync} className="font-semibold underline">
          Save now
        </button>
      )}
    </div>
  );
}

// --- inputs ------------------------------------------------------------------

/** Sub-heading that separates the stacked sections within one grouped screen. */
function SectionHeading({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className="border-t border-slate-100 pt-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {blurb && <p className="mt-0.5 text-sm text-slate-500">{blurb}</p>}
    </div>
  );
}

function usePills(item: TourItem): boolean {
  // few, short options → one-tap segmented row; anything longer → the native
  // wheel picker, which iOS renders well and for free.
  return item.choices.length <= 4 && item.choices.every((c) => c.length <= 14);
}

function ItemInput({
  item,
  value,
  flagged,
  photoTaken,
  onChange,
  onPhoto,
}: {
  item: TourItem;
  value: unknown;
  flagged: boolean;
  photoTaken: boolean;
  onChange: (v: unknown) => void;
  onPhoto: (v: boolean) => void;
}) {
  return (
    <div
      className={
        "rounded-lg border p-3 " +
        (flagged ? "border-red-300 bg-red-50" : "border-slate-200 bg-white")
      }
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <span className="text-base font-medium text-slate-800">{item.label}</span>
        {flagged && (
          <span className="shrink-0 rounded bg-red-600 px-2 py-0.5 text-xs font-semibold text-white">
            check this
          </span>
        )}
      </div>
      {item.hint && <p className="mb-2 text-sm text-slate-500">{item.hint}</p>}

      {item.type === "choice" &&
        (usePills(item) ? (
          <div className="flex flex-wrap gap-2">
            {item.choices.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => onChange(value === c ? "" : c)}
                className={
                  "min-h-11 rounded-lg border px-4 py-2 text-base " +
                  (value === c
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-300 bg-white text-slate-700")
                }
              >
                {c}
              </button>
            ))}
          </div>
        ) : (
          <select
            className="min-h-12 w-full rounded-lg border border-slate-300 bg-white px-3 text-base"
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value)}
          >
            <option value="">—</option>
            {item.choices.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        ))}

      {item.type === "bool" && (
        <button
          type="button"
          onClick={() => onChange(value === true ? "" : true)}
          className={
            "flex min-h-12 w-full items-center justify-between rounded-lg border px-4 text-base " +
            (value === true
              ? "border-slate-900 bg-slate-900 text-white"
              : "border-slate-300 bg-white text-slate-700")
          }
        >
          <span>{value === true ? "Yes" : "Tap if yes"}</span>
          <span className="text-xl">{value === true ? "✓" : "○"}</span>
        </button>
      )}

      {item.type === "rating" && (
        <div className="flex gap-2">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => onChange(value === n ? "" : n)}
              className={
                "h-12 flex-1 rounded-lg border text-lg font-semibold " +
                (value === n
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 bg-white text-slate-600")
              }
            >
              {n}
            </button>
          ))}
        </div>
      )}

      {item.type === "number" && (
        <input
          type="number"
          inputMode="numeric"
          className="min-h-12 w-full rounded-lg border border-slate-300 px-3 text-base"
          defaultValue={value === undefined || value === null ? "" : String(value)}
          onBlur={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        />
      )}

      {item.type === "text" && (
        <textarea
          rows={3}
          className="w-full rounded-lg border border-slate-300 p-3 text-base"
          defaultValue={(value as string) ?? ""}
          onBlur={(e) => onChange(e.target.value)}
        />
      )}

      {item.photo && (
        <button
          type="button"
          onClick={() => onPhoto(!photoTaken)}
          className={
            "mt-2 flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm " +
            (photoTaken ? "border-sky-500 bg-sky-50 text-sky-800" : "border-slate-200 text-slate-600")
          }
        >
          <span className="text-lg">{photoTaken ? "☑" : "☐"}</span>
          <span>Photo: {item.photo}</span>
        </button>
      )}
    </div>
  );
}

function AgentQA({
  home,
  tour,
  onAnswer,
}: {
  home: FieldHome;
  tour: LocalTour;
  onAnswer: (i: number, v: string) => void;
}) {
  return (
    <div className="space-y-3">
      {home.spec.agent_questions.map((q, i) => (
        <div key={q} className="rounded-lg border border-slate-200 bg-white p-3">
          <label className="mb-2 block text-base font-medium text-slate-800">
            {i === 3 && (
              <span className="mr-2 rounded bg-slate-900 px-1.5 py-0.5 text-xs font-semibold text-white">
                key
              </span>
            )}
            {q}
          </label>
          <textarea
            rows={2}
            className="w-full rounded-lg border border-slate-300 p-3 text-base"
            defaultValue={tour.agent_answers[String(i)] ?? ""}
            onBlur={(e) => onAnswer(i, e.target.value)}
          />
        </div>
      ))}
    </div>
  );
}

function VerdictControls({
  tour,
  onGut,
  onVerdict,
}: {
  tour: LocalTour;
  onGut: (n: number) => void;
  onVerdict: (v: string) => void;
}) {
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
      <div>
        <div className="mb-2 text-base font-medium text-slate-800">Gut score</div>
        <div className="flex gap-2">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => onGut(n)}
              className={
                "h-12 flex-1 rounded-lg border text-lg font-semibold " +
                (tour.gut_score === n
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 bg-white text-slate-600")
              }
            >
              {n}
            </button>
          ))}
        </div>
      </div>
      <div>
        <div className="mb-2 text-base font-medium text-slate-800">Verdict</div>
        <div className="flex gap-2">
          {["offer", "maybe", "pass"].map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => onVerdict(tour.verdict === v ? "" : v)}
              className={
                "min-h-12 flex-1 rounded-lg border text-base font-semibold capitalize " +
                (tour.verdict === v
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 bg-white text-slate-700")
              }
            >
              {v}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function NotesField({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 text-base font-medium text-slate-800">Notes</div>
      <textarea
        rows={3}
        className="w-full rounded-lg border border-slate-300 p-3 text-base"
        placeholder="Voice-memo transcript, anything the checklist missed…"
        defaultValue={value}
        onBlur={(e) => onSave(e.target.value)}
      />
    </div>
  );
}

function RollupSummary({
  roll,
  cmaEstimate,
}: {
  roll: ReturnType<typeof rollupFlags>;
  cmaEstimate: number | null;
}) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">
      <div className="mb-1 font-semibold">
        Deferred maintenance · {money(roll.low)}–{money(roll.high)}
      </div>
      <ul className="space-y-0.5">
        {roll.bands.map((b) => (
          <li key={b.key} className="flex justify-between">
            <span>{b.label}</span>
            <span className="tabular-nums">
              {money(b.low)}–{money(b.high)}
            </span>
          </li>
        ))}
      </ul>
      {cmaEstimate != null && (
        <p className="mt-2">
          CMA {money(cmaEstimate, false)} → condition-adjusted{" "}
          <span className="font-semibold">
            {money(cmaEstimate - roll.high, false)}–{money(cmaEstimate - roll.low, false)}
          </span>
        </p>
      )}
      <p className="mt-1 text-xs text-red-800">Estimates, not quotes.</p>
    </div>
  );
}

/** Clipboard write that works on both origins: navigator.clipboard needs a secure
 * context (the home server's HTTPS front door has one; a plain-http LAN origin does
 * not), so fall back to execCommand there. Either way the raw JSON is always shown to
 * select by hand. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    /* fall through */
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

function BackupControls({
  show,
  setShow,
  json,
}: {
  show: boolean;
  setShow: (v: boolean) => void;
  json: () => string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={async () => setCopied(await copyText(json()))}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700"
        >
          Copy answers
        </button>
        <button
          type="button"
          onClick={() => setShow(!show)}
          className="text-sm text-slate-500 underline"
        >
          {show ? "hide" : "show"}
        </button>
        {copied && <span className="text-sm text-emerald-700">✓ copied</span>}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Copies every answer here as text, in case some ever fail to save.
      </p>
      {show && (
        <textarea
          readOnly
          rows={8}
          value={json()}
          onFocus={(e) => e.currentTarget.select()}
          className="mt-2 w-full rounded border border-slate-300 p-2 font-mono text-xs"
        />
      )}
    </div>
  );
}

/** Paper fallback: the whole checklist, printable, for when a phone dies mid-tour.
 * Hidden on screen; the only thing @media print shows. */
function PrintSheet({
  ids,
  homes,
  answers,
}: {
  ids: string[];
  homes: Record<string, FieldHome>;
  answers: Record<string, LocalTour>;
}) {
  return (
    <div className="hidden print:block">
      {ids.map((id) => {
        const home = homes[id];
        if (!home) return null;
        const tour = answers[id];
        const val = (k: string) => {
          const v = tour?.checklist[k];
          return v === undefined || v === null || v === "" ? "____________" : String(v);
        };
        return (
          <div key={id} className="mb-6" style={{ pageBreakAfter: "always" }}>
            <h2 className="text-lg font-bold">{home.address}</h2>
            {home.spec.sections.map((s) => (
              <div key={s.key} className="mt-3">
                <h3 className="font-semibold underline">{s.title}</h3>
                {s.items.map((it) => (
                  <div key={it.key} className="text-sm">
                    {it.label}: {val(it.key)}
                    {it.choices.length > 0 && ` (${it.choices.join(" / ")})`}
                  </div>
                ))}
              </div>
            ))}
            <div className="mt-3">
              <h3 className="font-semibold underline">Questions for the agent</h3>
              {home.spec.agent_questions.map((q, i) => (
                <div key={q} className="text-sm">
                  {q}: {tour?.agent_answers[String(i)] || "____________"}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

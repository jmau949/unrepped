import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import {
  addListingContact,
  deleteListingContact,
  CONTACT_KINDS,
  type Contact,
  type ContactPhone,
  type ListingDetail,
} from "../api/client";
import { copyText } from "../lib/clipboard";
import { useConfig } from "../lib/config";
import { phone as fmtPhone } from "../lib/format";

const CARD = "rounded-lg border border-slate-200 bg-white p-4";
const H2 = "mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500";
const FIELD = "rounded border border-slate-300 px-2 py-1 text-sm";
const LINK = "text-sky-700 underline hover:text-sky-900";
const BTN = "rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50";

const telUrl = (digits: string) => `tel:+1${digits}`;

/**
 * Who to call about this house, and on what footing (docs/08 §3 1c).
 *
 * The listing agent's direct line and email come off the MLS record the scan
 * already stores; the links are plain tel:/sms:/mailto: so first contact never
 * runs through a portal "Contact agent" form — those hand you to a buyer's
 * agent and a representation agreement with a fee (docs/14 §2.3).
 */
export default function ContactPanel({
  listing,
  onChanged,
}: {
  listing: ListingDetail;
  onChanged: () => void;
}) {
  const side = listing.listing_contact;
  const agent = side?.agent ?? null;
  const office = side?.office ?? null;
  const reach = agent ?? office; // whoever the record names
  const config = useConfig();
  // Free owner-of-record lookups, every configured county: `properties` carries no
  // county, and a wrong-county link is worse than several labelled ones.
  const assessors = (config.data?.geography.counties ?? []).flatMap((c) =>
    c.assessor_url ? [{ label: c.assessor_label || `${c.name} Assessor`, href: c.assessor_url }] : [],
  );
  const email = agent?.email ?? office?.email ?? null;
  const mlsLabel = side?.mls ? [side.mls.system, side.mls.id].filter(Boolean).join(" ") : "";

  return (
    <section className={CARD}>
      <h2 className={H2}>Contact the listing side</h2>

      {side && reach ? (
        <div className="space-y-1 text-sm">
          <p>
            <span className="font-semibold">{reach.name}</span>
            {agent && office && <span className="text-slate-500"> · {office.name}</span>}
            {side.broker && <span className="text-slate-500"> · {side.broker.name}</span>}
            {mlsLabel && <span className="text-slate-500"> · MLS {mlsLabel}</span>}
          </p>
          {reach.phones.length > 0 && (
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1">
              {reach.phones.map((p) => <PhoneLine key={p.number} p={p} />)}
            </p>
          )}
          {email && (
            <p className="flex flex-wrap items-center gap-2">
              <a href={`mailto:${email}`} className={LINK}>{email}</a>
              <span className="text-xs text-slate-400">email on the listing</span>
              <CopyButton text={email} />
            </p>
          )}
          {agent && office && (office.phones.length > 0 || office.email) && (
            <p className="text-xs text-slate-500">
              Office:{" "}
              {office.phones.map((p, i) => (
                <span key={p.number}>
                  {i > 0 && " · "}
                  <a href={telUrl(p.number)} className={LINK}>{fmtPhone(p.number)}</a>
                </span>
              ))}
              {office.email && (
                <>
                  {office.phones.length > 0 && " · "}
                  <a href={`mailto:${office.email}`} className={LINK}>
                    {office.email}
                  </a>
                </>
              )}
            </p>
          )}
          {side.builder && <p className="text-xs text-slate-500">Builder: {side.builder.name}</p>}
        </div>
      ) : (
        <p className="text-sm text-slate-500">
          No agent on the source record for this listing. Add one by hand below, or look up the
          owner of record.
        </p>
      )}

      <SavedContacts listing={listing} onChanged={onChanged} />

      {assessors.length > 0 && (
        <p className="mt-3 text-xs text-slate-500">
          Owner of record, free:{" "}
          {assessors.map((l, i) => (
            <span key={l.href}>
              {i > 0 && " · "}
              <a href={l.href} target="_blank" rel="noreferrer" className={LINK}>{l.label} ↗</a>
            </span>
          ))}
          {" "}— search by address; if the portal withholds the owner's name, the Assessor's office
          provides it on request. Save the name here as an <span className="font-medium">owner</span>{" "}
          contact. No paid skip-trace.
        </p>
      )}
    </section>
  );
}

function PhoneLine({ p }: { p: ContactPhone }) {
  return (
    <span className="inline-flex items-center gap-1">
      <a href={telUrl(p.number)} className={LINK}>{fmtPhone(p.number)}</a>
      <span className="text-xs text-slate-400">{p.type.replace("_", " ")}</span>
      <CopyButton text={fmtPhone(p.number)} />
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <button
      type="button"
      className={BTN}
      onClick={async () => {
        setState((await copyText(text)) ? "copied" : "failed");
        setTimeout(() => setState("idle"), 2500);
      }}
    >
      {state === "copied" ? "✓ copied" : state === "failed" ? "failed" : "copy"}
    </button>
  );
}

/** Contacts saved on this listing by hand — the owner of record, a second agent,
 * the person who actually answered the phone. Same table and kinds as the deal
 * team; a deal on this listing inherits these rows. */
function SavedContacts({ listing, onChanged }: { listing: ListingDetail; onChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState("listing_agent");
  const addMut = useMutation({
    mutationFn: (body: Parameters<typeof addListingContact>[1]) =>
      addListingContact(listing.id, body),
    onSuccess: () => setAdding(false),
    onSettled: onChanged,
  });
  const delMut = useMutation({
    mutationFn: (id: string) => deleteListingContact(listing.id, id),
    onSettled: onChanged,
  });

  return (
    <div className="mt-3">
      {listing.contacts.length > 0 && (
        <table className="w-full text-sm">
          <tbody>
            {listing.contacts.map((c: Contact) => (
              <tr key={c.id} className="border-t border-slate-100">
                <td className="py-1 pr-2 text-slate-500">{c.kind.replace("_", " ")}</td>
                <td className="py-1 pr-2 font-medium">{c.name}</td>
                <td className="py-1 pr-2 text-slate-500">{c.company}</td>
                <td className="py-1 pr-2 tabular-nums">
                  {c.phone && <a href={`tel:${c.phone}`} className={LINK}>{c.phone}</a>}
                </td>
                <td className="py-1 pr-2">
                  {c.email && <a href={`mailto:${c.email}`} className={LINK}>{c.email}</a>}
                </td>
                <td className="py-1 pr-2 text-xs text-slate-400">{c.notes}</td>
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
      )}

      {adding ? (
        <form
          className="mt-2 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            const name = String(f.get("name") ?? "").trim();
            if (!name) return;
            addMut.mutate({
              kind,
              name,
              company: String(f.get("company") ?? ""),
              phone: String(f.get("phone") ?? ""),
              email: String(f.get("email") ?? ""),
              notes: String(f.get("notes") ?? ""),
            });
          }}
        >
          <select className={FIELD} value={kind} onChange={(e) => setKind(e.target.value)}>
            {CONTACT_KINDS.map((k) => (
              <option key={k} value={k}>{k.replace("_", " ")}</option>
            ))}
          </select>
          <input name="name" className={FIELD} placeholder="name" />
          <input name="company" className={FIELD} placeholder="company" />
          <input name="phone" className={FIELD} placeholder="phone" />
          <input name="email" className={FIELD} placeholder="email" />
          <input name="notes" className={FIELD} placeholder="notes" />
          <button className="rounded bg-slate-800 px-3 py-1 text-sm text-white" type="submit">
            Add
          </button>
          <button type="button" className="text-sm text-slate-500" onClick={() => setAdding(false)}>
            Cancel
          </button>
          {kind === "owner" && (
            <p className="w-full text-xs text-slate-500">
              The owner's name comes from the county assessor roll (free) — search by address
              using the links below.
            </p>
          )}
        </form>
      ) : (
        <button className="mt-2 text-sm text-sky-700 underline" onClick={() => setAdding(true)}>
          + Add contact
        </button>
      )}
    </div>
  );
}

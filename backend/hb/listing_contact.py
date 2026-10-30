"""listing_contact — the listing side, read out of `listings.raw`.

Realtor.com's `advertisers` block arrives flattened by HomeHarvest as
`agent_name/agent_email/agent_phones/agent_mls_set/agent_nrds_id`,
`office_name/office_email/office_phones`, `broker_name`, `builder_name`, plus
`mls`/`mls_id` — and the scan keeps every one of them verbatim in `raw`
(docs/05 §4.2). This module is the only reader. It normalizes the messy phone
records (a dozen spellings of "mobile", fax lines, `(650) 555-0177` next to
`6505550177`) into one shape the detail page can turn into `tel:`/`sms:` links.

Why this exists at all: a buyer with no agent contacts the listing agent
directly. That is the one route that creates no buyer-broker agreement and no
commission (docs/14 §2.3) — the portals' "Contact agent" buttons route to a
buyer's agent instead. Pure functions; no session, no network.
"""

import re

_NON_DIGIT = re.compile(r"\D")

# Source `type` labels seen live, lowercased -> ours. Anything else is "other".
PHONE_TYPES = {
    "mobile": "mobile", "cell": "mobile",
    "business_mobile": "mobile", "personal_mobile": "mobile",
    "office": "office", "business_phone": "office", "home office": "office",
    "home": "home", "personal_phone": "home",
    "tfn": "toll_free", "toll free": "toll_free",
    "fax": "fax",
}
_TYPE_RANK = {"mobile": 0, "office": 1, "home": 2, "toll_free": 3, "other": 4}


def digits(number) -> str | None:
    """`(650) 555-0177` / `+1 650 555 0123` -> ten digits, or None if it isn't a US number."""
    if number is None:
        return None
    raw = _NON_DIGIT.sub("", str(number))
    if len(raw) == 11 and raw.startswith("1"):
        raw = raw[1:]
    return raw if len(raw) == 10 else None


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_phones(value) -> list[dict]:
    """Raw phone list -> [{number, type, primary, sms}], primary first then by type.

    Fax lines and unparseable numbers are dropped, duplicates collapse to the
    first occurrence, and anything that is not a list (including the repr
    strings the scan used to write) yields [] — there is no second format.
    """
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    phones: list[dict] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        number = digits(entry.get("number"))
        if number is None or number in seen:
            continue
        kind = PHONE_TYPES.get(str(entry.get("type") or "").strip().lower(), "other")
        if kind == "fax":
            continue
        seen.add(number)
        phones.append({
            "number": number,
            "type": kind,
            "primary": bool(entry.get("primary")),
            "sms": kind == "mobile",
        })
    phones.sort(key=lambda p: (not p["primary"], _TYPE_RANK[p["type"]]))
    return phones


def from_raw(raw: dict | None) -> dict | None:
    """The listing side as the detail page shows it, or None when the source
    record carried no advertiser (Realtor drops the block on ~1 in 4 listings)."""
    raw = raw or {}
    agent_name = _clean(raw.get("agent_name"))
    office_name = _clean(raw.get("office_name"))
    if not agent_name and not office_name:
        return None

    agent = {
        "name": agent_name,
        "email": _clean(raw.get("agent_email")),
        "phones": normalize_phones(raw.get("agent_phones")),
        "mls_id": _clean(raw.get("agent_mls_set")),
        "nrds_id": _clean(raw.get("agent_nrds_id")),
    } if agent_name else None
    office = {
        "name": office_name,
        "email": _clean(raw.get("office_email")),
        "phones": normalize_phones(raw.get("office_phones")),
    } if office_name else None
    broker_name = _clean(raw.get("broker_name"))
    builder_name = _clean(raw.get("builder_name"))
    mls_system = _clean(raw.get("mls"))
    mls_id = _clean(raw.get("mls_id"))
    return {
        "agent": agent,
        "office": office,
        "broker": {"name": broker_name} if broker_name else None,
        "builder": {"name": builder_name} if builder_name else None,
        "mls": {"system": mls_system, "id": mls_id} if (mls_system or mls_id) else None,
    }

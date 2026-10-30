"""realtor_gql — shared Realtor.com frontdoor GraphQL access.

Both `price_history` and `enrich` talk to Realtor's `frontdoor/graphql` with
homeharvest's browser `DEFAULT_HEADERS` (no auth token — the exact path the
working scan uses) and resolve an address to Realtor's `mpr_id`. This module
holds that shared plumbing so the two pipelines don't duplicate it.
"""

import json

import httpx

from homeharvest.core.scrapers import DEFAULT_HEADERS
from homeharvest.core.scrapers.realtor.queries import SEARCH_SUGGESTIONS_QUERY
from hb.db.models import Property

URL = "https://www.realtor.com/frontdoor/graphql"


def post(query: str, variables: dict, op: str) -> dict:
    payload = {"operationName": op, "query": " ".join(query.split()), "variables": variables}
    resp = httpx.post(URL, headers=DEFAULT_HEADERS, content=json.dumps(payload), timeout=10)
    resp.raise_for_status()
    return resp.json()


def resolve_mpr_id(address: str) -> str | None:
    """Address -> Realtor property (mpr) id via the search-suggestions query."""
    j = post(SEARCH_SUGGESTIONS_QUERY, {"searchInput": {"search_term": address}},
             "Search_suggestions")
    geos = ((j.get("data") or {}).get("search_suggestions") or {}).get("geo_results") or []
    for g in geos:
        geo = g.get("geo") or {}
        if geo.get("area_type") == "address" and geo.get("mpr_id"):
            return geo["mpr_id"]
    return None


def mpr_id_for(prop: Property) -> str | None:
    """The Realtor mpr id the scan stored on the property (in `source_ids`)."""
    ids = prop.source_ids or {}
    return ids.get("realtor_mpr") or next(iter(ids.get("realtor") or []), None)

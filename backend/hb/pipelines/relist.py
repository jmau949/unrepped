"""Relist stitching — docs/05-pipelines.md §6.

Rebuilds listing_groups deterministically for a set of properties: episodes
ordered by list_date; an episode starting < 90 days after the previous
episode's end (and with no intervening sale) joins its group. cumulative_dom
is the true market exposure the public DOM counter hides.

Idempotency: group membership + fields are recomputed from the listings table
(no incremental state); the `relisted` event fires only on a listing's
NULL -> existing-group transition, so re-runs emit nothing.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.db.models import Listing, ListingEvent, ListingGroup

log = logging.getLogger(__name__)

RELIST_GAP_DAYS = 90


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _episode_end(ep: Listing) -> date | None:
    """When the episode left the market (None = still active)."""
    return _d(ep.sold_date) or _d(ep.pending_date) or _d(ep.delist_date)


def _cluster(episodes: list[Listing]) -> list[list[Listing]]:
    clusters: list[list[Listing]] = []
    for ep in episodes:
        if not clusters:
            clusters.append([ep])
            continue
        prev = clusters[-1][-1]
        prev_end = _episode_end(prev)
        ep_start = _d(ep.list_date)
        ended_by_sale = prev.status == "sold" or prev.sold_date is not None
        if (
            not ended_by_sale
            and prev_end is not None
            and ep_start is not None
            and 0 <= (ep_start - prev_end).days < RELIST_GAP_DAYS
        ):
            clusters[-1].append(ep)
        else:
            clusters.append([ep])
    return clusters


def stitch(session: Session, property_ids: set[str], observed_at: str) -> int:
    """Rebuild groups for the given properties. Returns events emitted."""
    events = 0
    today = date.today()

    for property_id in sorted(property_ids):
        episodes = session.execute(
            select(Listing)
            .where(Listing.property_id == property_id, Listing.list_date.is_not(None))
            .order_by(Listing.list_date)
        ).scalars().all()
        if not episodes:
            continue

        for cluster in _cluster(episodes):
            # reuse an existing group row if any member already has one
            group_id = next((ep.listing_group_id for ep in cluster if ep.listing_group_id), None)
            group = session.get(ListingGroup, group_id) if group_id else None
            if group is None:
                group = ListingGroup(property_id=property_id)
                session.add(group)
                session.flush()

            cumulative = 0
            for ep in cluster:
                start = _d(ep.list_date)
                end = _episode_end(ep) or today
                cumulative += max(0, (min(end, today) - start).days)

            group.first_list_date = cluster[0].list_date[:10]
            group.episode_count = len(cluster)
            group.cumulative_dom = cumulative
            last = cluster[-1]
            group.ended_by = (
                "sale" if (last.status == "sold" or last.sold_date)
                else "withdrawn" if last.status == "delisted"
                else "open"
            )

            for i, ep in enumerate(cluster):
                joining = ep.listing_group_id is None
                if ep.listing_group_id != group.id:
                    ep.listing_group_id = group.id
                # a later episode newly joining a multi-episode group = a relist
                if joining and i > 0:
                    prev_end = _episode_end(cluster[i - 1])
                    session.add(ListingEvent(
                        listing_id=ep.id,
                        event_type="relisted",
                        old_value=prev_end.isoformat() if prev_end else None,
                        new_value=ep.list_date[:10],
                        observed_at=observed_at,
                    ))
                    events += 1

    return events

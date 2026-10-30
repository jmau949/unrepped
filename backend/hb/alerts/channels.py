"""Alert delivery — docs/09-alerts-spec.md §4–5.

Alerts are rows first; delivery is a separate, retry-safe step: a failed
channel leaves rows undelivered for the next `hb alerts send`.
"""

import logging
import platform
import smtplib
from email.mime.text import MIMEText

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from hb.config import settings
from hb.db.models import Alert, Listing, Property, utcnow_iso

log = logging.getLogger(__name__)

DIGEST_THRESHOLD = 3  # email only: more pending than this is one digest email


def format_alert(session: Session, alert: Alert) -> str:
    """Plain-language one-liner per docs/09 §5."""
    listing = session.get(Listing, alert.listing_id) if alert.listing_id else None
    prop = session.get(Property, listing.property_id) if listing else None
    addr = f"{prop.address_norm.title()}, {prop.city}" if prop else "unknown address"
    p = alert.payload or {}

    if alert.type == "price_cut":
        return (f"↓ ${p.get('old', 0) - p.get('new', 0):,} ({p.get('pct', 0):.1%}) — {addr} "
                f"now ${p.get('new', 0):,}. Cut #{p.get('cut_count', 1)}.")
    if alert.type == "relist":
        return (f"Relisted — {addr}. True cumulative DOM {p.get('cumulative_dom')} across "
                f"{p.get('episode_count')} episodes.")
    if alert.type == "back_on_market":
        return f"Back on market — {addr}."
    if alert.type == "new_listing_match":
        return (f"New match — {addr} ({p.get('zip')}): ${p.get('price', 0):,}, "
                f"{p.get('beds')}bd, {p.get('sqft')} sqft.")
    if alert.type == "offer_date_soon":
        return f"Offer date in {p.get('days_left')} day(s) — {addr} (due {p.get('due')})."
    if alert.type == "deal_deadline_soon":
        flag = "BLOCKING — " if p.get("blocking") else ""
        return (f"{flag}{p.get('label')} due in {p.get('days_left')} day(s) — {addr} "
                f"(due {p.get('due')}).")
    if alert.type == "deal_deadline_overdue":
        return (f"OVERDUE — {p.get('label')} was due {p.get('due')} — {addr}. "
                f"A missed contingency date can cost the deposit.")
    if alert.type == "watched_status":
        return _watched_status(p, addr)
    if alert.type == "scan_failure":
        return "The last 2 listing scans failed — check the Data Log."
    return f"{alert.type} — {addr}"


def _watched_status(p: dict, addr: str) -> str:
    event = p.get("event")
    if event == "sold" and p.get("sold_price"):
        sold, ask = p["sold_price"], p.get("original_list_price")
        vs_ask = f" ({sold / ask - 1:+.1%} vs original ask)" if ask else ""
        msg = f"Watched home sold — {addr} for ${sold:,}{vs_ask}."
        if p.get("my_max_bid"):
            gap = sold - p["my_max_bid"]
            msg += f" ${abs(gap):,} {'over' if gap > 0 else 'under'} your max bid."
        return msg
    if event == "sold":
        return f"Watched home sold — {addr}; price not published yet."
    if event == "pending":
        return f"Watched home went pending — {addr}, asking ${p.get('list_price') or 0:,}."
    return f"Watched home taken off the market — {addr}."


def _url(alert: Alert) -> str:
    return (f"{settings.app_base_url}/listings/{alert.listing_id}"
            if alert.listing_id else settings.app_base_url)


def send_toast(title: str, message: str, url: str) -> bool:
    if platform.system() != "Windows":
        return False
    try:
        from win11toast import toast

        toast(title, message, on_click=url)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("toast failed: %s", exc)
        return False


def send_log(title: str, message: str, url: str) -> bool:
    """The portable channel: one INFO line per alert, on every OS. It always
    succeeds, so with `log` enabled an alert is marked delivered on first pass
    even where toast (Windows-only) silently cannot show it."""
    log.info("alert [%s] %s -> %s", title, message, url)
    return True


PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def _pushover_post(data: dict) -> httpx.Response:
    """The network seam: tests replace this."""
    return httpx.post(PUSHOVER_URL, data=data, timeout=30)


def send_pushover(title: str, message: str, url: str) -> bool:
    """Phone push via Pushover, one per alert, the listing page as the tap-through.
    Unconfigured, rejected (4xx / status != 1) or unreachable all count as a
    failed channel, so the row stays pending for the next run."""
    if not (settings.pushover_token and settings.pushover_user):
        return False
    try:
        resp = _pushover_post({
            "token": settings.pushover_token,
            "user": settings.pushover_user,
            "title": title[:250],
            "message": message[:1024],
            "url": url[:512],
            "url_title": "Open",
        })
        if resp.status_code == 200 and resp.json().get("status") == 1:
            return True
        log.warning("pushover failed: HTTP %s %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("pushover failed: %s", exc)
        return False


def send_email(subject: str, html: str) -> bool:
    if not (settings.smtp_host and settings.smtp_user and settings.alert_email_to):
        return False
    try:
        msg = MIMEText(html, "html")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_user
        msg["To"] = settings.alert_email_to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("email failed: %s", exc)
        return False


def deliver_pending(session: Session) -> int:
    """Deliver undelivered alerts via enabled channels; returns delivered count.

    One toast, one push and one log line per alert, each linking to its
    listing. Email alone digests: more than DIGEST_THRESHOLD pending is one
    email listing them all. Each alert is committed as it is delivered, so the
    database's write lock is never held while a toast is on screen (it blocks
    until dismissed) and the API keeps writing meanwhile."""
    channels = [c.strip() for c in settings.alert_channels.split(",") if c.strip()]
    pending = session.execute(
        select(Alert).where(Alert.delivered_at.is_(None)).order_by(Alert.created_at)
    ).scalars().all()
    if not pending:
        return 0

    use_digest = "email" in channels and len(pending) > DIGEST_THRESHOLD
    digest_ok = False
    if use_digest:
        items = "".join(
            f'<li><a href="{_url(a)}">{format_alert(session, a)}</a></li>' for a in pending
        )
        digest_ok = send_email(f"[home-buying] {len(pending)} alerts", f"<ul>{items}</ul>")

    delivered = 0
    for alert in pending:
        title = alert.type.replace("_", " ")
        message = format_alert(session, alert)
        url = _url(alert)
        ok_channels = []
        if "toast" in channels and send_toast(title, message, url):
            ok_channels.append("toast")
        if "pushover" in channels and send_pushover(title, message, url):
            ok_channels.append("pushover")
        if "log" in channels and send_log(title, message, url):
            ok_channels.append("log")
        if "email" in channels:
            if use_digest:
                if digest_ok:
                    ok_channels.append("email")
            elif send_email(f"[home-buying] {alert.type}", f'<a href="{url}">{message}</a>'):
                ok_channels.append("email")
        if ok_channels:
            alert.delivered_at = utcnow_iso()
            alert.channel = ",".join(ok_channels)
            delivered += 1
            session.commit()  # per alert: the write lock is free again at once

    log.info("delivered %d/%d alerts", delivered, len(pending))
    return delivered

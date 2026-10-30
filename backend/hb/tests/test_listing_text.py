"""Signals parsed out of the listing remarks (docs/05 §4.7)."""

from hb.db.models import Property
from hb.pipelines.listing_text import (
    AUTO_PREFIX, apply_condition, classify_condition, parse_offer_due,
)


# --- condition ---------------------------------------------------------------

def test_condition_renovated():
    tag, evidence = classify_condition(
        "Stunning home, fully remodeled in 2023 with a new kitchen and new roof."
    )
    assert tag == "renovated"
    assert "remodeled" in evidence


def test_condition_fixer():
    tag, _ = classify_condition(
        "Contractor special! Needs work throughout. Bring your contractor and vision."
    )
    assert tag == "fixer"


def test_condition_dated():
    tag, _ = classify_condition(
        "Owned by the same family for 52 years. In original condition and ready "
        "for your personal touch."
    )
    assert tag == "dated"


def test_condition_tie_is_unknown():
    """A coin-flip tag moves a comp by 7% — silence is the safer answer."""
    tag, evidence = classify_condition(
        "Remodeled kitchen; the bathrooms need work."
    )
    assert tag is None and evidence is None


def test_condition_no_signal():
    assert classify_condition("Charming home near parks and shops.") == (None, None)
    assert classify_condition(None) == (None, None)
    assert classify_condition("") == (None, None)


def test_condition_wins_on_weight_not_order():
    tag, _ = classify_condition(
        "Needs TLC. Deferred maintenance throughout, sold strictly as-is. "
        "The kitchen was remodeled in 1998."
    )
    assert tag == "fixer"  # 3 fixer phrases vs 1 renovated


# --- apply_condition guards --------------------------------------------------

def _prop(**over):
    p = Property(address_norm="1 X ST", zip="94087")
    for k, v in over.items():
        setattr(p, k, v)
    return p


def test_apply_writes_tag_and_evidence():
    prop = _prop()
    assert apply_condition(prop, "Beautifully remodeled with a new kitchen.") is True
    assert prop.condition_tag == "renovated"
    assert prop.condition_notes.startswith(AUTO_PREFIX)


def test_apply_never_overwrites_a_hand_entered_tag():
    prop = _prop(condition_tag="fixer", condition_notes="toured 8/2 - roof is shot")
    assert apply_condition(prop, "Beautifully remodeled with a new kitchen.") is False
    assert prop.condition_tag == "fixer"


def test_apply_treats_a_bare_manual_tag_as_owned():
    """A tag set in the UI with no note is still a human's call."""
    prop = _prop(condition_tag="dated", condition_notes=None)
    assert apply_condition(prop, "Fully remodeled, new roof.") is False
    assert prop.condition_tag == "dated"


def test_apply_may_revise_its_own_earlier_inference():
    prop = _prop(condition_tag="dated", condition_notes=f"{AUTO_PREFIX}dated")
    assert apply_condition(prop, "Fully remodeled, new kitchen, new roof.") is True
    assert prop.condition_tag == "renovated"


def test_apply_is_idempotent():
    prop = _prop()
    text = "Beautifully remodeled with a new kitchen."
    assert apply_condition(prop, text) is True
    assert apply_condition(prop, text) is False  # no change on a re-scan


# --- offer date --------------------------------------------------------------

def test_offer_due_numeric():
    assert parse_offer_due("Offers due 7/21 at 5pm.", "2026-07-14") == "2026-07-21"


def test_offer_due_month_name_with_ordinal():
    assert parse_offer_due(
        "Please submit offers by Tuesday, July 21st at noon.", "2026-07-14"
    ) == "2026-07-21"


def test_offer_due_explicit_year():
    assert parse_offer_due("Offer date: 7/21/26.", "2026-07-14") == "2026-07-21"


def test_offer_due_rolls_across_new_year():
    assert parse_offer_due(
        "Offers will be reviewed on 1/8.", "2025-12-20"
    ) == "2026-01-08"


def test_offer_due_explicit_none_is_respected():
    assert parse_offer_due(
        "No offer date - offers reviewed as they come.", "2026-07-14"
    ) is None


def test_offer_due_requires_a_trigger_phrase():
    """A bare date in the prose is not a deadline."""
    assert parse_offer_due("Built 7/21 of last century.", "2026-07-14") is None


def test_offer_due_rejects_an_implausible_date():
    """Parsed cleanly but nowhere near the listing — discard rather than guess."""
    assert parse_offer_due("Offers due 1/2/2019.", "2026-07-14") is None


def test_offer_due_needs_an_anchor():
    assert parse_offer_due("Offers due 7/21.", None) is None
    assert parse_offer_due(None, "2026-07-14") is None

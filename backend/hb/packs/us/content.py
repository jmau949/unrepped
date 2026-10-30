"""Misc. state-neutral content for the `us` base pack: what the AI brief says is
attached, the Tracker's disclosure checklist, affordability notes."""

from hb.packs.types import Affordability, ChecklistField, Content

CONTENT = Content(
    disclosure_packet=(
        "the full disclosure packet PDF",
        "pest / wood-destroying-organism report — the **active damage** total and the "
        "preventive items, separately",
        "the seller's property disclosure statement",
        "any seller-side home inspection, roof certification, or chimney report",
        "sewer lateral video and any compliance certificate",
        "permit history from the city (and what is NOT permitted)",
        "preliminary title report or title commitment — easements, CC&Rs",
        "HOA docs, if any",
    ),
    brief_tax_note=("Expect reassessment after close — most counties reset the assessed "
                    "value toward the purchase price, and some bill the difference "
                    "back to the closing date."),
    attorney_phrase="a real estate attorney licensed in your state",
    # Keys are the storage contract for tracked_listings.disclosure_checklist.
    tracker_checklist=(
        ChecklistField("packet_received", "Disclosure packet received", "bool"),
        ChecklistField("seller_disclosure_read", "Seller disclosure statement read", "bool"),
        ChecklistField("pest_section1_total", "Pest active-damage total ($)", "number"),
        ChecklistField("hoa_docs", "HOA docs", "text"),
        ChecklistField("insurance_quoted", "Insurance quoted", "bool"),
    ),
)

AFFORDABILITY = Affordability(
    earthquake_monthly_default=150,
    optional_insurance_label="include an excluded-peril rider (flood / earthquake)",
    supplemental_tax_note=(
        "Reassessment after sale: most counties reset the assessed value toward your "
        "purchase price on their own schedule, so a first-year catch-up bill on the order "
        "of ${amount:,} is possible — confirm the timing with the county assessor."
    ),
)

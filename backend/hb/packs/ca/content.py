"""Misc. California content for the `ca` pack."""

from hb.packs.types import Affordability, ChecklistField, Content

CONTENT = Content(
    disclosure_packet=(
        "the full disclosure packet PDF",
        "pest report — the **Section 1** (active damage) and **Section 2** (preventive) totals",
        "TDS and SPQ (the seller's own disclosures)",
        "NHD natural-hazard report",
        "any seller-side home inspection, roof certification, or chimney report",
        "sewer lateral video and compliance certificate",
        "permit history from the city (and what is NOT permitted)",
        "preliminary title report — easements, CC&Rs",
        "HOA docs, if any",
    ),
    brief_tax_note=("First-year supplemental tax applies — CA reassesses to purchase price "
                    "and back-bills to close."),
    attorney_phrase="a California real estate attorney",
    tracker_checklist=(
        ChecklistField("packet_received", "Disclosure packet received", "bool"),
        ChecklistField("tds_spq_read", "TDS / SPQ read", "bool"),
        ChecklistField("pest_section1_total", "Pest §1 total ($)", "number"),
        ChecklistField("nhd_read", "NHD read", "bool"),
        ChecklistField("hoa_docs", "HOA docs", "text"),
        ChecklistField("insurance_quoted", "Insurance quoted", "bool"),
    ),
)

AFFORDABILITY = Affordability(
    earthquake_monthly_default=150,
    optional_insurance_label="include earthquake insurance (CEA)",
    supplemental_tax_note=(
        "First-year supplemental tax: the assessed value resets to your purchase price at "
        "close, so expect a one-time catch-up bill on the order of ${amount:,} (varies with "
        "the seller's old assessed value and the closing date)."
    ),
    purchase_tax_rate=0.0115,
    purchase_tax_note=(
        "Prop 13: 1% of the purchase price plus typical local bonds and parcel taxes"
    ),
)

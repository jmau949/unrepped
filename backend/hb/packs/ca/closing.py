"""Closing content for the `ca` pack — docs/14 in data form.

Built from the `us` base: the same task keys with California prose where the
practice differs (active contingency removal on Form CR, the C.A.R. forms,
Prop 13 reassessment and the supplemental bill, FAIR Plan insurance), plus the
tasks that only exist here (TDS/SPQ/NHD, the agency pair, the Notice to Buyer to
Perform, point-of-sale sewer ordinances, Megan's Law, the homeowners' exemption).
"""

from hb.packs import compose
from hb.packs.types import ClosingTask as T
from hb.packs.types import Contingency, CostBand, CostBook, Due, Form, Phase
from hb.packs.us import closing as us

# C.A.R. RPA defaults, calendar days after Acceptance (docs/14 §4). Only ever
# defaults for a NEW deal — once a deal exists its own negotiated numbers govern.
CONTINGENCY = Contingency(
    investigation_days=17, appraisal_days=17, loan_days=21, emd_business_days=3,
    label="C.A.R. RPA defaults",
)

# C.A.R. forms, named in plain English. Referenced only — the forms are
# member-licensed and none of their text is reproduced.
FORMS: dict[str, Form] = {
    **{code: f for code, f in us.FORMS.items() if code != "PA"},
    **{
        f.code: f
        for f in [
            Form("RPA", "Residential Purchase Agreement",
                 "The main contract. Everything you agreed to — price, deadlines, who pays "
                 "what — is in here plus its counter offers."),
            Form("AD", "Disclosure Regarding Real Estate Agency Relationships",
                 "A one-page state-required explainer of who an agent can represent. It is "
                 "information, not an agreement — signing it only confirms you read it."),
            Form("BNA", "Buyer Non-Agency Agreement",
                 "The listing agent's written record that they represent the SELLER and not "
                 "you. Signing is fine — it describes the truth of your situation."),
            Form("TDS", "Real Estate Transfer Disclosure Statement",
                 "The seller's legally required list of defects they know about."),
            Form("SPQ", "Seller Property Questionnaire",
                 "The longer follow-up to the TDS, where the property's real history usually "
                 "shows up — repairs, disputes, leaks, claims."),
            Form("NHD", "Natural Hazard Disclosure Statement",
                 "A third-party report saying whether the home sits in a flood, fire, "
                 "earthquake or dam-inundation zone."),
            Form("CR", "Contingency Removal",
                 "The form that gives up one of your rights to walk away. In California "
                 "nothing expires on its own — it is not gone until you sign this."),
            Form("NBP", "Notice to Buyer to Perform",
                 "What the seller sends when you have missed a deadline. It starts a "
                 "48-hour countdown, after which they can cancel on you."),
            Form("RR", "Request for Repairs",
                 "How you ask the seller to fix things, or to knock money off, after your "
                 "inspections come back."),
            Form("VP", "Verification of Property Condition",
                 "The final walkthrough form — confirming the house is as it was and the "
                 "agreed repairs actually happened."),
            Form("ETA", "Extension of Time Addendum",
                 "A mutual agreement to push a deadline back when reports or the loan are "
                 "running late. Asking is normal."),
        ]
    },
}

COSTS = CostBook(
    year=us.COSTS.year,
    label="California contractor ranges (rough)",
    bands={
        **us.COSTS.bands,
        "fair_plan_dic": CostBand("fair_plan_dic", "FAIR Plan + DIC companion", 3_500, 9_000),
        "earthquake": CostBand("earthquake", "Earthquake rider (CEA), annual", 800, 3_500),
    },
)

PHASES: tuple[Phase, ...] = tuple(compose.override(us.PHASES, {
    "negotiate": {
        "title": "Repairs, credits, and removing contingencies",
        "blurb": "The one negotiation left, and then three irreversible signatures.",
    },
    "post_close": {
        "blurb": "Small, easy to forget, and one of them is a five-figure tax bill nobody "
                 "warned you about.",
    },
}))

# Same keys as the base, California wording.
OVERRIDES: dict[str, dict] = {
    "executed_contract": {"form": "RPA"},
    "record_key_dates": {
        "how": "Read them off your own contract — not off a summary email — and enter them on "
               "the deal. Where you negotiated something other than the RPA default, the "
               "negotiated number is the one that governs.",
    },
    "calendar_deadlines": {
        "how": "The dates are the chips along the top of this page: (1) deposit due, "
               "(2) investigation contingency removal, (3) appraisal contingency removal, "
               "(4) loan contingency removal, (5) close of escrow — plus (6) your final "
               "walkthrough, a few days before closing. Make each an all-day event with an "
               "alert 2 days before AND at 8am on the day. Title them so a glance is enough: "
               "'LOAN CONTINGENCY — sign the removal form today or lose the right to walk'.",
    },
    "open_escrow": {
        "label": "Confirm escrow is open; get officer and number",
        "why": "Escrow is the neutral party holding your deposit. You need the escrow number "
               "and a direct line to the officer before you move any money.",
    },
    "wire_emd": {
        "why": "Commonly 3% of price. Late delivery is a curable default: the seller can serve "
               "a Notice to Buyer to Perform and then cancel. Do not lose a deal for an "
               "administrative reason.",
    },
    "insurance_quotes_started": {
        "why": "In California in 2026 this is a live risk of not closing at all. Carriers have "
               "exited, placement can take weeks, and your lender will not fund without bound "
               "coverage. First-time buyers schedule this last; it belongs on day one.",
        "how": "Call an independent broker who writes across carriers, not a single-carrier "
               "agent. Give them the address, year built, roof type and age, construction, "
               "and any wildfire-zone flag.",
    },
    "attorney_engaged": {
        "why": "Right now nobody in this transaction is on your side. The listing agent works "
               "for the seller. Escrow and title are required by law to be neutral — they will "
               "answer 'what is the process' precisely and 'should I do this' not at all. "
               "Without an attorney there is literally no one whose job is to protect you, on "
               "a purchase of this size. The fee is around 0.1% of the price.",
        "how": "Search for a real estate attorney in your county, or ask your lender or escrow "
               "officer who buyers use — they deal with them constantly. Ask for a FLAT FEE "
               "(not hourly) to do four specific things: (1) read the purchase contract and "
               "tell you in plain words what you actually agreed to, (2) read the preliminary "
               "title report and explain what is on the 'exceptions' list, (3) be reachable "
               "for the three contingency-removal decisions, and (4) draft your repair request "
               "after the inspections. Send them the contract, the disclosure packet and the "
               "title report the moment you have each one. Expect $1,500–$4,000 total.",
    },
    "packet_received": {
        "how": "Ask in writing and expect to ask twice. Note the date you actually received "
               "each document — the statutory rescission right runs 3 days from personal "
               "delivery, 5 from mail.",
    },
    "lead_paint_disclosure": {
        "why": "Federal requirement for any home built before 1978. It carries its own 10-day "
               "inspection right, separate from the RPA investigation contingency.",
    },
    "prelim_title_read": {"label": "Read the preliminary title report"},
    "pest_section1_total": {
        "label": "Record the pest report Section 1 total",
        "why": "Section 1 is ACTIVE infestation or damage — real money, now. Section 2 is "
               "preventive. When you ask for a credit, the Section 1 total is the number that "
               "carries weight.",
        "how": "Write the Section 1 dollar total into the deal notes. It goes straight into "
               "the repair request.",
    },
    "pest_inspection": {
        "why": "WDO stands for wood-destroying organisms — termites, beetles and rot. They "
               "are endemic in California housing of this age, and the report splits findings "
               "into 'Section 1' (active infestation or damage happening NOW) and 'Section 2' "
               "(conditions likely to cause it later). The Section 1 dollar total is the "
               "single strongest number you can put in a repair request, because it is not "
               "your opinion — it is a licensed inspector's.",
        "how": "Order your own unless the seller supplied a current report from an inspector "
               "you did not have to trust. When it arrives, write the Section 1 total down — "
               "there is a task for exactly that further up this list.",
    },
    "sewer_scope": {
        "why": "Always, on this housing stock. Pre-1975 homes are likely clay, and a failed "
               "lateral is a $12k–$30k repair that no visual inspection can find.",
    },
    "structural_engineer": {
        "why": "Pre-1980 homes should be assumed to have an unbolted foundation and unbraced "
               "cripple wall until you see hardware. Retrofit runs $5k–$15k; a real "
               "foundation problem runs far more.",
    },
    "chimney_inspection": {
        "why": "Unreinforced masonry chimneys on pre-1980 homes are both a seismic and a fire "
               "risk, and the damage is inside the flue where nobody looks.",
    },
    "loan_application_complete": {
        "why": f"The {CONTINGENCY.loan_days}-day loan contingency is the tightest clock in "
               "the deal.",
    },
    "clear_to_close": {
        "how": "Written confirmation from the lender. If it will not arrive before the loan "
               "contingency date, ask for an extension (Form ETA) rather than removing blind.",
    },
    "insurance_quotes_compared": {
        "why": "If no admitted carrier will write the property, you are looking at a FAIR Plan "
               "policy plus a DIC companion — a different structure at a different price, and "
               "FAIR Plan premiums rise an average of 29.8% statewide from 15 October 2026.",
        "how": "Compare on dwelling limit and replacement-cost basis, not on premium alone. If "
               "you end up on the FAIR Plan, set a reminder to re-shop at renewal once you can "
               "show upgrades.",
    },
    "request_for_repairs": {
        "label": "Send the Request for Repairs",
        "how": "Ask for the Section 1 pest total and the genuinely large items. Do not itemize "
               "$400 of caulking — it costs credibility on the items that matter.",
        "form": "RR",
    },
    "credit_vs_repair": {
        "how": "The exception is work that must be permitted and signed off before transfer — "
               "the point-of-sale sewer certificate. Let the seller run that one.",
    },
    "credit_cleared_with_lender": {
        "how": "Tell the lender the proposed amount before you agree. Above the cap, take it "
               "as a price reduction instead — which also lowers your loan and your Prop 13 "
               "assessed value for as long as you own the house.",
    },
    "extension_if_needed": {
        "why": "Form ETA extends a contingency by mutual agreement. It is a normal request.",
        "how": "Ask early. Asking on the deadline itself reads as a stall and gets refused.",
        "form": "ETA",
    },
    "remove_investigation": {
        "label": "Remove the investigation contingency",
        "why": "You are giving up the right to walk on anything about the property's physical "
               "condition, permits, or neighborhood. It is irreversible.",
        "how": "Do not sign until every report is in, every 'further evaluation' has been "
               "chased down, and the repair negotiation has landed.",
        "form": "CR",
    },
    "remove_appraisal": {
        "label": "Remove the appraisal contingency",
        "how": "Do not sign until the appraisal is in hand in writing, or you have decided in "
               "advance to cover the gap in cash and confirmed you still clear reserves.",
        "form": "CR",
    },
    "remove_loan": {
        "label": "Remove the loan contingency",
        "why": "THE one that puts the deposit in play. Once all contingencies are removed, "
               "your deposit is effectively at risk if you fail to close — and if the RPA's "
               "liquidated damages clause was initialed, the seller's recovery is capped at 3% "
               "of price, which is usually exactly your deposit.",
        "how": "Written clear-to-close first, or an extension. Never on a verbal assurance.",
        "form": "CR",
    },
    "cash_to_close_confirmed": {
        "why": "Down payment plus closing costs plus any appraisal gap plus prepaids and "
               "impounds, minus your credit. Prepaids are the bucket first-timers forget and "
               "they are comfortably five figures at California prices.",
    },
    "final_walkthrough": {"form": "VP"},
    "utilities_transfer": {
        "how": "PG&E or your local utility, water, garbage and internet. Set the start date to "
               "your closing day (the contract calls it close of escrow, or COE). Ask the "
               "seller or escrow for the account numbers if you can — it makes the transfer "
               "far quicker than starting fresh service.",
    },
    "funding_recording": {
        "why": "The county recorder recording the deed is the moment you own the house — not "
               "signing, not funding. Recording usually lands the morning after signing.",
    },
}

# Base tasks whose California counterpart is a different task (below).
REPLACED = (
    "agency_disclosure_signed", "know_your_default_terms", "seller_disclosures_read",
    "local_pos_requirements", "offender_registry_check", "excluded_perils_decision",
    "reassessment_check", "homestead_exemption",
)

EXTRA: tuple[T, ...] = (
    T(
        "agency_forms_signed", "Sign the two agency forms — and know what they mean",
        "lock_down", "you",
        why="You will be handed two forms with initials-only names. The AD (Agency "
            "Disclosure) is a state-required one-pager explaining that an agent can work "
            "for the seller, for the buyer, or — with permission — for both. The BNA "
            "(Buyer Non-Agency Agreement) is the listing agent putting in writing that "
            "they represent the SELLER and not you. Neither hurts you. But together they "
            "are the moment the paperwork states plainly that you are on your own, and "
            "most people sign them without reading.",
        how="Read the AD's three definitions before signing anything. Sign the BNA — it "
            "describes the truth of your situation. If the listing agent instead offers to "
            "represent you as well ('dual agency'), understand the trade: you gain someone "
            "who knows the file and can produce paperwork, and you lose any ability for "
            "them to advise you on price or terms against their own seller. For a "
            "first-time buyer that is usually worse than staying unrepresented and paying "
            "an attorney.",
        due=Due("acceptance", 3), form="BNA",
    ),
    T(
        "know_the_nbp", "Learn what a Notice to Buyer to Perform is", "lock_down", "you",
        why="California contingencies do not expire on their own — you remove them actively "
            "in writing. If you are late, the seller serves an NBP and you have 48 HOURS "
            "before they can cancel and fight you over the deposit. Two days is not enough "
            "time to learn this.",
        how="Read “The contingency clock” in the closing playbook on this page now, "
            "while nothing is urgent. Know that an NBP must be "
            "delivered in writing with receipt acknowledged, and cannot be served before "
            "the date has actually passed.",
        due=Due("acceptance", 2), form="NBP",
    ),
    T(
        "tds_read", "Read the Transfer Disclosure Statement", "disclosures", "you",
        why="The statutory seller disclosure of known defects. It is the closest thing to "
            "an admission you will ever get.",
        how="Read every 'yes' box — and every question left blank. Blanks are not answers; "
            "ask for them to be completed.",
        due=Due("acceptance", 7), form="TDS",
    ),
    T(
        "spq_read", "Read the Seller Property Questionnaire", "disclosures", "you",
        why="The long-form supplement, and where the real history usually lives.",
        how="Look for neighbor disputes, prior insurance claims, water intrusion, deaths, "
            "and repairs described as done 'by owner' — that phrase means unpermitted "
            "until proven otherwise.",
        due=Due("acceptance", 7), form="SPQ",
    ),
    T(
        "nhd_read", "Read the Natural Hazard Disclosure", "disclosures", "you",
        why="Third-party report on flood, fire, seismic and dam inundation zones. Every "
            "'yes' is an insurance conversation, not just a safety one.",
        how="Cross-check against the hazard chips the app already computed for this "
            "property. Send any wildfire-zone finding straight to your insurance broker.",
        due=Due("acceptance", 7), form="NHD",
    ),
    T(
        "city_pos_report", "Get the city point-of-sale / sewer lateral report", "disclosures",
        "seller",
        why="This city requires a sewer-lateral compliance certificate before title can "
            "transfer. It is a hard gate on closing, not a negotiation item — and a "
            "replacement runs $12k–$30k, so whether it lands on the seller by ordinance or "
            "on you by silence is a five-figure question.",
        how="Confirm the current ordinance with the city directly, and confirm in writing "
            "who is performing and paying for the work. Get the certificate before COE.",
        due=Due("acceptance", 7), blocking=True, cost="sewer_lateral",
        # Cities carrying this flag in geography.toml; an unknown city keeps the task.
        applies_when={"city_flag": "sewer_lateral_pos"},
    ),
    T(
        "megans_law_check", "Search the sex-offender registry for the neighbourhood",
        "disclosures", "you",
        why="'Megan's Law' is the California statute that put the sex-offender registry "
            "online. Every purchase contract carries a paragraph telling you the database "
            "exists — and that is the entire extent of anyone's obligation. The seller "
            "does not have to look it up, and agents are actually forbidden from "
            "interpreting it for you. If you don't run the search, nobody does.",
        how="Go to meganslaw.ca.gov, enter the address, and look at the surrounding blocks "
            "on the map rather than just the parcel itself. Free, takes two minutes. Do it "
            "before you remove your investigation contingency — while you still have the "
            "right to walk away over what you find.",
        due=Due("acceptance", 7),
    ),
    T(
        "earthquake_decision", "Decide on earthquake coverage", "title_insurance", "you",
        why="Always excluded from a standard homeowners policy, and this is California. "
            "CEA coverage is expensive with a 10–25% deductible — which is a decision worth "
            "making deliberately rather than by default.",
        how="Get the quote, compare against the deductible you would actually face, and "
            "record the decision either way.",
        due=Due("acceptance", 12), cost="earthquake",
    ),
    T(
        "supplemental_tax_reserve", "Set aside money for the supplemental tax bill",
        "post_close", "you",
        why="The most common first-year financial surprise in California. Tax was being "
            "paid on the seller's Prop 13 basis — possibly set decades ago. The county "
            "reassesses to your purchase price and bills you for the difference, BACK-DATED "
            "to your closing date. It arrives months later, it is NOT in your impound "
            "account, and on a long-held home it can be five figures.",
        how="Estimate it from the assessed-value jump times the local rate and move the "
            "money to a separate account at closing.",
        due=Due("coe", 3),
    ),
    T(
        "homeowners_exemption", "File the CA homeowners' exemption", "post_close", "you",
        why="Knocks $7,000 off assessed value, permanently. Small, easy, and easy to forget.",
        how="File with the county assessor. The form usually arrives automatically after "
            "recording — if it does not, request it.",
        due=Due("coe", 14),
    ),
)

TASKS: tuple[T, ...] = tuple(
    compose.add(compose.override(compose.without(us.TASKS, *REPLACED), OVERRIDES), *EXTRA)
)

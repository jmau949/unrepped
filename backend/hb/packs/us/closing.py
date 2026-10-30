"""Closing content for the `us` base pack — every task a self-represented buyer
in any US state needs, in state-neutral wording.

The engine (`hb.closing_spec`) does the date math; this file is only the
records. State packs build on these lists with `hb.packs.compose` — same keys,
different prose — so a `deals.checklist` written under one pack still reads
under another (docs/packs/README.md).

Where state practice genuinely diverges (active contingency removal, named
forms, point-of-sale ordinances, reassessment), the base task says what to find
out and where; the state pack says the answer.
"""

from hb.packs.types import ClosingTask as T
from hb.packs.types import Contingency, CostBand, CostBook, Due, Form, Phase

# Who actually performs the task. The buyer has no agent, so `you` is most of them.
OWNERS = ("you", "lender", "escrow", "title", "seller", "inspector", "insurer", "attorney")

# Common defaults for a NEW deal. There is no national contract, so these are a
# starting point the user edits to their own numbers (the UI says so).
CONTINGENCY = Contingency(
    investigation_days=10, appraisal_days=21, loan_days=21, emd_business_days=3,
    label="Common defaults (edit to your contract)",
)

FORMS: dict[str, Form] = {
    f.code: f
    for f in [
        Form("PA", "Purchase Agreement",
             "The main contract. Everything you agreed to — price, deadlines, who pays "
             "what — is in here plus its counter offers and addenda."),
        Form("FLD", "Lead-Based Paint and Hazards Disclosure",
             "Federally required for any home built before 1978, with its own 10-day "
             "window to test for lead paint."),
        Form("LE", "Loan Estimate",
             "The federally standardised three-page estimate of your loan terms and "
             "closing costs, due within 3 business days of applying."),
        Form("CD", "Closing Disclosure",
             "The final federally standardised statement of your loan and closing "
             "costs, due at least 3 business days before you sign."),
    ]
}

COSTS = CostBook(
    year=2026,
    label="national contractor ranges (rough)",
    bands={
        b.key: b
        for b in [
            # Inspections you order yourself
            CostBand("inspection_general", "General home inspection", 600, 1_200),
            CostBand("inspection_pest", "Pest / WDO inspection", 150, 450),
            CostBand("inspection_sewer", "Sewer lateral video scope", 300, 700),
            CostBand("inspection_roof", "Roof inspection", 300, 800),
            CostBand("inspection_structural", "Structural / foundation engineer", 600, 2_500),
            CostBand("inspection_chimney", "Chimney level-2 inspection", 250, 600),
            CostBand("inspection_pool", "Pool / spa inspection", 200, 450),
            # Professional help you buy back because you have no agent
            CostBand("attorney", "Real estate attorney, flat fee", 1_500, 4_000),
            CostBand("transaction_coordinator", "Transaction coordinator", 500, 900),
            # Settlement charges
            CostBand("escrow_fee", "Escrow / settlement fee", 2_500, 4_500),
            CostBand("title_owners", "Owner's title policy", 2_500, 5_000),
            CostBand("title_lenders", "Lender's title policy", 500, 1_200),
            CostBand("recording", "Recording fees", 150, 400),
            CostBand("notary", "Notary / mobile signing", 150, 350),
            CostBand("appraisal", "Appraisal (jumbo may require two)", 800, 1_500),
            CostBand("prepaids", "Prepaids + impounds", 10_000, 25_000),
            # Insurance
            CostBand("hoi_year1", "Homeowners insurance, first year", 1_800, 4_500),
            CostBand("fair_plan_dic", "FAIR Plan / surplus-lines policy, first year", 3_500, 9_000),
            CostBand("earthquake", "Earthquake rider, annual", 800, 3_500),
            CostBand("flood_year1", "Flood insurance (NFIP), annual", 600, 3_000),
            # Repair obligation a point-of-sale ordinance can force to closing
            CostBand("sewer_lateral", "Sewer lateral replacement", 12_000, 30_000),
        ]
    },
)

PHASES: tuple[Phase, ...] = (
    Phase("lock_down", "Days 0–3: lock it down",
          "Administrative, urgent, and the cheapest place in the whole transaction to "
          "lose a deposit. Do all of it in the first three days."),
    Phase("disclosures", "The packet, read adversarially",
          "You may have read it before offering. Read it again with a signed contract "
          "and the inspection reports next to it — it is a different document now."),
    Phase("inspections", "Inspections you order yourself",
          "Book on day one; good inspectors are 5–10 days out and a report that lands "
          "after your decision date bought you nothing."),
    Phase("loan", "Loan, appraisal, and the gap",
          "The loan contingency is the tightest clock in the deal and the one that puts "
          "the deposit in play."),
    Phase("title_insurance", "Title, escrow, and insurance",
          "Two neutral parties and one that can stop the closing outright if you start "
          "shopping too late."),
    Phase("negotiate", "Repairs, credits, and the contingency deadlines",
          "The one negotiation left, and then three irreversible dates."),
    Phase("final_week", "The final week",
          "Closing Disclosure, walkthrough, sign, fund, record. You own it at recording, "
          "not at signing."),
    Phase("post_close", "Week one after close",
          "Small, easy to forget, and one of them is a tax bill nobody warned you about."),
)

TASKS: tuple[T, ...] = (
    # ---------------------------------------------------------------- lock_down
    T(
        "executed_contract", "Get a complete copy of the signed contract", "lock_down", "you",
        why="Acceptance is a specific moment — the last signature communicated back — and "
            "every deadline in the transaction counts from that date. If you are unsure "
            "of the acceptance date you do not know a single one of your deadlines.",
        how="Ask for the complete signed PDF: every page, every initial box, every counter "
            "in order, every addendum. The operative terms are in the last counter signed. "
            "Confirm the acceptance date back in writing.",
        due=Due("acceptance", 0), blocking=True, form="PA",
    ),
    T(
        "record_key_dates", "Copy the five numbers your deadlines come from", "lock_down",
        "you",
        why="Acceptance date, price, deposit, the three contingency periods, and the "
            "closing date are the only inputs this tracker has. Everything else is "
            "arithmetic on them.",
        how="Read them off your own contract — not off a summary email — and enter them on "
            "the deal. Where you negotiated something other than the defaults shown here, "
            "the negotiated number is the one that governs.",
        due=Due("acceptance", 0), blocking=True,
    ),
    T(
        "send_contract_to_lender", "Email the signed purchase contract to your loan officer",
        "lock_down", "you",
        why="Your lender cannot start underwriting a house they have no contract for, and "
            "the loan contingency clock started the moment the seller signed — it does not "
            "wait for you to forward the file. This is the most common self-inflicted delay "
            "in the whole transaction.",
        how="The 'executed contract' is the purchase agreement signed by BOTH you and the "
            "seller, including every counter offer — the same PDF you collected in the "
            "first task on this list. Email the complete file to your loan officer, ask "
            "them to confirm receipt in writing, and ask one question: 'what date do you "
            "expect to have me clear to close, and how does that compare to my loan "
            "contingency date?' If those two dates are the wrong way round, you need to "
            "know today, not in three weeks.",
        due=Due("acceptance", 0), applies_when={"financed": True},
    ),
    T(
        "calendar_deadlines", "Put your six key dates in your phone calendar", "lock_down",
        "you",
        why="This page is the system of record, but you will not have it open on the day "
            "something is due. A second copy in the calendar you actually look at costs "
            "nothing and has saved deals.",
        how="The dates are the chips along the top of this page: (1) deposit due, "
            "(2) investigation contingency deadline, (3) appraisal contingency deadline, "
            "(4) loan contingency deadline, (5) closing — plus (6) your final walkthrough, "
            "a few days before closing. Make each an all-day event with an alert 2 days "
            "before AND at 8am on the day. Title them so a glance is enough: 'LOAN "
            "CONTINGENCY — decide today or lose the right to walk'.",
        due=Due("acceptance", 1),
    ),
    T(
        "open_escrow", "Confirm escrow or the closing agent is open; get a contact and number",
        "lock_down", "escrow",
        why="Escrow — or, in attorney-closing states, the closing attorney or title "
            "company — is the neutral party holding your deposit. You need the file "
            "number and a direct line to the person running it before you move any money.",
        how="Get the officer's name, direct phone, and the file number. Save the phone "
            "number in your contacts NOW — you will need a number you trust in order to "
            "verify wire instructions, and it cannot come from the email carrying them.",
        due=Due("acceptance", 1), cost="escrow_fee",
    ),
    T(
        "verify_wire_instructions", "Verify wire instructions BY VOICE", "lock_down", "you",
        why="Real estate wire fraud targets exactly this transaction profile. Criminals "
            "watch the thread and send lookalike instructions at the moment you expect "
            "them. Money sent to the wrong account is usually gone permanently.",
        how="Call the escrow or closing officer on a number you obtained independently — "
            "never one printed in the email containing the instructions — and read the "
            "account number back aloud. Treat any change to previous instructions as fraud "
            "until proven otherwise. Repeat this before the cash-to-close wire too.",
        due=Due("acceptance", 2), blocking=True,
    ),
    T(
        "wire_emd", "Wire the earnest money deposit", "lock_down", "you",
        why="Commonly 1–3% of price. Late delivery is a default the seller can act on — "
            "in some states only after a formal notice to perform, in others at once. Do "
            "not lose a deal for an administrative reason.",
        how="Wire to escrow after verifying instructions by voice. Call an hour later to "
            "confirm receipt — the first hours are the only ones where a recall has a real "
            "chance. Tell your bank it is a real estate closing wire.",
        due=Due("emd", 0), blocking=True,
    ),
    T(
        "insurance_quotes_started", "Start homeowners insurance quotes", "lock_down", "you",
        why="In a growing number of markets this is a live risk of not closing at all. "
            "Carriers have pulled back, placement can take weeks, and your lender will not "
            "fund without bound coverage. First-time buyers schedule this last; it belongs "
            "on day one.",
        how="Call an independent broker who writes across carriers, not a single-carrier "
            "agent. Give them the address, year built, roof type and age, construction, "
            "and any hazard-zone flag the app shows for the property.",
        due=Due("acceptance", 2), blocking=True,
    ),
    T(
        "attorney_engaged", "Hire a real estate attorney to review the deal", "lock_down",
        "you",
        why="Right now nobody in this transaction is on your side. The listing agent works "
            "for the seller. Escrow and title are required to be neutral — they will "
            "answer 'what is the process' precisely and 'should I do this' not at all. "
            "Without an attorney there is literally no one whose job is to protect you, on "
            "the largest purchase of your life. The fee is a fraction of a percent of the "
            "price.",
        how="Search for a real estate attorney in your county, or ask your lender or escrow "
            "officer who buyers use — they deal with them constantly. Ask for a FLAT FEE "
            "(not hourly) to do four specific things: (1) read the purchase contract and "
            "tell you in plain words what you actually agreed to, (2) read the title "
            "report and explain what is on the 'exceptions' list, (3) be reachable for the "
            "three contingency decisions, and (4) draft your repair request after the "
            "inspections. Send them the contract, the disclosure packet and the title "
            "report the moment you have each one. Expect a flat fee in the low thousands.",
        due=Due("acceptance", 2), cost="attorney",
    ),
    T(
        "agency_disclosure_signed", "Sign the agency disclosure — and know what it means",
        "lock_down", "you",
        why="Every state requires the listing agent to disclose in writing whom they "
            "represent. Signing confirms you read it, not that they work for you. It is "
            "the moment the paperwork states plainly that you are on your own, and most "
            "people sign it without reading.",
        how="Read the definitions before signing anything. If the listing agent instead "
            "offers to represent you as well ('dual agency', where your state allows it), "
            "understand the trade: you gain someone who knows the file and can produce "
            "paperwork, and you lose any ability for them to advise you on price or terms "
            "against their own seller. For a first-time buyer that is usually worse than "
            "staying unrepresented and paying an attorney.",
        due=Due("acceptance", 3),
    ),
    T(
        "know_your_default_terms", "Learn what happens if you miss a deadline", "lock_down",
        "you",
        why="Contracts differ on whether a missed contingency date waives your protection "
            "automatically, starts a notice-and-cure period, or lets the seller cancel "
            "outright. Two days before a deadline is not enough time to learn which one "
            "yours does.",
        how="Find the default and notice paragraphs in your contract now, while nothing is "
            "urgent, and have your attorney confirm in one sentence how a missed date plays "
            "out — and whether an extension must be in writing.",
        due=Due("acceptance", 2),
    ),

    # ------------------------------------------------------------- disclosures
    T(
        "packet_received", "Receive the full disclosure packet", "disclosures", "seller",
        why="Everything you can learn about this house without paying for it is in here, "
            "and several of your rights run from the date of DELIVERY rather than from "
            "acceptance.",
        how="Ask in writing and expect to ask twice. Note the date you actually received "
            "each document — review and rescission periods run from delivery.",
        due=Due("acceptance", 3), blocking=True,
    ),
    T(
        "seller_disclosures_read", "Read the seller's property disclosure statement",
        "disclosures", "you",
        why="Nearly every state requires the seller to disclose known defects on a standard "
            "form. It is the closest thing to an admission you will ever get.",
        how="Read every 'yes' box — and every question left blank. Blanks are not answers; "
            "ask for them to be completed. Look for prior insurance claims, water "
            "intrusion, neighbor disputes, and repairs described as done 'by owner' — that "
            "phrase means unpermitted until proven otherwise.",
        due=Due("acceptance", 7),
    ),
    T(
        "lead_paint_disclosure", "Lead-based paint disclosure", "disclosures", "seller",
        why="Federal requirement for any home built before 1978. It carries its own 10-day "
            "inspection right, separate from your inspection contingency.",
        how="Confirm you received it and decide whether to use or waive the 10-day "
            "assessment window.",
        due=Due("acceptance", 7), form="FLD", applies_when={"year_built_before": 1978},
    ),
    T(
        "prelim_title_read", "Read the preliminary title report or title commitment",
        "disclosures", "title",
        why="Not a search result to skim — a list of everything the title company will "
            "EXCLUDE from coverage.",
        how="Read the exceptions schedule line by line.",
        due=Due("acceptance", 7), blocking=True,
    ),
    T(
        "title_exceptions_pulled", "Pull every document on the title report's exception list",
        "disclosures", "you",
        why="This is the part nobody reads, and it is where easements through the yard, "
            "shared driveway agreements, deed restrictions, encroachments and unreleased "
            "old liens live. They survive the sale and become yours.",
        how="Request copies of every recorded document referenced by number in the "
            "exception schedule. This is the hour of attorney time that pays for itself.",
        due=Due("acceptance", 10), blocking=True,
    ),
    T(
        "hoa_docs_read", "Read the HOA documents", "disclosures", "you",
        why="CC&Rs, budget, reserves and minutes decide what you may do with the property "
            "and what you will be assessed for.",
        how="Check reserve funding percentage, pending special assessments, litigation, and "
            "any rental restrictions. Read the last 12 months of minutes.",
        due=Due("acceptance", 10), applies_when={"hoa": True},
    ),
    T(
        "local_pos_requirements", "Check for local point-of-sale requirements", "disclosures",
        "you",
        why="Some cities require an inspection, a certificate of occupancy or a sewer "
            "certificate before title can transfer. It is a hard gate on closing, not a "
            "negotiation item — and the kind of local rule a first-time buyer has no way "
            "to know exists.",
        how="Call the city's building or planning department and ask whether anything is "
            "required at sale. If so, confirm in writing who is performing and paying for "
            "it, and get the certificate before closing.",
        due=Due("acceptance", 7),
    ),
    T(
        "seller_inspections_read", "Read the seller-supplied inspections", "disclosures", "you",
        why="Useful as a starting point, but the inspector was hired by the seller, the "
            "report is scoped accordingly, and you have no recourse against it because you "
            "are not their client. It is not a substitute for your own.",
        how="Read them, then order your own anyway. Note anything they conspicuously did "
            "not cover.",
        due=Due("acceptance", 5),
    ),
    T(
        "pest_section1_total", "Record the pest report's active-damage total", "disclosures",
        "you",
        why="A pest (wood-destroying organism) report separates active infestation or "
            "damage — real money, now — from preventive items. When you ask for a credit, "
            "the active-damage total is the number that carries weight.",
        how="Write the active-damage dollar total into the deal notes. It goes straight "
            "into the repair request.",
        due=Due("acceptance", 7),
    ),
    T(
        "offender_registry_check", "Search the sex-offender registry for the neighbourhood",
        "disclosures", "you",
        why="Every state's registry is online and most purchase contracts tell you it "
            "exists — and that is the entire extent of anyone's obligation. The seller "
            "does not have to look it up, and agents generally will not interpret it for "
            "you. If you don't run the search, nobody does.",
        how="Use the national search at nsopw.gov (or your state's site), enter the "
            "address, and look at the surrounding blocks on the map rather than just the "
            "parcel. Free, takes two minutes. Do it before your investigation contingency "
            "deadline — while you still have the right to walk away over what you find.",
        due=Due("acceptance", 7),
    ),

    # ------------------------------------------------------------- inspections
    T(
        "book_general_inspection", "Book the general home inspection", "inspections", "you",
        why="Good inspectors run 5–10 days out. Booked on day one the report lands with "
            "time to price repairs and still decide; booked on day five it does not.",
        how="Book day one. Ask for the earliest slot and confirm the report turnaround.",
        due=Due("acceptance", 1), blocking=True,
    ),
    T(
        "general_inspection", "General home inspection completed", "inspections", "inspector",
        why="The foundation of every other decision in the investigation period.",
        how="Attend in person for the whole thing, not the last hour. Three or four hours "
            "walking the house with someone who does this daily is the best education "
            "available to a first-time buyer, and what they say out loud is consistently "
            "more useful than what survives into the written report.",
        due=Due("investigation_removal", -8), blocking=True, cost="inspection_general",
    ),
    T(
        "pest_inspection", "Book a termite inspection (the 'pest' or WDO report)",
        "inspections", "inspector",
        why="WDO stands for wood-destroying organisms — termites, beetles and rot. The "
            "report separates active infestation or damage happening NOW from conditions "
            "likely to cause it later, and the active-damage total is the single strongest "
            "number you can put in a repair request, because it is not your opinion — it "
            "is a licensed inspector's.",
        how="Order your own unless the seller supplied a current report from an inspector "
            "you did not have to trust. When it arrives, write the active-damage total "
            "down — there is a task for exactly that further up this list.",
        due=Due("investigation_removal", -8), cost="inspection_pest",
    ),
    T(
        "sewer_scope", "Sewer lateral video scope", "inspections", "inspector",
        why="Always, on older housing. Pre-1975 laterals are often clay or Orangeburg "
            "fibre, and a failed lateral is a five-figure repair that no visual inspection "
            "can find.",
        how="Camera scope from the cleanout to the main. Get the video file, not just the "
            "summary.",
        due=Due("investigation_removal", -7), cost="inspection_sewer",
    ),
    T(
        "roof_inspection", "Roof inspection", "inspections", "inspector",
        why="A roof replacement is a five-figure repair and estimated age is the trigger.",
        how="Order if the general inspector flags it or the roof is 15+ years old.",
        due=Due("investigation_removal", -6), cost="inspection_roof",
    ),
    T(
        "structural_engineer", "Structural / foundation engineer", "inspections", "inspector",
        why="Foundation problems are the most expensive class of defect and the least "
            "visible from inside the house. On an older home assume nothing until an "
            "engineer has looked.",
        how="Order for any settlement crack, hillside lot, or addition. A general inspector "
            "saying 'recommend further evaluation' is a referral — treat it as one.",
        due=Due("investigation_removal", -5), cost="inspection_structural",
        applies_when={"year_built_before": 1980},
    ),
    T(
        "chimney_inspection", "Chimney level-2 inspection", "inspections", "inspector",
        why="Masonry chimneys on older homes hide flue damage where nobody looks, and a "
            "cracked flue is both a fire risk and an expensive rebuild.",
        how="Level 2, with a camera.",
        due=Due("investigation_removal", -5), cost="inspection_chimney",
        applies_when={"year_built_before": 1980},
    ),
    T(
        "pool_inspection", "Pool / spa inspection", "inspections", "inspector",
        why="Equipment and shell problems are expensive and invisible to a general "
            "inspector.",
        how="Separate specialist.",
        due=Due("investigation_removal", -5), cost="inspection_pool",
        applies_when={"pool": True},
    ),
    T(
        "further_evaluation_chased", "Chase every 'recommend further evaluation'",
        "inspections", "you",
        why="That phrase is not filler. It is the general inspector telling you they found "
            "something outside their scope that needs a trade to price. Every instance you "
            "leave unchased becomes a number you agreed to without knowing it.",
        how="List them, book the specialist for each, and get them done before the "
            "investigation contingency deadline.",
        due=Due("investigation_removal", -4), blocking=True,
    ),
    T(
        "contractor_bids", "Get written contractor bids on the large items", "inspections",
        "you",
        why="'The inspector said' is a weak negotiating position. A written bid is not.",
        how="Bids are usually free. Get them for anything you intend to raise in the repair "
            "request.",
        due=Due("investigation_removal", -3),
    ),
    T(
        "price_the_findings", "Price the findings into a total", "inspections", "you",
        why="The tour app already estimated deferred maintenance from cost bands; the "
            "inspection reports replace those estimates with real numbers. That total is "
            "what you carry into the repair negotiation and the contingency decision.",
        how="Sum the real quotes, keep the band estimates for anything not yet quoted, and "
            "compare against what you assumed when you set your bid.",
        due=Due("investigation_removal", -3),
    ),

    # -------------------------------------------------------------------- loan
    T(
        "loan_application_complete", "Submit the complete loan application", "loan", "you",
        why="The loan contingency is the tightest clock in the deal.",
        how="Submit everything on day one. Underwriting will come back for documents "
            "repeatedly — answer within hours, not days.",
        due=Due("acceptance", 1), blocking=True, applies_when={"financed": True},
    ),
    T(
        "loan_estimate_saved", "Receive and SAVE the Loan Estimate", "loan", "lender",
        why="Federally required within 3 business days of application. Save it — in the "
            "final week you will compare the Closing Disclosure against it line by line, "
            "and that comparison is the only thing standing between you and fee creep.",
        how="File it where you will find it in four weeks.",
        due=Due("acceptance", 4), blocking=True, form="LE", applies_when={"financed": True},
    ),
    T(
        "no_new_credit", "Standing rule: change nothing financial until you have keys",
        "loan", "you",
        why="Underwriting re-pulls credit and re-verifies employment shortly before "
            "funding. People lose loans in the last week doing entirely ordinary things.",
        how="No new credit cards, no financed car, no job change, no comp-structure change, "
            "no large transfers between accounts, no undocumented deposits. Until keys.",
        due=Due("acceptance", 0), blocking=True, applies_when={"financed": True},
    ),
    T(
        "rate_lock", "Lock the rate", "loan", "you",
        why="Locks run 30–60 days. A lock that expires before closing costs real money to "
            "extend.",
        how="Confirm the lock expiry lands after your closing date with margin, in writing.",
        due=Due("acceptance", 7), applies_when={"financed": True},
    ),
    T(
        "appraisal_ordered", "Confirm the appraisal is ordered", "loan", "lender",
        why="You pay for it, the lender orders it, and jumbo programs sometimes require "
            "two — which takes longer than one.",
        how="Confirm the order date and expected turnaround against your appraisal "
            "contingency date.",
        due=Due("acceptance", 5), cost="appraisal", applies_when={"financed": True},
    ),
    T(
        "appraisal_received", "Receive the appraisal in writing", "loan", "lender",
        why="The lender lends against the LOWER of price and appraised value. In a "
            "competitive market a low appraisal is ordinary, because the price was set by "
            "a bidding war and the comps were not.",
        how="In writing, not verbally. If it comes in low, your CMA workbench output — "
            "bracketed comps, market-derived adjustments, a visible grid — is exactly the "
            "right artifact for a reconsideration-of-value request through the lender.",
        due=Due("appraisal_removal", -3), blocking=True, applies_when={"financed": True},
    ),
    T(
        "appraisal_gap_decision", "Decide how to handle any appraisal gap", "loan", "you",
        why="The shortfall is cash out of your pocket on top of the down payment. Four "
            "options: cover it, ask the seller to reduce, split it, or walk on the "
            "contingency if you still have one.",
        how="Run the number through the affordability check — covering a gap still has to "
            "leave you above the 6-month reserves floor. Decide before the deadline, not "
            "on it.",
        due=Due("appraisal_removal", -1), blocking=True, applies_when={"financed": True},
    ),
    T(
        "underwriting_conditions", "Clear all underwriting conditions", "loan", "you",
        why="Conditions are what stand between 'approved' and 'clear to close', and they "
            "arrive in waves.",
        how="Answer same-day. Ask the lender explicitly which conditions remain and which "
            "are prior-to-doc versus prior-to-funding.",
        due=Due("loan_removal", -5), applies_when={"financed": True},
    ),
    T(
        "clear_to_close", "Get 'clear to close' from your lender IN WRITING", "loan", "lender",
        why="'Clear to close' is the lender's term for: underwriting is finished, every "
            "condition is satisfied, and the only thing left is to draw up documents and "
            "send money. It is the gate before you let your loan contingency go. A verbal "
            "'we're looking good' is not it, and giving up that contingency without it in "
            "writing is the single most common way a buyer loses a deposit.",
        how="Written confirmation from the lender. If it will not arrive before the loan "
            "contingency deadline, ask for a written extension rather than proceeding "
            "blind.",
        due=Due("loan_removal", -1), blocking=True, applies_when={"financed": True},
    ),

    # -------------------------------------------------------- title_insurance
    T(
        "escrow_instructions_signed", "Sign the escrow / closing instructions",
        "title_insurance", "escrow",
        why="These govern what escrow may do with your money. Escrow is neutral — it will "
            "answer process questions precisely and advice questions not at all.",
        how="Read them. Confirm the parties, price, deposit and closing date match your "
            "contract.",
        due=Due("acceptance", 7),
    ),
    T(
        "title_policy_choice", "Choose the owner's title policy", "title_insurance", "you",
        why="Standard versus extended (ALTA homeowner's) coverage differ in what they "
            "insure against, and this is a once-per-house decision you keep for as long as "
            "you own it.",
        how="Ask the title officer to state plainly what the extended policy adds. On older "
            "housing stock with the exception schedules that come with it, the extra is "
            "usually worth it.",
        due=Due("acceptance", 14), cost="title_owners",
    ),
    T(
        "insurance_quotes_compared", "Compare insurance quotes and choose", "title_insurance",
        "you",
        why="If no admitted carrier will write the property, you may be looking at your "
            "state's FAIR Plan or a surplus-lines policy — a different structure at a "
            "different price, and one that gets more expensive every year.",
        how="Compare on dwelling limit and replacement-cost basis, not on premium alone. If "
            "you end up on a last-resort plan, set a reminder to re-shop at renewal once "
            "you can show upgrades.",
        due=Due("acceptance", 10), cost="hoi_year1",
    ),
    T(
        "excluded_perils_decision", "Decide on flood and other excluded-peril coverage",
        "title_insurance", "you",
        why="A standard homeowners policy excludes flood everywhere, and earthquake, wind "
            "or sinkhole in the regions where they matter. If the home sits in a FEMA "
            "flood zone the lender will require flood insurance; everywhere else it is a "
            "decision worth making deliberately rather than by default.",
        how="Get a quote for each excluded peril that applies to this address, compare it "
            "against the deductible you would actually face, and record the decision "
            "either way.",
        due=Due("acceptance", 12), cost="flood_year1",
    ),
    T(
        "insurance_bound", "BIND the policy", "title_insurance", "insurer",
        why="Your lender will not fund without bound coverage. This is the insurance task "
            "that can stop a closing outright.",
        how="Bind, get the declarations page or binder, and confirm the effective date is "
            "on or before closing.",
        due=Due("coe", -7), blocking=True,
    ),
    T(
        "binder_to_lender", "Send the insurance binder to the lender", "title_insurance",
        "you",
        why="Bound but unsent is the same as unbound as far as funding is concerned.",
        how="Send it at least a week before closing and get confirmation it satisfies "
            "their requirement — including the mortgagee clause wording.",
        due=Due("coe", -7), blocking=True, applies_when={"financed": True},
    ),

    # --------------------------------------------------------------- negotiate
    T(
        "request_for_repairs", "Send the repair request", "negotiate", "you",
        why="This is the one negotiation left in the transaction.",
        how="Ask for the active-damage pest total and the genuinely large items. Do not "
            "itemize $400 of caulking — it costs credibility on the items that matter.",
        due=Due("investigation_removal", -2),
    ),
    T(
        "credit_vs_repair", "Ask for a credit rather than a repair", "negotiate", "you",
        why="A seller who is leaving has no incentive to buy quality work, repairs done in "
            "escrow are done under duress, and you inherit whatever they hired. A credit "
            "lets you choose the contractor and reduces cash to close immediately.",
        how="The exception is work that must be permitted and signed off before transfer. "
            "Let the seller run that one.",
        due=Due("investigation_removal", -2),
    ),
    T(
        "credit_cleared_with_lender", "Clear any credit with your lender first", "negotiate",
        "you",
        why="A closing-cost credit cannot exceed your actual closing costs, and jumbo "
            "programs cap seller concessions. A credit that breaks a program rule gets "
            "stripped at underwriting after you already traded for it.",
        how="Tell the lender the proposed amount before you agree. Above the cap, take it "
            "as a price reduction instead — which also lowers your loan and your assessed "
            "value for as long as you own the house.",
        due=Due("investigation_removal", -1), applies_when={"financed": True},
    ),
    T(
        "extension_if_needed", "Ask for an extension if reports are late", "negotiate", "you",
        why="An extension addendum pushes a contingency back by mutual agreement. It is a "
            "normal request.",
        how="Ask early, in writing. Asking on the deadline itself reads as a stall and gets "
            "refused.",
        due=Due("investigation_removal", -1),
    ),
    T(
        "remove_investigation", "Investigation contingency deadline: proceed or walk",
        "negotiate", "you",
        why="This is the last day you can walk away over the property's physical "
            "condition, permits or neighborhood without putting your deposit at risk. In "
            "most states the right simply expires at the deadline; in some you must sign a "
            "removal. Either way, after today it is gone.",
        how="Do not let the date pass until every report is in, every 'further evaluation' "
            "has been chased down, and the repair negotiation has landed. If you need more "
            "time, get a written extension before the deadline, not after.",
        due=Due("investigation_removal", 0), blocking=True,
    ),
    T(
        "remove_appraisal", "Appraisal contingency deadline: proceed or walk", "negotiate",
        "you",
        why="You are giving up the right to walk if value comes in below price.",
        how="Do not let the date pass until the appraisal is in hand in writing, or you "
            "have decided in advance to cover the gap in cash and confirmed you still clear "
            "reserves.",
        due=Due("appraisal_removal", 0), blocking=True,
    ),
    T(
        "remove_loan", "Loan contingency deadline: proceed or walk", "negotiate", "you",
        why="THE one that puts the deposit in play. Once every contingency is gone, your "
            "deposit is at risk if you fail to close — read your contract's "
            "liquidated-damages or default clause to know exactly how much.",
        how="Written clear-to-close first, or a written extension. Never on a verbal "
            "assurance.",
        due=Due("loan_removal", 0), blocking=True, applies_when={"financed": True},
    ),

    # -------------------------------------------------------------- final_week
    T(
        "closing_disclosure_received", "Receive the Closing Disclosure", "final_week",
        "lender",
        why="TRID requires it in your hands at least 3 business days before consummation. "
            "This is not a courtesy window — certain changes restart it.",
        how="Confirm the date you received it.",
        due=Due("coe", -3), blocking=True, form="CD", applies_when={"financed": True},
    ),
    T(
        "cd_vs_le_compared",
        "Compare the Closing Disclosure against your Loan Estimate, line by line",
        "final_week", "you",
        why="Nobody else will. Ever. This is the single highest-value hour in the final "
            "week and it is entirely on you.",
        how="Check loan amount, rate, term and payment against your lock; no prepayment "
            "penalty and no balloon; lender fees against the LE tolerances; that the credit "
            "you negotiated actually appears; that tax and insurance escrows are real "
            "numbers not placeholders; and that cash to close matches your own arithmetic. "
            "Raise discrepancies the day you receive it, not at the signing table.",
        due=Due("coe", -3), blocking=True, applies_when={"financed": True},
    ),
    T(
        "cash_to_close_confirmed", "Confirm cash to close with escrow", "final_week", "you",
        why="Down payment plus closing costs plus any appraisal gap plus prepaids and "
            "impounds, minus your credit. Prepaids are the bucket first-timers forget and "
            "they are often five figures.",
        how="Get the exact figure from escrow and reconcile it against the Closing "
            "Disclosure before you move money.",
        due=Due("coe", -3), blocking=True, cost="prepaids",
    ),
    T(
        "final_walkthrough", "Do the final walkthrough before you sign", "final_week", "you",
        why="Not a re-inspection and not a new chance to negotiate — it verifies that "
            "repairs you paid for were done, that the house is as you saw it, and that "
            "everything works. If something is wrong, your leverage ends at recording.",
        how="Bring the receipts and the repair request. Check behind where the furniture "
            "was — that is where the floor damage and wall holes are. Run every faucet, "
            "flush every toilet, run the furnace and the AC, open the garage door, test "
            "every burner. Confirm the seller's belongings and debris are gone and that "
            "everything the contract says conveys is physically present.",
        due=Due("coe", -2), blocking=True,
    ),
    T(
        "utilities_transfer", "Put the utilities in your name from closing day",
        "final_week", "you",
        why="Do this before closing, not after — discovering the power is off while the "
            "movers are standing in the driveway is a bad afternoon, and some providers "
            "need several days' notice.",
        how="Electricity, gas, water, garbage and internet. Set the start date to your "
            "closing day. Ask the seller or the closing agent for the account numbers if "
            "you can — it makes the transfer far quicker than starting fresh service.",
        due=Due("coe", -2),
    ),
    T(
        "wire_cash_to_close", "Wire cash to close", "final_week", "you",
        why="The largest wire of the transaction, and therefore the one wire fraud most "
            "wants. A cashier's check for this sum is impractical and often refused.",
        how="Re-verify the instructions by voice on your independently obtained number "
            "BEFORE sending — properly, out loud, digit by digit — then call to confirm "
            "receipt afterwards.",
        due=Due("coe", -1), blocking=True,
    ),
    T(
        "sign_documents", "Sign at the notary", "final_week", "you",
        why="Signing is not closing. You do not own the house at the end of this "
            "appointment.",
        how="Bring government photo ID. Allow 60–90 minutes. Mobile notaries will come to "
            "you.",
        due=Due("coe", -1), blocking=True, cost="notary",
    ),
    T(
        "funding_recording", "Confirm funding and recording", "final_week", "escrow",
        why="The county recording the deed is the moment you own the house — not signing, "
            "not funding. Depending on the state and the recorder's queue that is the same "
            "day as funding or the morning after.",
        how="Get confirmation of recording from escrow, then collect keys. Do not schedule "
            "movers assuming keys at noon on the signing day.",
        due=Due("coe", 0), blocking=True, cost="recording",
    ),

    # -------------------------------------------------------------- post_close
    T(
        "change_locks", "Change every exterior lock and the garage code", "post_close", "you",
        why="You have no idea how many keys exist or who holds them.",
        how="All exterior doors, plus the garage keypad code.",
        due=Due("coe", 1),
    ),
    T(
        "reassessment_check", "Find out when the property is reassessed — and set money aside",
        "post_close", "you",
        why="Most counties reassess after a sale, on their own schedule, and the first bill "
            "at the new value can be far higher than what the seller was paying. Some "
            "states also send a one-time catch-up bill for the months since closing, "
            "outside your impound account.",
        how="Call the county assessor: when does the reassessment take effect, and is any "
            "supplemental or catch-up bill issued? Estimate the jump from the assessed "
            "value to your price times the local rate, and move the money to a separate "
            "account now.",
        due=Due("coe", 3),
    ),
    T(
        "save_closing_package", "Save the recorded deed, title policy and closing package",
        "post_close", "you",
        why="You will need these for years — refinancing, disputes, and the eventual sale.",
        how="Two copies, one off-site or in cloud storage.",
        due=Due("coe", 3),
    ),
    T(
        "detectors_checked", "Test smoke and CO detectors", "post_close", "you",
        why="Compliance was the seller's obligation at sale. The batteries are now yours.",
        how="Test every unit, replace anything over 10 years old.",
        due=Due("coe", 7),
    ),
    T(
        "homestead_exemption", "File for the homestead / homeowner exemption", "post_close",
        "you",
        why="Most states reduce assessed value or cap increases for an owner-occupied "
            "primary residence — but only if you file, and several have a deadline in the "
            "first months of ownership.",
        how="Find the owner-occupied exemption on the county assessor's or appraisal "
            "district's site and file it. If the form arrives automatically after "
            "recording, return it.",
        due=Due("coe", 14),
    ),
    T(
        "warranties_registered", "Register appliance and roof warranties", "post_close", "you",
        why="Some are transferable only within a window after sale.",
        how="Gather serial numbers during the move-in and register in your name.",
        due=Due("coe", 14),
    ),
    T(
        "maintenance_backlog", "Write down the deferred maintenance you chose not to fix",
        "post_close", "you",
        why="Every flagged item you priced and did not negotiate is now your backlog. "
            "Written down it is a plan; unwritten it is a series of emergencies.",
        how="Take the priced findings from the investigation period and turn them into a "
            "dated list, worst-consequence first.",
        due=Due("coe", 14),
    ),
)

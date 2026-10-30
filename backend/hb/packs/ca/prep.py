"""Preparation checklist content for the `ca` pack — docs/15 in data form: the
base tasks with the California specifics (Prop 13 and the supplemental bill, the
17-day investigation default, FAIR Plan insurance, offer-date conventions)."""

from hb.packs import compose
from hb.packs.types import Phase
from hb.packs.types import PrepTask as T
from hb.packs.us import prep as us

OWNERS = us.OWNERS
NEEDED_BY = us.NEEDED_BY

PHASES: tuple[Phase, ...] = tuple(compose.override(us.PHASES, {
    "financing": {
        "blurb": "In a market where sellers pick between six offers, a weak pre-approval is "
                 "the same as no offer.",
    },
    "team": {
        "blurb": "Every one of these is someone an agent would normally have on speed-dial "
                 "for you. Line them up before you need them, not during a 17-day clock.",
    },
}))

OVERRIDES: dict[str, dict] = {
    "equity_income_documented": {
        "why": "RSUs and bonus income are treated very differently by different lenders. Some "
               "count a two-year average, some require continuance letters, some discount "
               "them heavily. On a seven-figure purchase this can move your approved amount "
               "by hundreds of thousands.",
    },
    "understand_true_monthly": {
        "why": "The loan payment is roughly two-thirds of what you will actually pay. "
               "California property tax runs about 1.1–1.3% of the PURCHASE price every year "
               "(it resets to what you paid — the seller's old low tax bill is not yours), "
               "plus insurance which is expensive and getting worse, plus any HOA.",
        "how": "Use the Affordability calculator with a real target price. Look at the full "
               "payment breakdown, not the loan line. Then ask whether you would still be "
               "comfortable if your income dropped for six months.",
    },
    "budget_first_year_extras": {
        "why": "The supplemental tax bill is the big one: the county reassesses to your "
               "purchase price and back-bills the difference from your closing date, months "
               "later, not in your escrow account, and on a long-held home it is five figures. "
               "Then there is furniture, immediate repairs, and the deferred maintenance the "
               "inspection finds.",
    },
    "understand_jumbo_rules": {
        "label": "Learn the jumbo rules that apply at this price",
        "why": "Above the conforming limit you are in jumbo territory, where the rules are the "
               "lender's own rather than Fannie Mae's: bigger reserve requirements, tighter "
               "debt-to-income, sometimes two appraisals, and much more variation between "
               "lenders. Assumptions from a conforming-loan article will mislead you.",
    },
    "ask_lender_gap_questions": {
        "why": "In California's competitive metros, winning bids routinely land above what an "
               "appraiser will support, and the lender funds against the LOWER of price and "
               "appraised value. The difference is cash from you. You need to know your "
               "lender's behaviour before you are choosing an offer number, not after.",
    },
    "find_inspector": {
        "why": "Good inspectors run 5–10 days out. Your investigation contingency is 17 days "
               "by default and often shorter. An inspector you have to find from scratch "
               "after acceptance can cost you the ability to inspect at all.",
    },
    "find_specialists": {
        "why": "A sewer lateral scope should be automatic on this housing stock — a failed "
               "clay lateral is a $12k–$30k repair no visual inspection finds. Pre-1980 homes "
               "frequently need a structural opinion, and both specialists book out.",
    },
    "find_insurance_broker": {
        "why": "California homeowners insurance in 2026 is a genuinely hard market: carriers "
               "have exited, some homes only qualify for the state FAIR Plan plus a companion "
               "policy, and your lender will not fund without bound coverage. This can stop a "
               "closing outright, and it is the task first-time buyers leave until last.",
        "how": "Find a broker who writes across many carriers rather than a single-carrier "
               "agent. Ask them now what they would need from you, and whether wildfire zone "
               "exposure in your target cities is causing placement problems.",
    },
    "understand_escrow_title": {
        "how": "Read “What you just lost” in the closing playbook on the Closing page. "
               "The practical consequence: every 'should I' question goes to "
               "your attorney, and every 'how does this work' question goes to escrow.",
    },
    "learn_overbid_reality": {
        "label": "Learn the overbid pattern for YOUR ZIPs",
        "why": "In the Bay Area and other hot California metros, list prices are frequently "
               "set 10–40% below expected sale price to manufacture a bidding war. If you "
               "read a list price as a ceiling you will never buy anything; if you read it as "
               "meaningless you will overpay. The truth is hyper-local and the app computes "
               "it.",
    },
    "learn_offer_date_convention": {
        "label": "Learn how offer dates work here",
        "why": "Bay Area listings usually publish an offer date about 7–14 days after "
               "listing, and the disclosure packet is provided UP FRONT so buyers can review "
               "before offering. Miss the date and your only option is a pre-emptive offer "
               "that has to be knockout.",
    },
    "practice_disclosure_packet": {
        "how": "Ask a listing agent at an open house for the disclosure package on a home you "
               "are not going to bid on. They will usually send it. Read it against docs/14 §5 "
               "and see how much you can find.",
    },
    "decide_contingency_policy": {
        "why": "In this market you will be told that waiving is the price of winning. Sometimes "
               "that is true. But waiving the loan contingency puts your entire deposit — "
               "around 3% of price — at risk if financing fails, and that decision should "
               "never be made in the twenty minutes before an offer deadline.",
    },
    "set_gap_tolerance": {
        "why": "Offers here commonly include appraisal-gap coverage of 5–10%. That is real "
               "cash you must produce on top of the down payment if the appraisal lands low. "
               "Promising more than you have is how a deal collapses at your expense.",
    },
    "write_dealbreakers": {
        "how": "Be specific and physical: roads, flight paths, the Caltrain horn corridor, "
               "school-district boundaries, commute ceiling, unpermitted additions, unbolted "
               "foundations, a lot below street level. The tour checklist raises most of these "
               "automatically once you are in a house.",
    },
}

TASKS: tuple[T, ...] = tuple(compose.override(us.TASKS, OVERRIDES))

"""Preparation checklist content for the `us` base pack — docs/15 in data form,
state-neutral. `hb.prep_spec` is the engine; state packs override prose with
`hb.packs.compose` (same keys, so `settings.prep_checklist` reads under any pack).
"""

from hb.packs.types import Phase
from hb.packs.types import PrepTask as T

# Who does the work. Mostly you — that is the point of doing this without an agent.
OWNERS = ("you", "lender", "attorney", "inspector", "insurer", "cpa")

NEEDED_BY = ("before you tour", "before you offer")

PHASES: tuple[Phase, ...] = (
    Phase("credit", "Credit and the paper trail",
          "Start here on day one. Everything in this phase runs on calendar time you "
          "cannot compress, and a mistake found late costs you months."),
    Phase("money", "Know your real number",
          "Not what a bank will lend you — what you can pay and still sleep. These are "
          "different numbers and the gap between them is where people get hurt."),
    Phase("financing", "Get a pre-approval that actually means something",
          "In a market where sellers pick between several offers, a weak pre-approval is "
          "the same as no offer."),
    Phase("team", "Build your team — you have no agent",
          "Every one of these is someone an agent would normally have on speed-dial for "
          "you. Line them up before you need them, not during a contingency clock "
          "measured in days."),
    Phase("market", "Learn the market before you bid in it",
          "The app is built for exactly this. Months of passive watching is what turns "
          "a list price into information."),
    Phase("rules", "Decide your rules while you are calm",
          "Every rule here is one you will be tempted to break inside a bidding war. "
          "Write them down now, when nothing is at stake."),
    Phase("logistics", "Ready to walk houses",
          "The small practical setup that makes a Saturday of open houses produce "
          "evidence instead of vibes."),
)

TASKS: tuple[T, ...] = (
    # ------------------------------------------------------------------ credit
    T(
        "pull_credit_reports", "Pull all three credit reports and your real score",
        "credit",
        why="Your rate, and on a jumbo loan your approval itself, keys off your middle "
            "score. Roughly a quarter of reports contain an error, and a wrong collection "
            "or a stranger's account can cost you a rate tier or the loan.",
        how="Get the reports free at annualcreditreport.com (the government-mandated site — "
            "the ones advertising 'free scores' sell you something). Pull Equifax, "
            "Experian and TransUnion. Your card issuer or bank probably shows a FICO score "
            "free. Read every account, every address, every inquiry.",
        lead_time="30–60 days if you find an error",
    ),
    T(
        "dispute_credit_errors", "Dispute anything wrong — immediately", "credit",
        why="A dispute takes 30–60 days by law. Started in month one it is invisible; "
            "started the week you find a house it blocks the whole purchase.",
        how="File disputes online with each bureau directly, in writing, with documents. "
            "Keep every confirmation number. Re-pull afterwards to confirm the fix landed.",
        lead_time="30–60 days",
    ),
    T(
        "freeze_financial_life", "Stop changing anything financial — starting now",
        "credit",
        why="This rule usually appears at the end of the process, in the escrow checklist. "
            "It should start the day you decide to buy, because underwriters look back "
            "two months at your accounts and two years at your employment.",
        how="No new credit cards or car loans. No job change or move to contractor status "
            "if avoidable. No large unexplained deposits or transfers between accounts. "
            "If you must move money, keep the paper trail. This holds until you have keys.",
    ),
    T(
        "assemble_document_pack", "Assemble the loan document pack in one folder", "credit",
        why="Underwriting will ask for all of it, usually twice, usually on a deadline. "
            "Having it ready turns a two-week back-and-forth into an afternoon.",
        how="Two years of W-2s and tax returns (all schedules), 30 days of pay stubs, 60 "
            "days of statements for EVERY account you will use, photo ID, and — if equity "
            "is part of your income or down payment — vesting schedules, grant statements "
            "and brokerage statements showing sales. Scan everything to PDF.",
        lead_time="a weekend",
    ),
    T(
        "equity_income_documented", "Sort out how equity compensation will be counted",
        "credit",
        why="RSUs and bonus income are treated very differently by different lenders. Some "
            "count a two-year average, some require continuance letters, some discount "
            "them heavily. On a large purchase this can move your approved amount by "
            "hundreds of thousands.",
        how="Ask each lender explicitly: 'how do you underwrite RSU income, what history "
            "do you need, and do you require a continuance letter from my employer?' Get "
            "the answer before you compare their rates — it matters more than the rate.",
        needed_by="before you offer",
    ),
    T(
        "gift_funds_sorted", "If family is helping, sort the gift paperwork early", "credit",
        why="Lenders require gift funds to be documented and often 'seasoned' — sitting in "
            "your account for 60 days — with a signed gift letter proving it is not a loan. "
            "Money that arrives the week of closing raises questions you do not want then.",
        how="Move it early, keep the transfer records, and get the donor to sign the "
            "lender's gift letter template. Ask your lender for their exact requirements — "
            "they vary.",
        lead_time="60 days of seasoning",
    ),

    # ------------------------------------------------------------------- money
    T(
        "count_your_cash", "Count your actual available cash, honestly", "money",
        why="Down payment is the number people track. It is not the number that matters. "
            "You also need closing costs (~1.5% of price), possibly an appraisal gap in "
            "cash, moving costs, and reserves left over afterwards.",
        how="Add up everything liquid, then subtract what you will not actually spend — "
            "emergency fund, tax owed on any stock you sell to fund this. Enter the result "
            "as 'cash available' in the Affordability page's buyer profile; the app uses it "
            "as a hard constraint in the bid back-solver.",
    ),
    T(
        "set_reserves_floor", "Decide your post-closing reserves floor", "money",
        why="Winning the house with nothing left is losing. The app warns below six months "
            "of full housing payment — and jumbo lenders often REQUIRE six to twelve months "
            "in reserves to approve you at all, so this is both prudence and a "
            "qualification requirement.",
        how="Six months of the full payment is the floor the app enforces. Decide now "
            "whether yours is higher, and treat it as untouchable when the bidding starts.",
    ),
    T(
        "understand_true_monthly", "Work out the true monthly cost, not the mortgage",
        "money",
        why="The loan payment is only part of what you will actually pay. Property tax is "
            "charged on what the county assesses — which after a sale usually resets "
            "toward what you paid, so the seller's old tax bill is not yours — plus "
            "insurance, which is expensive and getting worse, plus any HOA.",
        how="Use the Affordability calculator with a real target price; it applies the "
            "effective tax rate from your geography file. Look at the full payment "
            "breakdown, not the loan line. Then ask whether you would still be "
            "comfortable if your income dropped for six months.",
    ),
    T(
        "budget_first_year_extras", "Budget the first-year surprises", "money",
        why="Reassessment is the big one in most states: the county resets the assessed "
            "value after the sale and the first bill at the new value — sometimes a "
            "one-time catch-up bill back-dated to closing — lands months later and not in "
            "your escrow account. Then there is furniture, immediate repairs, and the "
            "deferred maintenance the inspection finds.",
        how="Set aside a first-year fund on top of reserves. The Closing page's cost panel "
            "and the tour app's deferred-maintenance rollup both feed this.",
    ),
    T(
        "decide_down_payment", "Decide your down payment target", "money",
        why="Twenty percent avoids mortgage insurance and is the assumption most jumbo "
            "pricing is built around. Less is possible but changes your rate, your monthly "
            "cost and your competitiveness.",
        how="Enter it in the buyer profile as a dollar figure. Run the affordability "
            "numbers at 20% and at whatever else you are considering, and compare the true "
            "monthly cost rather than the headline rate.",
    ),

    # --------------------------------------------------------------- financing
    T(
        "learn_preapproval_tiers", "Understand what counts as a real pre-approval",
        "financing",
        why="Three different things get called pre-approval. Pre-QUALIFICATION is a "
            "conversation and worth nothing. Standard pre-APPROVAL means a credit pull and "
            "stated income. An UNDERWRITTEN pre-approval means a human underwriter has "
            "reviewed your actual documents. In a multiple-offer situation the third wins "
            "and the first is ignored.",
        how="Ask each lender which one they are giving you, in those words. Ask for the "
            "underwritten version even though it takes longer and needs the document pack.",
        lead_time="1–3 weeks",
    ),
    T(
        "shop_three_lenders", "Shop at least three lenders, including a broker", "financing",
        why="Rates and fees on the same borrower routinely differ by enough to matter over "
            "thirty years, and jumbo programs vary far more than conforming ones. A "
            "mortgage broker shops multiple wholesale lenders at once; a bank sells you "
            "only its own product. You want both kinds in the comparison.",
        how="Try a big bank, a credit union, and an independent mortgage broker. Ask each "
            "for a written Loan Estimate on the same day for the same scenario — that form "
            "is standardised precisely so you can compare it line by line.",
        owner="lender", lead_time="1–2 weeks",
    ),
    T(
        "credit_pull_window", "Do all your rate shopping inside a two-week window",
        "financing",
        why="Multiple mortgage inquiries inside a short window count as ONE inquiry for "
            "scoring purposes. Spread over months they count separately and drag your score "
            "down exactly when you need it.",
        how="Line up your lender conversations, then let them all pull within the same "
            "week or two. Do not let one pull in January and another in April.",
    ),
    T(
        "understand_jumbo_rules", "Learn the jumbo rules if your price is above the limit",
        "financing",
        why="Above the conforming loan limit you are in jumbo territory, where the rules "
            "are the lender's own rather than Fannie Mae's: bigger reserve requirements, "
            "tighter debt-to-income, sometimes two appraisals, and much more variation "
            "between lenders. Assumptions from a conforming-loan article will mislead you.",
        how="Ask each lender: reserve months required, maximum debt-to-income, whether two "
            "appraisals are needed at your price, and maximum seller credit allowed. Write "
            "the answers down — the seller-credit cap decides how you take a repair "
            "concession later.",
        needed_by="before you offer",
    ),
    T(
        "get_preapproval_letter", "Get the pre-approval letter and note its expiry",
        "financing",
        why="You cannot make a serious offer without one, and it expires — usually in 60 to "
            "90 days. An expired letter attached to an offer reads as disorganised.",
        how="Ask for a letter you can have re-issued at a specific number quickly, so you "
            "are not showing a seller your true ceiling on every offer. Diary the expiry "
            "date now.",
        owner="lender", needed_by="before you offer",
    ),
    T(
        "ask_lender_gap_questions", "Ask your lender the appraisal-gap questions in advance",
        "financing",
        why="In a competitive market, winning bids routinely land above what an appraiser "
            "will support, and the lender funds against the LOWER of price and appraised "
            "value. The difference is cash from you. You need to know your lender's "
            "behaviour before you are choosing an offer number, not after.",
        how="Ask: what happens if the appraisal comes in low, will you accept a "
            "reconsideration of value with comps, and how quickly can you order the "
            "appraisal? Then set your gap tolerance in the buyer profile so the bid "
            "back-solver treats it as a real cash constraint.",
        owner="lender", needed_by="before you offer",
    ),

    # -------------------------------------------------------------------- team
    T(
        "find_inspector", "Find and pre-book a general home inspector", "team",
        why="Good inspectors run 5–10 days out. Your inspection contingency is often ten "
            "days or fewer. An inspector you have to find from scratch after acceptance "
            "can cost you the ability to inspect at all.",
        how="Call two or three now. Ask their lead time in a normal week, whether they will "
            "let you walk with them for the full inspection, and what their report "
            "turnaround is. Tell them you are shopping and will call with a real date.",
        owner="inspector",
    ),
    T(
        "find_specialists", "Get a sewer scope and a structural engineer on the list", "team",
        why="A sewer lateral scope should be automatic on older housing — a failed clay or "
            "Orangeburg lateral is a five-figure repair no visual inspection finds. Older "
            "homes frequently need a structural opinion, and both specialists book out.",
        how="Ask your general inspector who they trust for each; that referral is usually "
            "better than a search result. Save the numbers in your deal team.",
        owner="inspector",
    ),
    T(
        "find_insurance_broker", "Find an independent insurance broker — early", "team",
        why="Homeowners insurance is a genuinely hard market in a growing number of "
            "states: carriers have pulled back, some homes only qualify for a state "
            "last-resort plan, and your lender will not fund without bound coverage. This "
            "can stop a closing outright, and it is the task first-time buyers leave until "
            "last.",
        how="Find a broker who writes across many carriers rather than a single-carrier "
            "agent. Ask them now what they would need from you, and whether hazard "
            "exposure in your target cities is causing placement problems.",
        owner="insurer",
    ),
    T(
        "test_insurance_quote", "Get a practice insurance quote on a real listing", "team",
        why="An abstract 'insurance is expensive' is useless. A real quote on a real house "
            "in your target ZIP tells you what your monthly number actually is, and whether "
            "the homes you like are insurable at all.",
        how="Pick a listing you are watching, send the broker the address, year built, roof "
            "type and construction, and ask for a rough annual figure. Feed it into the "
            "buyer profile's insurance estimate so the affordability maths is real.",
        owner="insurer", needed_by="before you offer",
    ),
    T(
        "understand_escrow_title", "Understand what escrow and title do — and don't do",
        "team",
        why="They are the two parties you will speak to most during closing, and both are "
            "required to be NEUTRAL. They will explain process precisely and refuse to "
            "advise you entirely. Buyers routinely mistake this for having help.",
        how="Read the closing playbook's opening section on the Closing page. The practical "
            "consequence: every 'should I' question goes to your attorney, and every 'how "
            "does this work' question goes to escrow or the closing agent.",
        needed_by="before you offer",
    ),

    # ------------------------------------------------------------------ market
    T(
        "set_target_geography", "Set your target cities, ZIPs and price band", "market",
        why="Everything the app does — alerts, comps, the dashboards — is scoped to this. A "
            "target list that is too broad produces noise you will learn to ignore.",
        how="Set them in geography.toml (cities, ZIPs, counties, the price band). Be honest "
            "about commute and school-district boundaries; they move prices more than "
            "square footage does.",
    ),
    T(
        "watch_the_dashboards", "Watch the market weekly for at least a month before bidding",
        "market",
        why="This is the whole premise of the product: months of passive observation is what "
            "turns a list price into information. You cannot judge whether a given price is "
            "good for a house until you have watched thirty similar ones sell.",
        how="Once a week, look at the Dashboard's per-ZIP tiles, the Supply page, and the "
            "Recently Sold feed. You are looking for one thing above all: what homes "
            "actually sell for versus what they were listed at.",
    ),
    T(
        "learn_overbid_reality", "Learn the sale-to-list pattern for YOUR ZIPs", "market",
        why="In some markets list prices are set well below the expected sale price to "
            "manufacture a bidding war; in others the list price is a ceiling and homes "
            "sell under it. Read the wrong pattern into your market and you will either "
            "never buy anything or overpay. The truth is hyper-local and the app computes "
            "it.",
        how="On the Recently Sold page and each listing's overbid panel, look at the "
            "sale-to-list distribution for your ZIPs. Learn the median and the spread. That "
            "number, not the list price, is what tells you where a house will land.",
    ),
    T(
        "learn_offer_date_convention", "Learn how offers work in your market", "market",
        why="Some markets run published offer dates with the disclosure packet provided up "
            "front; others take offers as they come and disclosures arrive after "
            "acceptance. Which one you are in changes how fast you must move and when you "
            "get to read the paperwork.",
        how="Watch a few listings through their full cycle without bidding. Note when the "
            "packet appears, when offers are due, and what it eventually sold for.",
    ),
    T(
        "read_the_tour_playbook", "Read the tour playbook before your first open house",
        "market",
        why="You get about 45 minutes in a house and you are a first-time buyer. Without a "
            "system you will remember the kitchen and miss the foundation.",
        how="Read docs/13. It is organised in the order you should physically walk a "
            "property, and tells you which findings are $3k annoyances and which are $30k "
            "renegotiations.",
    ),
    T(
        "practice_disclosure_packet", "Read one full disclosure packet before you need to",
        "market",
        why="A packet is 100–300 pages and you will get days to read it under pressure. "
            "Reading one cold, with nothing at stake, is the cheapest possible practice.",
        how="Ask a listing agent at an open house for the disclosure package on a home you "
            "are not going to bid on. They will usually send it. Read it against the "
            "closing playbook's disclosure section and see how much you can find.",
        needed_by="before you offer",
    ),

    # ------------------------------------------------------------------- rules
    T(
        "set_max_price", "Set your maximum price — and write it down", "rules",
        why="The single most useful thing you can do before a bidding war is decide, coldly, "
            "the number above which you walk. Everyone believes they have one. People who "
            "have not written it down do not.",
        how="Use the offer helper's ceiling and the affordability back-solver, then commit. "
            "Record it as 'my max bid' on tracked homes so it is visible when you are "
            "deciding, not a number you renegotiate with yourself at 11pm.",
        needed_by="before you offer",
    ),
    T(
        "decide_contingency_policy", "Decide which contingencies you will and will not waive",
        "rules",
        why="In a competitive market you will be told that waiving is the price of winning. "
            "Sometimes that is true. But waiving the loan contingency puts your entire "
            "deposit — typically 1–3% of price — at risk if financing fails, and that "
            "decision should never be made in the twenty minutes before an offer deadline.",
        how="Decide now, in writing, for each of the three: investigation, appraisal, loan. "
            "A defensible middle path is shortening them rather than waiving, and covering "
            "a defined appraisal gap in cash. Discuss it with your attorney before the first "
            "offer, not the first time it comes up.",
        needed_by="before you offer",
    ),
    T(
        "set_gap_tolerance", "Decide the appraisal gap you can actually cover", "rules",
        why="Competitive offers often include appraisal-gap coverage. That is real cash you "
            "must produce on top of the down payment if the appraisal lands low. Promising "
            "more than you have is how a deal collapses at your expense.",
        how="Set the gap tolerance in your buyer profile. The bid back-solver then treats it "
            "as a hard cash constraint and will not recommend a bid you cannot fund.",
        needed_by="before you offer",
    ),
    T(
        "write_dealbreakers", "Write down your deal-breakers", "rules",
        why="Under competition, standards erode one small concession at a time. A written "
            "list is what stops 'I would never buy on that road' turning into 'the road is "
            "not that bad'.",
        how="Be specific and physical: roads, flight paths, train horn corridors, "
            "school-district boundaries, commute ceiling, unpermitted additions, foundation "
            "findings, a lot below street level. The tour checklist raises most of these "
            "automatically once you are in a house.",
    ),
    T(
        "decide_commission_position", "Decide what you want on buyer-side compensation",
        "rules",
        why="Since the 2024 NAR settlement, buyer-broker compensation is negotiated directly "
            "and nothing about it is published on the MLS. With no buyer's agent there is no "
            "buyer-side commission to pay — that amount is not automatically yours, but it "
            "is a live term, and it is only negotiable BEFORE acceptance.",
        how="Decide whether you want it as a price reduction or a closing-cost credit — "
            "credits are capped by lender rules, so above the cap take it as price. Raise it "
            "when you make the offer. After acceptance your leverage on it is gone.",
        needed_by="before you offer",
    ),

    # --------------------------------------------------------------- logistics
    T(
        "setup_field_mode", "Pick your tour homes in Field mode", "logistics",
        why="Field mode walks the tour checklist one home at a time, in big one-tap "
            "screens, pruned to its age and raising red flags as you answer. Decide what you will see "
            "before you are standing in a stranger's kitchen, not after.",
        how="Open Field and pick the homes you will see that day - it lists "
            "the homes on your Tracker and your open-house schedule; search by address for "
            "anything else.",
    ),
    T(
        "pack_tour_kit", "Put together the tour kit", "logistics",
        why="Four cheap objects turn 'the basement felt a bit damp' into an observation you "
            "can price.",
        how="A flashlight brighter than your phone's, a tape measure, a level app and a "
            "compass app, and optionally a $10 outlet tester that tells you about grounding "
            "in four seconds. Charge the phone.",
    ),
    T(
        "get_on_agent_lists", "Get on the listing agents' mailing lists", "logistics",
        why="Coming soon and pre-market listings circulate among agents before they hit the "
            "portals. Unrepresented buyers see them last unless they ask.",
        how="At open houses, give the listing agent your email and say what you are looking "
            "for. Be straightforward that you are unrepresented — it changes nothing about "
            "whether they will add you.",
    ),
    T(
        "practice_asking_for_packet", "Practise asking for the disclosure package",
        "logistics",
        why="It is the single most useful sentence in your vocabulary at an open house and "
            "it feels awkward the first time.",
        how="'Could you send me the disclosure package for this one?' That is the whole "
            "sentence. Ask on every house you are seriously considering.",
    ),
)

# 14 — Closing Playbook: offer accepted → keys, without a buyer's agent

Companion to `13-tour-playbook.md`. That document ends when you walk out of the house;
`01-domain-primer.md` and `06-algorithms.md` end when you decide what to bid. This one starts
the moment the seller signs, which is the point at which every other document in this repo
goes quiet.

> **This is not legal advice.** It is a working checklist assembled from public sources,
> written for a self-represented buyer of a single-family home in **California** (the `ca`
> pack); other states differ on forms, contingency removal and reassessment, and get the
> `us` base pack's tasks instead (`docs/packs/README.md`).
> California is an escrow state and does not require an attorney at closing — but you are
> buying a $2–3M asset with **no agent on your side of the table**, and a California real
> estate attorney on a flat fee (**$1.5k–4k**) to review the contract and ride the escrow is
> the highest-value thing on this entire page. Buy it. Every number here is an estimate,
> dated **August 2026**, and must be re-verified against a current source before you rely on
> it.

---

## 1. What you just lost

An accepted offer converts a shopping problem into an **operations problem on a deadline**.
The buyer's agent you don't have was, in practice, a project manager. Here is the job list
and who now holds each piece:

| Job an agent did | Who holds it now | Notes |
|---|---|---|
| Tracking every contract deadline | **You** | This is the single biggest risk. It is why `/closing` exists. |
| Chasing the disclosure packet out of the listing side | **You** | Expect to ask twice. Ask in writing, always. |
| Explaining what's in the packet | **You + attorney** | §5. The listing agent cannot advise you. |
| Booking and attending inspections | **You** | §6. Book on day 1 — good inspectors are 5–10 days out. |
| Knowing which forms exist and when | **Attorney / escrow / listing agent** | §2, §11 |
| Drafting repair requests and contingency removals | **Attorney** | §10, §11 |
| Keeping lender, escrow, and title talking to each other | **You** | Nobody else has all three phone numbers. |
| Reading the Closing Disclosure against the Loan Estimate | **You** | §12. Nobody checks this for you. Ever. |
| Final walkthrough | **You** | §12 |

**Hiring the pieces back**, 2026 Bay Area:

| Service | Cost | Worth it? |
|---|---|---|
| Real estate attorney, flat-fee contract review + escrow oversight | $1,500 – $4,000 | **Yes.** 0.1% of the purchase price to have someone whose duty runs to you. |
| Transaction coordinator (TC) | $500 – $900 | Optional. Buys deadline-chasing and paperwork, not advice. `/closing` covers most of it. |
| Escrow officer | Included in escrow fee | Neutral by law. Will answer process questions precisely and advice questions not at all. |

The distinction that matters all the way through: **escrow and title are neutral**. They are
not on your side, they are on nobody's side, and that is their job. When you need someone
whose duty runs to *you*, it is the attorney or it is nobody.

---

## 2. Forms and agency when you have no agent

**C.A.R. forms are member-licensed.** The California Association of REALTORS® is a **trade
association, not a government body**, and its form library — the RPA and every companion form
named in this document — is copyrighted work product licensed to its members. As an
unrepresented buyer you do not have an account; you receive the forms *from the listing
agent*, and you fill them in and sign them. This is normal and it is how most unrepresented
purchases run.

### 2.1 How you actually get a contract

Three routes, and the choice matters more than it looks.

| Route | How it works | When it makes sense |
|---|---|---|
| **Listing agent sends you the C.A.R. forms** | They email you the RPA (usually blank, via DocuSign/zipForm) and you complete the terms yourself. Expect them to send it and then go quiet — see below. | **The default, and the right answer for a normal on-market purchase.** |
| **Attorney drafts or reviews** | A California real estate attorney either writes the contract or — far more usefully — reviews the C.A.R. RPA before you sign it. $1,500–$4,000 flat. | Always worth it for review. Full drafting only for unusual deals: off-market, unrepresented seller, probate/trust, seller financing. |
| **Flat-fee / limited-service broker** | A brokerage writes the offer and handles the paperwork for a flat fee without full representation. | If you want C.A.R. form access plus someone licensed who *can* answer questions, without paying a percentage. |

**Why the agent sends blanks rather than filling them in.** Helping an unrepresented buyer
complete an offer risks creating an *implied agency* — a court later deciding they effectively
represented you, with all the duties that carries. Their broker's compliance rules will tell
them not to. So the realistic interaction is: they provide the form, they will confirm
mechanical facts ("the seller wants a 30-day close"), and they will decline to tell you what
number to write or which contingency to keep. That is not obstruction; it is them protecting
their broker, and it is exactly why you need your own attorney.

### 2.2 "Is a contract I drafted myself legal?"

Three separate questions hide inside that one, with three different answers.

1. **Would it be enforceable?** Yes, in principle. California requires that a real-property
   contract be **in writing and signed** (Statute of Frauds, Civ. Code §1624) with the ordinary
   elements — parties, property, price, mutual assent. **No statute requires the C.A.R. RPA or
   any particular form.** And because you are a *principal* buying for yourself, real estate
   licensing law does not restrict you from preparing your own contract; that restriction is
   about drafting for other people for compensation.
2. **Is it a copyright problem?** It can be. Reproducing C.A.R.'s RPA text — copying its
   paragraphs, or handing over something you call "the RPA" — without a licence is
   infringement, and C.A.R. does enforce. A genuinely original document is fine; a
   near-copy of theirs is not.
3. **Will it actually be accepted?** **This is the question that decides your outcome, and the
   answer is usually no.** A bespoke contract from an unrepresented buyer means the listing
   side must route it to their broker and probably a lawyer before responding. That costs them
   days and money, on a property where — in this market — other offers are sitting on familiar
   paperwork. Yours gets set aside on friction alone, before anyone evaluates your price.

There is a fourth, quieter reason to stay on the standard form: the RPA's machinery —
contingency removal, the Notice to Buyer to Perform, delivery definitions, liquidated damages,
the mediation/arbitration election — carries decades of case law and settled industry meaning.
Bespoke wording for the same ideas is an invitation to argue about what it meant, at exactly
the moment you least want to. (It would also break this app's assumptions: `closing_spec.py`
dates everything off RPA-style 17/17/21 contingencies removed by signed CR.)

**The play that gets the benefits of both:** take the C.A.R. RPA from the listing side, decide
**every term in it yourself** (that is the part that is genuinely yours — price, contingency
periods, deposit, close date, gap coverage, what you waive), have an attorney read it before
you sign, and use a short **buyer's addendum** for anything the form does not cover. An
addendum attached to a standard contract gets accepted; a replacement contract does not.

**Where AI genuinely earns its place here** is *deciding and reviewing*, not *producing the
base contract*: working out which contingencies to keep and for how many days, back-solving
your maximum bid and gap exposure (`06 §6`), reading the packet and the counters and telling
you what you just agreed to, and drafting addendum and repair-request language for your
attorney to check. Use it for judgement, not as a form printer.

> **Watch for the June 2026 C.A.R. listing-agreement rewrite**, which specifically reworked how
> unrepresented buyers and compensation are handled. Anything you read online older than that
> may describe the previous regime — confirm current practice with your attorney.

### 2.3 The two agency documents

Two agency documents you will meet immediately:

- **AD — Disclosure Regarding Real Estate Agency Relationships.** Statutory. Defines seller's
  agent, buyer's agent, and dual agent. You will be given it and asked to sign that you read
  it. Read it.
- **BNA — Buyer Non-Agency Agreement.** The listing agent's written record that they
  represent the **seller only** and do **not** represent you. Post-NAR-settlement this has
  become the standard instrument for documenting an unrepresented buyer. Signing it is fine —
  it is describing reality — but understand what it says: the only licensed professional in
  the transaction owes their loyalty to the person across the table.

**Dual agency** is legal in California with disclosure and written consent from both sides. A
listing agent may offer to "write you up" and represent you both. Understand the trade: you
gain someone who knows the file and can produce the paperwork; you lose any adversarial
advocate, because they now cannot advise either party on price or terms against the other.
For a first-time buyer in a competitive market this is usually a worse deal than staying
unrepresented and paying an attorney.

**Compensation is now a live term.** Since the August 2024 NAR settlement, buyer-broker
compensation is no longer published on the MLS and no seller is obliged to pay it. With no
buyer's agent, there is no buyer-side commission to pay. That amount does not automatically
become yours — but it is negotiable, and the two shapes it takes are a **lower purchase
price** or a **credit toward your closing costs**. A credit is capped by lender rules (it
cannot exceed your actual closing costs, and jumbo programs cap seller concessions — commonly
3–6% of price depending on LTV), so above that cap, take it as price. Raise this **before**
acceptance; after acceptance your leverage on it is gone.

**Start the conversation on this footing, not inside a portal.** Every listing's detail page
carries a Contact card (`08 §3 1c`) with the listing agent's direct line and email off the MLS
record. When you write, say you are unrepresented, are asking for no buyer-side compensation,
and are not asking them to represent you — and ask for the disclosure package now and the
blank C.A.R. RPA, AD and BNA if you go ahead (§2.1: the forms reach you only through them).
Contact them directly — never the
Realtor.com / Redfin / Zillow "Contact agent" or "Request a tour" button, which routes you to a
*buyer's* agent whose first move is a representation agreement with a fee attached.

---

## 3. Day 0–3: lock it down

### Get the fully executed contract

"Acceptance" is a specific moment: the last signature *communicated back* to the offering
party. **Every deadline in the transaction counts from that date**, so the first task is to
obtain the complete, fully executed contract — every page, every initial box, every counter
offer in order, every addendum — and confirm the acceptance date in writing.

Do not accept a summary email. Get the PDF. If the counters are numbered CO-1, CO-2, CO-3,
you need all three; the operative terms are the ones in the last one signed.

Then read your own contract and write down these five numbers, because everything else
derives from them:

1. **Acceptance date**
2. **Purchase price**
3. **Initial deposit (EMD) amount and days to deliver**
4. **Investigation / appraisal / loan contingency periods** (the RPA's defaults are 17 / 17 /
   21 calendar days, but only *your* negotiated numbers matter)
5. **Close of escrow date (COE)**

These are exactly the fields the `deals` row stores, and every task date on `/closing` is
computed from them.

### Open escrow and wire the EMD

Escrow is opened by the listing side, typically same-day or next-day. You should receive an
escrow number, the officer's name and direct line, and a wire instruction packet.

The initial deposit — commonly 3% of price, so **$60k–$90k in this band** — is due within the
contract's stated window, **3 business days after Acceptance** under the RPA default. Late
delivery is a curable default: the seller can serve a Notice to Buyer to Perform (§4) and,
after that, cancel. Do not be late for a purely administrative reason.

> ### ⚠ Wire fraud — read this before you move any money
>
> Real estate wire fraud is a targeted, well-run industry, and a $2–3M peninsula purchase is
> exactly the profile it hunts. The attack is simple: the criminal monitors an email thread,
> then sends you revised wire instructions from a lookalike domain at the moment you are
> expecting them. Money sent to the wrong account is usually **gone**.
>
> The rules, without exception:
>
> 1. **Never** take wire instructions from an email, a text, a PDF attachment, or a link.
> 2. Before every wire, **call the escrow officer and read the account number back to them
>    aloud.** Use a phone number you obtained independently — from the escrow company's
>    website or an earlier phone call — **never** one printed in the email containing the
>    instructions.
> 3. Treat *any* change to previously given instructions as fraud until proven otherwise.
>    Legitimate mid-escrow changes are rare.
> 4. Call escrow again an hour after sending to confirm receipt. If something is wrong, the
>    first hours are the only hours in which recall has a real chance.
> 5. Tell your bank it is a real estate closing wire. Ask what their recall procedure is
>    *before* you need it.

### Same-day housekeeping

- **Send the executed contract to your lender the day you get it.** The loan contingency
  clock (21 days by default) is the tightest one in the deal and it is already running.
- **Start shopping homeowners insurance today.** Not next week. See §9 — in California in
  2026 this is a genuine deal-killer and it is the task first-timers schedule last.
- **Put every deadline in a calendar with two-day-prior reminders.** `/closing` does this,
  but a second copy in the calendar you actually look at costs nothing.

---

## 4. The contingency clock

This is the mechanism that a buyer without an agent most often misunderstands, and the one
that puts the deposit at risk.

### The three clocks

C.A.R. RPA defaults, counted in **calendar days after Acceptance**:

| Contingency | Default | What it protects |
|---|---|---|
| **Investigation** (physical condition) | **17 days** | Your right to inspect and to walk on what you find |
| **Appraisal** | **17 days** | Your right to walk if the appraisal comes in below the price |
| **Loan** | **21 days** | Your right to walk if financing fails |

In the target market these are routinely shortened or waived to win. Whatever you negotiated
is what governs; the app stores your numbers per deal and never assumes the defaults once a
deal is created.

### California removes contingencies *actively*

This is the part that surprises people coming from other states. **A California contingency
does not expire on its own.** It stays in force until you affirmatively remove it in writing
by signing a **Contingency Removal (Form CR)**. Passing the date does not automatically waive
your protection — and it does not automatically cancel the deal either. It simply puts you in
breach of a timeline the seller can now act on.

What the seller does about it is the **Notice to Buyer to Perform (Form NBP)**:

- It must be delivered in writing with receipt acknowledged.
- It starts a **48-hour** clock (2 days).
- If you have not signed the CR or taken the required action when that clock runs out, the
  seller may **cancel the contract** — and then fight you over the deposit.

An NBP cannot be served before the contingency date has actually passed, and the seller must
have performed their own obligations. But the practical lesson is: **know what an NBP is
before one shows up**, because two days is not enough time to learn.

### A worked timeline

Acceptance **Monday 14 September 2026**, RPA defaults, COE at 30 days:

| Date | Day | Event |
|---|---|---|
| Mon Sep 14 | 0 | **Acceptance.** All clocks start. |
| Thu Sep 17 | +3 business | **EMD due** at escrow |
| Mon Sep 21 | 7 | Seller's disclosure delivery window closes; inspections underway |
| Thu Oct 1 | 17 | **Investigation contingency removal due** · **Appraisal contingency removal due** |
| Mon Oct 5 | 21 | **Loan contingency removal due** |
| Fri Oct 9 | 25 | Final verification of condition (walkthrough) |
| Mon Oct 12 | 28 | **Closing Disclosure** must be in hand (COE − 3 business days) |
| Wed Oct 14 | 30 | **COE** — sign, fund, record, keys |

Note how little slack there is: the general inspection has to be *booked* in the first two
days for its report to arrive with enough time to price repairs, request a credit, and still
decide by day 17.

---

## 5. The disclosure packet, read adversarially

On the Peninsula the packet usually arrives *before* offers (`01 §1`), which means you may
have read it already. Re-read it after acceptance anyway, slowly, with the inspection reports
next to it — the second reading with a signed contract is a different reading.

| Document | What it is | What to actually look for |
|---|---|---|
| **TDS** — Real Estate Transfer Disclosure Statement | Statutory seller disclosure of known defects | Every "yes" box, and every question left blank. Blanks are not answers. |
| **SPQ** — Seller Property Questionnaire | The long-form supplement; where the real history lives | Neighbor disputes, insurance claims, deaths, prior repairs "by owner", pets, water intrusion |
| **NHD** — Natural Hazard Disclosure | Third-party report: flood, fire, seismic, dam inundation | Cross-check against the app's hazard chips (`05 §7`). Every "yes" is an insurance conversation. |
| **Lead-based paint disclosure** | Federal, **any home built before 1978** | Carries a 10-day inspection right unless waived — separate from the RPA contingency |
| **Preliminary Title Report** | What title will insure, and what it won't | **The exceptions schedule** — see below |
| **Seller-supplied inspections** | Often general + pest, sometimes roof/sewer | Useful, but see the warning below |
| **Pest / WDO report** | Wood-destroying organisms | **Section 1 vs Section 2** — see below |
| **HOA documents** | If applicable — CC&Rs, budget, reserves, minutes | Reserve funding %, pending special assessments, litigation, rental caps |
| **Megan's Law disclosure** | Statutory notice; database is public | You do the lookup; nobody does it for you |
| **City/point-of-sale reports** | Varies by city — §7 | Sewer lateral certificate, resale inspection report |
| **Mello-Roos / special assessments** | Districts that add to your tax bill | Rare in the older peninsula cities, common in newer developments |

Three things worth calling out specifically:

**Pest report Section 1 vs Section 2.** Section 1 is *active* infestation or damage —
existing, present, costing money now. Section 2 is *conditions likely to lead to* infestation
— preventive. When you compare bids or ask for a credit, the Section 1 total is the number
that matters. `docs/01 §4` already names this as a blind spot; here is where it gets used.

**The prelim's exception schedule is the part nobody reads.** The prelim is not a title
search result you skim for liens — it is a list of everything the title company will
*exclude* from coverage. Easements running through the yard, deed restrictions, shared
driveway agreements, encroachments, unreleased old liens, boundary disputes. Read the
exceptions and request copies of every recorded document referenced by number. This is a
task where an attorney's hour pays for itself.

**Seller-supplied inspections are a starting point, not a substitute.** The inspector was
hired by the seller, and the report is scoped and worded accordingly. It also gives you no
recourse — you are not their client and cannot rely on it. Order your own (§6).

**Delivery matters for your rights.** Several disclosure rights are keyed to *delivery*, not
to Acceptance, and the statutory right to rescind after receiving certain disclosures runs 3
days from personal delivery or 5 days from mail. Note the date you actually received each
document, in writing.

---

## 6. Inspections you order yourself

Book on **day 1**. Good peninsula inspectors run 5–10 days out, and the report is worthless
if it lands after the day you had to decide.

**Attend the general inspection in person.** Not the last hour — the whole thing. Three or
four hours walking a house with someone who does this daily is the single best education
available to a first-time buyer, and what they say out loud is consistently more useful than
what survives into the written report.

| Inspection | Cost | When to order it |
|---|---|---|
| **General home inspection** | $600 – $1,200 | **Always.** Book day 1. |
| Pest / WDO | $150 – $450 | Always, unless a current independent report exists |
| **Sewer lateral video scope** | $300 – $700 | **Always** in this market. Mandatory in the point-of-sale cities (§7); pre-1975 homes are likely clay (`13 §4`) |
| Roof | $300 – $800 | Any roof the general inspector flags, or estimated age 15+ |
| Structural / foundation engineer | $600 – $2,500 | Pre-1980, any settlement crack, any hillside lot, any addition |
| Chimney (level 2, camera) | $250 – $600 | Any masonry chimney, especially pre-1980 unreinforced |
| HVAC or electrical specialist | $250 – $600 | When the general report says "recommend further evaluation" — that phrase is a referral, treat it as one |
| Pool / spa | $200 – $450 | If present |
| Contractor bids on anything large | Usually free | Before you ask for a credit. "The inspector said" is weak; a written bid is not. |

Two rules:

- **"Recommend further evaluation by a qualified specialist" is not filler.** It is the
  general inspector telling you they found something outside their scope and it needs a
  trade. Chase every instance before your investigation contingency runs out.
- **Price the findings before you decide.** The tour app already rolls flagged defects into a
  deferred-maintenance range using `COST_BANDS` (`13 §10`); the inspection report replaces
  those estimates with real numbers. That total is what you take into §10.

Radon is a real concern in parts of the country and essentially not one here; skip it unless
an inspector specifically raises it.

---

## 7. City point-of-sale rules — Peninsula-specific

Several San Mateo County cities require a **sewer lateral compliance certificate before title
can transfer**. This is a hard gate on closing, not a negotiation item, and it is the kind of
local rule an out-of-state first-time buyer has no way to know exists.

| City | Rule | In the packaged geography? |
|---|---|---|
| **San Mateo** | Point-of-sale test + compliance required | **Yes** |
| **Burlingame** | Point-of-sale test required for structures 25+ years old; repairs completed and city-approved **before transfer of title** | **Yes** |
| **Millbrae** | Point-of-sale test + compliance required | **Yes** |
| **San Bruno** | Point-of-sale test + compliance required | **Yes** |
| Hillsborough, Pacifica, South San Francisco | Point-of-sale test + compliance required | No |
| **San Carlos**, **Belmont**, Brisbane | Triggered by remodel or fixture addition — **not** automatically at sale | **Yes** |
| Santa Clara County target cities | No county-wide point-of-sale lateral ordinance; confirm per city | — |

Because a lateral replacement runs **$12k–$30k** (`13 §10`), whether this obligation lands on
the seller by ordinance or on you by silence is a five-figure question. Confirm the current
ordinance with the city directly — these change, and the cost-sharing programs attached to
them (San Mateo opened applications for one on 1 July 2026) change more often.

The spec keys these tasks off `properties.city`, so the tracker raises the sewer task on a
Burlingame home and does not on a San Carlos one.

---

## 8. Loan, appraisal, and the gap

### The loan

| Milestone | Timing | Note |
|---|---|---|
| Full application submitted | Day 0–1 | The 21-day clock does not care when you get around to it |
| **Loan Estimate (LE)** received | Within **3 business days** of application | Federally required. **Keep it** — you will compare the Closing Disclosure against it in §12 |
| Rate lock | Your call | Locks run 30–60 days; a lock that expires before COE costs real money to extend |
| Appraisal ordered | Week 1 | Lender orders it; you pay for it ($800–$1,500, and jumbo lenders sometimes require two) |
| Conditions cleared | Days 10–20 | Underwriting will ask for documents repeatedly. Answer within hours, not days. |
| **Clear to close** | Before loan contingency removal | Do not remove the loan contingency on a verbal "looks good" |

> **The standing rule until you have keys:** do not open a credit card, finance a car, change
> jobs, take a bonus structure change, move large sums between accounts, or make an
> undocumented deposit. Underwriting re-pulls credit and re-verifies employment shortly before
> funding. People lose loans in the last week doing ordinary things.

### The appraisal, and the gap

The appraisal is the lender's opinion of value, and the lender will lend against the **lower**
of price and appraised value. If you agree to $2.6M and the appraisal lands at $2.45M, the
$150k difference is cash out of your pocket on top of the down payment — that is the
**appraisal gap**, and in this market appraisals below contract price are ordinary because
the contract price was set by a bidding war and the comps were not.

The app already models this: `06 §6`'s back-solver treats the gap as a hard cash constraint,
and `buyer_profile.appraisal_gap_tolerance_pct` is the amount you pre-committed to cover.
When the appraisal arrives, the decision is one of four:

1. **Cover the gap in cash** — if you have it and still clear the 6-month reserves check
   (`06 §8`).
2. **Ask the seller to reduce** to appraised value — leverage depends entirely on whether
   backup offers exist.
3. **Split the difference** — the common outcome.
4. **Walk on the appraisal contingency** — only if you still have one.

A rebuttal ("reconsideration of value") to the appraiser through the lender is possible with
genuinely better comps, and occasionally works. Your CMA workbench output (`06 §2–4`) is
exactly the right artifact for that: bracketed comps, market-derived adjustments, a visible
grid. This is the one moment where the app's core feature does direct, immediate work for
you after acceptance.

---

## 9. Insurance — start on day one

**In California in 2026, this is a live risk of not closing at all**, and it is the task
first-time buyers schedule last.

The state of things: sustained wildfire losses drove carrier exits, non-renewals, and
withdrawal from whole regions. Over 2.8 million California homeowner policies were
non-renewed between 2020 and 2025. The **FAIR Plan** — the insurer of last resort, fire-only
and deliberately minimal — has absorbed the overflow, and its premiums rise an average of
**29.8% statewide from 15 October 2026**. A FAIR Plan policy is not a whole solution; it is
normally paired with a **DIC (Difference In Conditions)** companion policy to cover the
non-fire perils a normal homeowners policy would have handled.

Why this can stop a closing: **your lender will not fund without bound coverage.** If the
property is in a wildfire severity zone (CAL FIRE FHSZ — which reaches the Redwood City,
San Carlos, and Belmont hills in the target area, `01 §4`), placement can take weeks and may
require completed defensible-space or roof work first.

What to do:

1. **Get quotes in the first 48 hours.** Use an independent broker who writes across
   carriers, not a single-carrier agent.
2. Give them the address, year built, roof type and age, construction, and any FHSZ flag —
   the app has all of this already.
3. If no admitted carrier will write it, expect a **FAIR Plan + DIC** structure, budget
   accordingly, and set a reminder to re-shop at renewal once you can show upgrades.
4. **Bind the policy** and get the binder to your lender at least a week before COE.
5. **Earthquake is separate and always excluded** from a standard homeowners policy. CEA
   coverage on this housing stock is expensive with a high deductible (10–25% of dwelling
   limit). `buyer_profile.include_earthquake_ins` already carries this through the
   affordability math (`06 §8`); the decision is yours to make deliberately rather than by
   default.

| Coverage | First-year cost |
|---|---|
| Standard homeowners, non-FHSZ peninsula | $1,800 – $4,500 |
| FAIR Plan + DIC companion | $3,500 – $9,000 |
| Earthquake (CEA), separate | $800 – $3,500/yr |

---

## 10. Repairs and credits

Once the inspection reports are in and priced, you have exactly one negotiation left, and it
runs on the **Request for Repairs (Form RR)**.

**Ask for a credit, not a repair.** Nearly always:

- A seller who is leaving has no incentive to buy quality work, and you inherit whatever they
  hired.
- Repairs done in escrow are done fast and under duress.
- A credit lets you choose the contractor and control scope.
- A credit reduces your cash to close immediately.

The one exception is work that must be permitted and signed off before transfer — the
point-of-sale sewer certificate in §7 is the obvious case. Let the seller run that.

**Credits have a ceiling.** A closing-cost credit cannot exceed your actual closing costs,
and jumbo programs cap seller concessions (commonly 3–6% depending on LTV). Above the cap,
take the concession as a **price reduction** — which also lowers your loan, your transfer tax
basis, and your Prop 13 assessed value for as long as you own the house. Tell your lender
before you agree to any credit; a credit that breaks a program rule gets stripped at
underwriting.

**Be realistic about leverage.** In a house that drew multiple offers, a repair request is
sometimes the moment the seller remembers they had backups. What you actually hold is: the
cost of re-marketing, the disclosure obligation that now attaches to everything your
inspections found (they must disclose it to the next buyer), and the time already sunk. That
is real but it is not unlimited. Ask for the Section 1 pest total and the genuinely large
items; do not itemize $400 of caulking.

If the reports come back needing more time, **Form ETA (Extension of Time Addendum)** extends
a contingency by mutual agreement. Ask early — asking on the deadline reads as a stall.

---

## 11. Removing contingencies

Three separate decisions, each executed on a **Form CR**, each irreversible.

| Removing | You are giving up | Do not sign until |
|---|---|---|
| **Investigation** | The right to walk on anything about the property's physical condition, permits, or neighborhood | Every report is in, every "further evaluation" is chased down, and repair/credit negotiation has landed |
| **Appraisal** | The right to walk if value comes in low | The appraisal is in hand **in writing**, or you have decided in advance to cover the gap in cash |
| **Loan** | The right to walk if financing fails — **and this is the one that puts the deposit in play** | You have a written **clear to close** or something very near it. Not a verbal "we're fine." |

Once all contingencies are removed, your deposit is effectively at risk if you fail to close.
That is the deal you are making by signing — it is not a formality, and it is the seller's
entire reason for wanting these signed early.

**On the RPA's liquidated damages provision:** if initialed by both parties, it caps the
seller's recovery on a buyer default at **3% of the purchase price** — which on a $2.6M home
is $78,000, and is usually exactly your deposit. Know whether you initialed it.

---

## 12. The final week

### Closing Disclosure — COE minus 3 business days

Federal law (TRID) requires your lender to put the **Closing Disclosure (CD)** in your hands
at least **3 business days before consummation**. This is not a courtesy window; certain
changes restart it.

**Read it line by line against the Loan Estimate you saved in §8.** Nobody else will. Check:

- Loan amount, rate, term, and monthly payment match what you locked
- No prepayment penalty, no balloon
- Lender fees against the LE — some tolerances are zero, some allow 10%, some are unlimited
- The credit you negotiated in §10 actually appears
- Property taxes and insurance escrows are the real numbers, not placeholders
- **Cash to close** — and that it matches your own arithmetic

Discrepancies get raised the day you receive it, not at the signing table.

### Final verification of condition — the walkthrough

**Form VP**, typically within the last 5 days. It is not a re-inspection and not a new chance
to negotiate; it verifies three things:

1. **Repairs you paid for were actually done** — bring the receipts and the RR
2. **The house is in the condition it was in when you saw it** — check behind the furniture
   that has now moved out; that is where the floor damage and wall holes were
3. **Everything works** — run every faucet, flush every toilet, turn on the furnace and the
   AC, open the garage door, test every burner, check the water heater

Also confirm the seller's belongings and debris are gone, and that everything the contract
said conveys is still physically present — appliances, fixtures, remotes, keys.

If something is wrong, raise it **before** you sign. After recording, your leverage is a
lawsuit.

### Signing, funding, recording

Three separate events, and the distinction matters:

1. **Signing.** You sit with a notary — often mobile, at your kitchen table or office — and
   sign the loan documents and escrow instructions. Bring **government photo ID**. Allow 60–90
   minutes. You do not own the house.
2. **Funding.** Your cash to close must be **wired** and confirmed (cashier's check for a sum
   this size is impractical and often refused). The lender wires the loan proceeds. **Re-verify
   the wire instructions by voice** — §3, and this is the big one, so do it again properly.
3. **Recording.** The county recorder records the deed. **This is the moment you own the
   house.** Escrow confirms recording, then keys are released.

Recording usually lands the morning after signing. Do not schedule movers assuming keys at
noon on the signing day.

---

## 13. Cash to close, to the dollar

Four buckets:

```
cash to close  =  down payment
               +  closing costs (below)
               +  appraisal gap, if any (§8)
               +  prepaids and impounds
               −  any negotiated credit (§10)
```

**Prepaids and impounds** are the bucket first-timers forget: prepaid interest from funding to
month-end, the first year of homeowners insurance up front, plus 2–6 months of taxes and
insurance to start the escrow account. On a $2.5M home this is comfortably five figures on its
own.

`06 §8` estimates buyer-side closing costs as a flat **≈1.5% of price** (~$37.5k on $2.5M),
which the affordability engine and the offer back-solver both use. That flat figure is
consistent with the itemization below — use the itemization to sanity-check, not to replace.

| Line | Cost on $2–3M | Note |
|---|---|---|
| Escrow fee | $2,500 – $4,500 | Split custom varies by county — see below |
| Owner's title policy | $2,500 – $5,000 | Extended/ALTA homeowner's costs more and covers more |
| Lender's title policy | $500 – $1,200 | Simultaneous-issue rate |
| Recording | $150 – $400 | |
| Notary / mobile signing | $150 – $350 | |
| Appraisal | $800 – $1,500 | Jumbo may require two |
| Lender origination / points / underwriting | Varies widely | The LE is the source of truth |
| Prepaids + impounds | $10,000 – $25,000+ | Insurance, prepaid interest, tax reserve |
| Inspections (§6) | $1,500 – $4,000 | Paid as you go, not at closing |
| Attorney (§1) | $1,500 – $4,000 | |

### Who pays what

> **Verify this table against a current title-company sheet before relying on it.** Old
> Republic, First American, and Lawyers Title each publish a "Who Pays What / Closing Costs
> and Transfer Taxes" PDF for the Bay Area, updated regularly. Research for this document
> turned up **contradictory secondary claims** about Santa Clara escrow-fee custom and about
> which city transfer taxes apply — so this is a starting point and a set of questions for
> your escrow officer, not an authority. All of it is **custom only and fully negotiable**.

| | San Mateo County | Santa Clara County |
|---|---|---|
| Documentary transfer tax | County base **$1.10 per $1,000**, customarily seller-paid | County base **$1.10 per $1,000** |
| City transfer tax adder | **City of San Mateo: $5.00 per $1,000, split buyer/seller.** Other target cities: none. | San Jose, Palo Alto, Mountain View: **$3.30 per $1,000** |
| Escrow fee | Confirm with escrow — commonly buyer or split | Confirm with escrow |
| Owner's title policy | Commonly buyer | Confirm |

The city-of-San-Mateo split adder is the one line most likely to surprise you, because it is
the only target city with a meaningful buyer-side transfer tax obligation. On a $2.5M home it
is $12,500 total, half of which is yours.

---

## 14. Week one after close

| Task | Why it matters |
|---|---|
| **Change every exterior lock**, and the garage code | You have no idea how many keys exist |
| Transfer utilities into your name effective COE | PG&E, water, garbage, internet. Schedule before, not after. |
| **File the CA homeowners' exemption** with the county assessor | Knocks **$7,000** off assessed value. Small, permanent, and easy to forget. |
| **Expect the supplemental tax bill** | See below |
| Save the recorded deed, title policy, and full closing package | You will need these for years |
| Test/replace smoke and CO detectors | Compliance was the seller's obligation; the batteries are now yours |
| Register appliance and roof warranties in your name | Some are transferable only within a window |
| Note the seismic and drainage items you deferred | The tour flags and inspection findings you priced but didn't fix are now your maintenance backlog |

**The supplemental tax bill** deserves its own paragraph, because it is the most common
first-year financial surprise in California and `01 §4` already names it as a blind spot.
Property tax was being paid on the **seller's** assessed value — under Prop 13, possibly a
value set decades ago and a small fraction of what you just paid. On sale, the county
reassesses to your purchase price and sends a **supplemental bill for the difference,
back-dated to your closing date**. It arrives months later, it is **not** in your impound
account, and on a home that traded from a long-held low basis to $2.5M it can be **five
figures**. Set the money aside at closing.

---

## 15. How the app models this

The machine-readable form of everything above lives in the `ca` state pack,
`backend/hb/packs/ca/closing.py` (`CONTINGENCY`, `FORMS`, `PHASES`, `TASKS`, `COSTS`, composed
on the `us` base in `hb/packs/us/closing.py`), with the date engine in
`backend/hb/closing_spec.py`, and renders into the closing tracker (`/closing`, `08 §12`) as
dated tasks with the *why* attached. The doc is the reasoning; the spec is the clock. §1–§14
are also rendered in full on `/closing` itself as the collapsible closing playbook:
`GET /api/guide/closing` serves **this file**, split on its `## N.` headings server-side
(`hb/api/guide.py` `split_sections`) and rendered by
`frontend/src/components/MarkdownGuide.tsx`, so this document is a runtime asset — an edit
above is live on the next request, and this section is hidden from the page.

| Concept here | Where it lives |
|---|---|
| The task list, phases, owners, `why`/`how` text | `backend/hb/packs/ca/closing.py` — `PHASES`, `TASKS` (field-level overrides + extras on `hb/packs/us/closing.py`); date math in `backend/hb/closing_spec.py` |
| Cost bands in §6 and §13 | the pack's `COSTS` (`hb/packs/ca/closing.py`), re-labelled per geography (`[costs]`), same dedupe-on-rollup rule as the tour `COST_BANDS` (`13 §10`) |
| Your five numbers from §3 | `deals` table (`04`) — `accepted_on` is the anchor for every computed date |
| The three clocks in §4 | `deals.investigation_days` / `appraisal_days` / `loan_days`; **NULL means waived**, which prunes the anchor and every task hanging off it |
| Per-task state | `deals.checklist` JSON, keyed by spec key — adding a task is a spec edit, never a migration |
| §7 city rules, age-triggered inspections | `applies_when`, pruned against `year_built` and the city's flags in `geography.toml` (`city_flag: sewer_lateral_pos` — flag a city there to turn the §7 task on) |
| Deadline countdowns and the UI | `/closing` (`08 §12`) |
| §1–§14 prose, tables and worked timeline | this file, served by `GET /api/guide/closing` (`hb/api/guide.py`) and rendered by `frontend/src/components/MarkdownGuide.tsx`; `GUIDE.phase_map` in `hb/packs/ca/__init__.py` maps each spec phase to the chapters behind it |
| Deadline alerts | `deal_deadline_soon` / `deal_deadline_overdue` (`09`), emitted by the `deal-deadlines` job (`05`) |

Roll-ups are **recomputed on read**, never stored — same contract as tours (`04`), so
correcting a date or a cost band in the spec immediately reprices an open deal.

**Two things the app deliberately does not do.** It does not store your documents — tasks
carry a received/reviewed date and a note, not a file, because introducing binary upload for
this is out of proportion to the need. And it does not compute legal deadlines for you as
authority: the dates on `/closing` are arithmetic on the numbers you entered from your own
contract, and your contract governs.

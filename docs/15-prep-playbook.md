# 15 — Prep Playbook: what to do before you tour a single house

The front half of the process. `01-domain-primer.md` teaches the market, `13-tour-playbook.md`
covers walking a house, `06-algorithms.md` covers the bid, and `14-closing-playbook.md` covers
escrow. This one covers the weeks **before any of that** — where a buyer with no agent either
builds a working setup or discovers, mid-bidding-war, that they haven't got one.

The machine-readable form lives in the state pack, `backend/hb/packs/ca/prep.py` (`PHASES`,
`TASKS`, composed on `hb/packs/us/prep.py`), with the engine in `backend/hb/prep_spec.py`, and
renders into the Get Ready page (`/prep`, `08 §13`).

> Written for the **`ca` pack**: the 17-day investigation default, Prop 13 and the
> supplemental bill, FAIR Plan insurance and Bay Area offer-date conventions are California's.
> The `us` base pack keeps every task with state-neutral wording (`docs/packs/README.md`).

> Same caveat as `docs/14`: not legal or financial advice, and figures are dated
> **August 2026**.

## Why this list is ordered the way it is

**Two things gate everything: calendar time and money.** Most of this list is an evening's
work. A handful of items take weeks *regardless of how motivated you are*, and those are the
only ones whose ordering actually matters:

| Item | Real lead time | Consequence of starting late |
|---|---|---|
| Credit dispute | **30–60 days**, set by law | A wrong collection you find in month one is invisible; found in month six it blocks the purchase |
| Gift-fund seasoning | **60 days** in your account | Money arriving the week of closing triggers underwriting questions at the worst moment |
| Underwritten pre-approval | **1–3 weeks** | The strongest form of pre-approval, and the one that wins multiple-offer situations |
| Shopping three lenders | **1–2 weeks** | Rushed, you take the first quote and pay for it for thirty years |
| Insurance broker relationship | Weeks, in the 2026 CA market | See `14 §9` — this can stop a closing outright |

The app surfaces exactly this: unfinished tasks carrying a `lead_time` are pulled into a
**"Start these first"** panel and tinted amber in the list. Everything else is untinted and can
be done in any order.

**`needed_by` splits the list in two** — what must be true before you walk a house, and what
must be true before you write an offer. On the Peninsula those are days apart, not months:
disclosure packets are published *before* the offer date (`01 §1`), so "before you offer" means
"about a week after you start touring", not "later".

---

## 1. Credit and the paper trail

Start on day one; this phase is pure calendar time.

- **Pull all three reports** at `annualcreditreport.com` — the government-mandated free site,
  not the ones advertising free scores. Roughly a quarter of reports contain an error, and on a
  jumbo loan your middle score drives both your rate and your approval.
- **Dispute anything wrong immediately.** The bureaus have 30–60 days by law.
- **Freeze your financial life now, not at escrow.** No new credit, no job change, no
  unexplained transfers. Underwriters look back two months on assets and two years on
  employment. `14 §8` repeats this rule for the closing period; it should start far earlier.
- **Assemble the document pack once**: two years of W-2s and full tax returns, 30 days of pay
  stubs, 60 days of statements for every account you'll draw on, photo ID.
- **Equity compensation needs its own conversation.** RSU and bonus income is underwritten very
  differently by different lenders — two-year averaging, continuance letters, or heavy
  discounting. For a buyer whose income leans on equity compensation this moves the approved
  number by hundreds of thousands, and it is worth choosing a lender on this alone.
- **Gift funds need 60 days of seasoning** plus a signed gift letter proving it isn't a loan.

## 2. Know your real number

Not what a bank will lend — what you can pay and still sleep.

- **Count actual available cash**, then subtract what you won't really spend: emergency fund,
  tax owed on stock you'd sell. That figure goes in the buyer profile and becomes a hard
  constraint in the bid back-solver (`06 §6`).
- **Set a reserves floor.** Six months of full payment is what the app enforces (`06 §8`) — and
  jumbo lenders frequently *require* six to twelve months to approve you at all, so this is
  qualification as well as prudence.
- **The mortgage is about two-thirds of the true monthly cost.** California property tax runs
  ~1.1–1.3% of the **purchase price** annually and resets when you buy — the seller's old
  Prop 13 bill is not yours. Add insurance (expensive and worsening, `14 §9`) and any HOA.
- **Budget the first-year surprises**: the supplemental tax bill (`14 §14`), immediate repairs
  from the inspection, furniture.
- **Decide the down payment target.** 20% avoids mortgage insurance and is what most jumbo
  pricing assumes.

## 3. A pre-approval that means something

- **Three things get called "pre-approval".** Pre-*qualification* is a conversation and worth
  nothing. Standard pre-*approval* is a credit pull plus stated income. An **underwritten**
  pre-approval means a human underwriter reviewed your actual documents. In a multiple-offer
  situation the third wins and the first is ignored. Ask which one you're being given, in those
  words.
- **Shop at least three, including a broker.** A bank sells only its own product; an
  independent mortgage broker shops multiple wholesale lenders. Get a written **Loan Estimate**
  from each on the same day for the same scenario — that form is standardised precisely so it
  can be compared line by line. Save them: you'll compare the Closing Disclosure against yours
  in `14 §12`.
- **Do all rate shopping inside a two-week window.** Multiple mortgage inquiries in a short
  window count as one for scoring; spread over months they count separately.
- **Learn the jumbo rules.** Above the conforming limit the rules are the lender's own, not
  Fannie Mae's: bigger reserve requirements, tighter debt-to-income, sometimes two appraisals,
  and much more variation between lenders. Ask each for: reserve months, maximum DTI, whether
  two appraisals are required at your price, and **maximum seller credit allowed** — that last
  number decides how you can take a repair concession later (`14 §10`).
- **Get the letter, note its expiry** (usually 60–90 days), and ask whether they'll re-issue at
  a specific figure so you aren't showing every seller your true ceiling.
- **Ask the appraisal-gap questions before you need them**: what happens on a low appraisal,
  will they accept a reconsideration of value with comps, how fast can they order it. Then set
  your gap tolerance in the profile so the back-solver treats it as real cash (`06 §6`).

## 4. Build your team

Every one of these is somebody a buyer's agent would normally have on speed-dial. Line them up
before you need them, not during a 17-day investigation window.

| Who | Why now | Cost |
|---|---|---|
| **General home inspector** | Good Peninsula inspectors run 5–10 days out; the default investigation contingency is 17 days and often shorter | $600–$1,200 |
| **Sewer lateral scope** | A failed clay lateral is $12k–$30k and no visual inspection finds it | $300–$700 |
| **Structural engineer** | Pre-1980 stock frequently needs an opinion | $600–$2,500 |
| **Independent insurance broker** | The 2026 CA market can stop a closing outright (`14 §9`) — one who writes across carriers, not a single-carrier agent | — |

Two things worth knowing before you meet any of them:

- **Get a practice insurance quote on a real listing.** "Insurance is expensive" is useless; a
  real annual figure for a real house in your target ZIP tells you your monthly number and
  whether the homes you like are insurable at all. Feed it into the buyer profile.
- **Escrow and title are neutral by law.** They will explain process precisely and refuse to
  advise you entirely (`14 §1`). Buyers routinely mistake this for having help. Every "should I"
  goes to the attorney; every "how does this work" goes to escrow.

## 5. Learn the market before you bid in it

This is what the rest of the app is for — see `01-domain-primer.md` for the reasoning.

- **Set target cities, ZIPs and price band** in config. Everything — alerts, comps,
  dashboards — is scoped to them.
- **Watch weekly for at least a month before bidding.** Dashboard tiles, the Supply page, the
  Recently Sold feed. You cannot judge whether a given price is good until you've watched thirty
  similar homes sell.
- **Learn the overbid pattern for your ZIPs specifically.** List prices here are routinely set
  10–40% below expected sale price to manufacture competition. Read a list price as a ceiling
  and you'll never buy; read it as meaningless and you'll overpay. The sale-to-list distribution
  (`06 §5`) is the number that matters.
- **Learn the offer-date convention**: typically 7–14 days after listing, with the disclosure
  packet provided up front. Watch a few listings through a full cycle without bidding.
- **Read `13-tour-playbook.md`** before the first open house.
- **Read one full disclosure packet with nothing at stake.** Ask a listing agent for the package
  on a house you won't bid on — they usually send it. Read it against `14 §5`. It is the
  cheapest possible practice for a document you'll later have days to review under pressure.

## 6. Decide your rules while you are calm

Every rule here is one you'll be tempted to break inside a bidding war.

- **Write down your maximum price.** Everyone believes they have one; people who haven't
  written it down don't. Use the offer helper's ceiling (`06 §6`) and record it as `my_max_bid`
  on tracked homes so it's visible at the moment of decision.
- **Decide your contingency policy in advance** for each of investigation, appraisal and loan.
  You will be told waiving is the price of winning, and sometimes that's true — but waiving the
  loan contingency puts ~3% of the price ($60k–$90k) at risk if financing fails, and that is not
  a decision for the twenty minutes before an offer deadline. A defensible middle path is
  *shortening* rather than waiving, plus a defined cash gap. Discuss it with your attorney
  before the first offer.
- **Set the appraisal gap you can actually cover.** 5–10% coverage is common here. Promising
  more than you have is how a deal collapses at your expense.
- **Write down deal-breakers** — specific and physical: the Caltrain horn corridor, flight
  paths, school-district boundaries, commute ceiling, unpermitted additions, unbolted
  foundations, a lot below street level. The tour checklist raises most of these automatically.
- **Decide your position on buyer-side compensation.** Since the 2024 NAR settlement it is
  negotiated directly and nothing is published on the MLS. With no buyer's agent there is no
  buyer-side commission to pay; that amount isn't automatically yours, but it is a live term —
  and only negotiable **before** acceptance (`14 §2`).

## 7. Ready to walk houses

- **Pick the day's homes in Field mode** (`/field`, `08 §11`), after reading
  each home's detail page (`13 §1`). The picker lists your Tracker and open-house schedule;
  search for anything else. At the house, Field walks each home's age-pruned checklist on
  your phone and saves as you tap.
- **Pack the kit**: a flashlight brighter than your phone's, tape measure, level app, compass
  app, and optionally a $10 outlet tester.
- **Get on the listing agents' lists.** Coming-soon and pre-market listings circulate among
  agents first. Being unrepresented changes nothing about whether they'll add you. Each
  listing's Contact card (`08 §3 1c`) has the agent's direct line and a prefilled
  unrepresented-buyer note (`14 §2.3`) — the ask costs nothing and never runs through a portal
  form.
- **Practise the one sentence that matters**: *"Could you send me the disclosure package for
  this one?"* Ask on every house you're seriously considering.

---

## 8. How the app models this

| Concept | Where it lives |
|---|---|
| Phases, tasks, `why`/`how` | `backend/hb/packs/ca/prep.py` (engine: `backend/hb/prep_spec.py`) |
| Lead-time ordering | `PrepTask.lead_time` (`hb/packs/types.py`) → the "Start these first" panel |
| Tour vs offer split | `PrepTask.needed_by` |
| Saved state | `settings` row `prep_checklist` (`04`) — one global checklist, because you get pre-approved once, not once per house. No new table. |
| API | `GET /api/prep`, `PATCH /api/prep` (`07 §Prep`) |
| UI | `/prep` (`08 §13`) |

Roll-ups are **recomputed on read**, never stored — the same contract as tours and deals — so
editing the spec immediately re-scores an existing checklist.

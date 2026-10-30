# 13 — Tour Playbook: what to do when you walk a house

> Written for the **`ca` pack** (California; cost bands labelled for the SF Peninsula by the
> packaged geography). The checklist engine and most items are the same in every state; the
> `us` base pack drops the seismic items and the California hints (`docs/packs/README.md`).

Companion to `01-domain-primer.md`. That document is about *price*; this one is about
*condition* — the half of the decision the app could not see until you stood in the
building. The machine-readable form of everything below lives in the state pack,
`backend/hb/packs/ca/tour.py` (`SECTIONS`, `COST_BANDS`, `AGENT_QUESTIONS`, `AGE_NOTES`,
composed on `hb/packs/us/tour.py`), with the engine in `backend/hb/tour_spec.py`
(pruning, `flag_when`, the cost roll-up), and renders into three surfaces:
the tour panel on the listing detail page (`08 §3` item 6c), the Field page
(`/field`, `08 §11`), and the AI deep-dive brief (`hb/brief.py`).

**The buyer is a first-timer.** The design assumption throughout is that you do not yet
know which findings are ordinary and which are expensive. That is why observations carry
`flag_when` rules and cost bands rather than sitting in a free-text box: "Federal Pacific"
has to mean something without you already knowing why.

---

## 1. Before you leave the house

Open the listing detail page and read, in this order:

1. **Posture badge and the signal list** — is the ask bait, market, or aspirational?
2. **Cumulative DOM and price cuts** — a listing showing 9 days that is really on day 87
   is the leverage gift described in `01 §3`.
3. **Predicted sale range** vs the CMA estimate vs the AVM spread. Wide spread = genuine
   uncertainty, and that is exactly when a careful walk-through pays.
4. **Year built.** This determines *what you inspect*. The checklist prunes itself on it:
   pre-1980 adds foundation bolting and wiring vintage, pre-1975 adds the sewer lateral,
   pre-1970 adds galvanized supply.
5. **The sqft-mismatch banner** — listed sqft >15% above assessor is an unpermitted-addition
   flag (`05 §8`), and it becomes a question for the agent.
6. **Hazard chips** — flood, wildfire, liquefaction, fault. These change insurance cost,
   not just safety.

Then open **Field** mode (`08 §11`) — it lists your Tracker and your open-house schedule,
with a search for anything else — and pick every home you plan to see that day, so the
walk is one tap per home (§11).

**Bring**: a phone with a level app and a compass app, a flashlight brighter than the
phone's, a tape measure, and a charged battery. A cheap outlet tester is optional and
tells you about grounding in about four seconds.

---

## 2. Street and approach — 5 minutes, before you go in

Park down the block and walk it in both directions. Everything here is invisible in
listing photos and permanent once you own it.

- **Noise.** Three sources matter specifically on the Peninsula: the **Caltrain horn
  corridor** (grade crossings sound the horn day and night), the **SFO and SJC approach
  paths**, and **101/280 hum**, which carries much further than people expect and is worst
  at night when traffic thins and speeds rise.
- **Street parking density**, permit zones, and whether the neighbours' cars have spilled
  onto the street because their garages are full — or converted.
- **Adjacent and backing uses**: commercial, gas station, transformer or transmission
  lines, cell tower, a school (traffic twice a day), an apartment building whose balconies
  look into the yard.
- **Topography.** A lot sitting **below street level** drains toward the house. Bay Area
  clay soil does not absorb it.
- **Orientation.** Compass app. A south- or west-facing yard is usable after work; a
  north-facing one is not.
- **Neighbours' upkeep.** You are buying into the block, and two teardowns either side is
  both a risk and an opportunity.
- **Cell signal inside the house** — check it while you are there, not after you move in.

---

## 3. Exterior envelope — 10 minutes

Walk the full perimeter. Do not skip the side yards; that is where the drainage problems
and the panel usually are.

**Roof.** From the street and from the back yard. Note material, and estimate age — comp
shingle lasts roughly 20–25 years here. Look at the **cut edge along the rake**: more than
one layer means a tear-off, which is a meaningful chunk of the replacement cost. Curling
shingles, granule loss in the gutters, patched valleys, and moss on the north slope are all
end-of-life signals. *Photo: the full roofline from two angles.*

**Water, and where it goes.** This is the single highest-yield ten minutes of the tour,
because Bay Area clay soil means **drainage is the root cause behind most foundation
findings**. Are there gutters at all? Do the downspouts discharge away from the house or
straight into the soil beside the foundation? Does the ground slope away? Is there
efflorescence — white mineral bloom — on the concrete? *Photo: where each downspout lands.*

**Foundation.** Walk the perimeter and read the cracks:

| What you see | What it usually means |
|---|---|
| Hairline vertical cracks | Normal concrete shrinkage |
| Diagonal cracks from window/door corners | Settlement — worth an inspector's opinion |
| **Horizontal or stair-step cracks wider than ¼"** | Structural; get it priced before offering |
| **Freshly patched or painted-over cracks** | Someone knew. Ask what was done and when |

*Photo: any crack with a coin or your hand in frame for scale.*

**Seismic retrofit (pre-1980 raised foundations).** Look through a crawlspace vent with
your flash on. **Anchor bolts** along the mudsill and **plywood shear panels** on the
cripple wall mean it has been done. Nothing visible means assume it has not. This affects
earthquake insurance as well as safety, and it is one of the cheaper big-ticket fixes.

**Everything else on the envelope**: stucco cracking at corners, rot at the bottom of trim
and door frames (water always finds the bottom), window type — single-pane aluminum is
original and will be replaced eventually — and fogging between panes, which is a failed
seal on that unit. Note large trees within about fifteen feet: roots find sewer laterals,
and **heritage-tree ordinances may prevent you removing them**. Leaning or cracked
retaining walls are quietly one of the most expensive items on this page. Finally, look for
**ADU potential** — a detached garage or usable yard space is a real Bay Area value lever.

---

## 4. Systems — 15 minutes, and do them BEFORE the kitchen

The ordering is deliberate. Once you like a room you stop looking at pipes.

**Electrical panel.** Open the door.

- **Amperage.** 100A constrains EV charging plus a heat pump plus induction — you will not
  get all three without a service upgrade.
- **Brand.** **Federal Pacific, Zinsco, and Challenger are known fire hazards.** They get
  replaced, not repaired, and insurers ask about them.
- Fuses instead of breakers means the panel predates the question.
- *Photo: panel with the door open, breakers and the main label legible.*

**Wiring** (pre-1980). Look in the garage and crawlspace. Cloth-wrapped, knob-and-tube, or
aluminum branch wiring all affect insurability, not just safety. Two-prong outlets
throughout means no ground.

**Water heater.** Age off the data plate — most tanks last 10–15 years. California requires
it to be **double-strapped**; one strap or none is both a code issue and a tell about how
the rest of the house has been maintained. *Photo: the data plate.*

**Heating.** Forced air, heat pump, wall furnace, or floor furnace. **Wall and floor
furnaces mean there is no ductwork at all**, so adding air conditioning later is a much
bigger job than swapping a unit. *Photo: the data plate.*

**Plumbing — look under every sink.**

- **Galvanized steel supply** is dull grey and threaded. It corrodes shut from the inside;
  symptoms are low pressure and rusty first-draw water. This is a repipe, not a repair.
- Cast-iron drains crack with age.
- **The pressure test**: run a bathroom faucet at full, then flush the toilet. A hard drop
  means a supply-side problem.
- Staining, rust rings, or an active drip under any sink is worth photographing.

**Sewer lateral.** Many Peninsula cities require a **compliance certificate at sale**. A
clay lateral plus mature trees is a five-figure line item. Ask whether a video inspection
exists — if the seller has one, they already know.

**Crawlspace.** Head and flashlight in, even briefly. Standing water, a mould smell,
sagging joists, posts sitting on bare dirt with no footing, rodent activity in the
insulation. *Photo: joists, posts, and the ground surface.*

**Attic.** If the hatch is accessible: insulation depth, **daylight visible through the
roof deck**, water stains on the sheathing, and whether the bath fans actually vent outside
rather than into the attic.

---

## 5. Interior, room by room — 20 minutes

**Technique first**, applied everywhere:

- Phone level in every room. More than about half an inch over ten feet is worth asking
  about.
- **Open and close every window and every door.** Sticking is how structural movement shows
  up indoors, and it is free to check.
- Run every faucet, flush every toilet, switch on every fan and light.
- Look *up* in every room. Water stains and fresh patch paint on a ceiling both mean the
  same thing; one has been painted.
- Trust your nose. Musty means moisture. Heavy fragrance or candles means something is
  being covered — and a single freshly painted patch on an otherwise tired wall is the
  most honest thing in the house.

Then the specifics: kitchen condition and appliance age, whether the range hood vents
outside or recirculates; bathroom grout and caulk, and a **soft or spongy floor near any
toilet**, which is subfloor rot and is cheap to find now; bedroom closets, egress, and
street noise from the actual bedroom; the fireplace (many older ones are decorative-only or
red-tagged); laundry location; the garage — **converted garages are endemic, so ask whether
it was permitted and whether it is counted in the listed square footage**, which ties
straight back to the assessor mismatch flag; flooring, including whether there is original
hardwood under the carpet; and storage, because Peninsula homes are small and everything
has to go somewhere.

---

## 6. Fit for your actual life

No inspector checks these and no listing mentions them: where the desk goes, whether fibre
is available at the address, the commute driven or ridden at the hour you would really do
it, the measurements of the main wall and the fridge nook, and where the cars, bins and
bikes live.

---

## 7. Questions for the listing agent

The full list is `AGENT_QUESTIONS` in the pack (`hb/packs/ca/tour.py`). Two are worth calling out.

**"How many disclosure packets have gone out?"** is the single best competition proxy
available to a buyer before the offer date. Agents will often answer it when they would
deflect "how many offers do you have?", because packets out is a number they are proud of —
and it is a leading indicator, where offers-in-hand is a lagging one.

**"Is the square footage from the assessor or was it measured?"** cross-checks the app's
own `sqft_mismatch` flag and opens the permit conversation without being adversarial.

The rest: why they are moving and their timeline; rent-back; whether the offer date has
moved; what disclosures exist right now; what work was done and whether it was permitted;
what is excluded from the sale; anything they have chosen to disclose; what terms besides
price matter to the seller; and whether they would look at a pre-emptive offer.

---

## 8. In the car, before you leave the block

Memory degrades within the hour, and by the third house of the day they blur. Do this at
the kerb:

1. A 60-second **voice memo** walking the house in your head, start to finish.
2. **Gut score 1–5** and a verdict: offer / maybe / pass.
3. Top three things you loved, top three that worry you.
4. Rough immediate-work dollars, even if it is a guess.

Field mode's Agent & verdict screen carries the gut score, the verdict and the two top-three
fields (`loves` / `worries`, the pack's `verdict` section in `hb/packs/us/tour.py`); the voice
memo goes into its notes field as a transcript (there is no recorder), and the immediate-work
dollars are the deferred-maintenance roll-up in the screen's footer rather than a field of
their own (`pages/Field.tsx`). The tour panel's verdict section renders the same spec section.
Fill them before you start the engine.

---

## 9. Back home — the AI deep-dive handoff

Once field mode has synced (you are back on the LAN), open the listing and hit **Copy
deep-dive brief**. The brief (`hb/brief.py`) assembles the subject (including the listing
side's contact, stated as representing the seller), market position, valuation
and comps, schools and hazards, the money, your observations, the priced deferred
maintenance, and — the section that matters most — **what you could not verify**.

That last section exists because the failure mode of handing a house to an AI is that
silence reads as a clean bill of health. Listing the gaps explicitly lets the reader rank
which unknowns actually move the number.

**Attach alongside the brief:**

- The **disclosure packet** PDF — the single highest-value document in the process.
  Specifically the **pest report Section 1 total** (active damage) and **Section 2**
  (preventive), the TDS and SPQ, the NHD, any seller-side inspection or roof certification,
  the sewer lateral video and certificate, the permit history, the preliminary title report
  (easements, CC&Rs), and HOA docs if any.
- **Your photos** — the shot-list in `spec.photo_shot_list`: panel with the door open,
  water heater and furnace data plates, crawlspace, roofline, drainage, under-sink
  plumbing, and any crack.

**Then ask for**: the defects priced at current Peninsula rates; deal-breakers separated
from negotiables; the disclosure packet read against what you observed and what the
disagreements imply the seller knows; value restated net of deferred maintenance; offer
terms given the posture and competition signals; and the five questions still worth
answering before the offer date, ranked by how much they move the price.

The brief ends with exactly this request, so it is one paste.

---

## 10. Bay Area repair cost bands

These back the pack's `COST_BANDS` (`hb/packs/ca/tour.py`; a geography re-labels them and can override individual bands via `[costs]` in `geography.toml`) and roll up into the condition-adjusted
value shown under the CMA estimate. They are **2026 SF-Peninsula contractor ranges for a
typical 1,500–2,000 sqft single-family home** — deliberately wide, because the point is to
know whether a finding is a $3k annoyance or a $30k renegotiation, not to produce a
quote.

| Band | Range | Triggered by |
|---|---|---|
| Water heater replacement | $2k – $4.5k | Data-plate year 12+ years old |
| Service upgrade to 200A | $3.5k – $7k | 100A or 125A service |
| Electrical panel replacement | $4k – $8k | Federal Pacific / Zinsco / Challenger, or fuses |
| Foundation bolting + cripple wall | $5k – $15k | Pre-1980, no retrofit hardware visible |
| Drainage / regrading / French drain | $8k – $20k | Ground slopes toward house, or downspouts at the foundation |
| Forced-air furnace / ducting | $8k – $15k | Wall/floor furnace, none, or 20+ years old |
| Whole-house repipe | $10k – $20k | Galvanized steel supply |
| Sewer lateral replacement | $12k – $30k | Pre-1975 with no compliance certificate |
| Partial/whole rewire | $15k – $40k | Knob-and-tube or aluminum branch wiring |
| Retaining wall rebuild | $15k – $60k | Leaning or cracked |
| Whole-house window replacement | $20k – $45k | Single-pane aluminum |
| Composition roof replacement | $25k – $45k | Estimated age 20+ years |
| Bathroom remodel | $25k – $50k | Reference only — never auto-attached |
| Kitchen remodel | $60k – $150k | Reference only — never auto-attached |

**Two rules the roll-up follows.** Bands are **deduped by trade**: a house with both a
Federal Pacific panel *and* fuses pays for one panel, not two. And kitchen and bathroom
condition are **never** auto-priced, because "dated kitchen" is a preference, not a defect —
they are captured as 1–5 ratings and left for you to value.

Real quotes override the bands: the tour panel takes a low/high pair that replaces the
computed total everywhere it is shown.

---

## 11. Field capture — the walk, one home at a time

**Field** (`/field`, `08 §11`) is this checklist laid out to be held in one hand while you
walk. It is an ordinary page of the app, opened in any browser that reaches it — on the
home network, or anywhere over Tailscale with the home-server setup
(`docs/16` §5); nothing is installed.

Pick the day's homes once — the picker lists your Tracker and your open-house schedule, and
search finds anything else. Each home is then four grouped screens following the walk above:
**Outside** (Street + Exterior, §2–3), **Systems** (§4), **Inside** (Interior + Life, §5–6),
**Agent & verdict** (§7–8). Each screen stacks its sections under sub-headings, so related
items are one scroll, not a tap. Inputs are thumb-first: one-tap pills for short choices, the
iOS wheel for long ones, full-width toggles, five large squares for ratings. The same
`flag_when` red flags the tour panel raises appear as you answer, and the footer keeps a
running deferred-maintenance range (§10), deduped by trade.

Every tap is kept locally first and saved a moment later, per home as `POST /api/tours`
(idempotent per day) then a `PATCH` of the accumulated state. What you just observed is
authoritative, so the PATCH **overwrites** — unlike `POST /api/tours/import`, which
gap-fills and would refuse a correction. If the connection drops mid-walk, the answers wait
and save when it returns. A **Copy answers** button emits the raw JSON, which is exactly
what `/import` consumes if the normal save ever cannot run; **Clear** on the picker's
in-progress card saves first, then empties the set; and a print sheet renders the whole
checklist to paper for when the battery dies.

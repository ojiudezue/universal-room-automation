# AUDIT — Card merit review (2026-08-20, post-interrogation)

**Read-only review of all 135 board cards.** Trigger: operator, after a session in which three of my
own asserted mechanisms were refuted — *"review all cards and make sure they have merit rooted in
goals and correctness and enum those that are marginal."*

Merit test applied to each card: (1) is it rooted in a stated goal or a real correctness defect?
(2) is its **premise** verified, or inherited from an unproven reading? (3) has today's evidence
superseded it?

**Headline: 96 of 135 are terminal (shipped/done). Of the ~39 live cards, 8 are strong, 9 are
marginal, and 7 form a cluster whose shared input turns out to be broken.**

---

## 1. The finding that reorders the board

**The census/identity consumer cluster is built on a partly-dead input.**

Seven cards exist to wire downstream consumers onto egress `person_id`:
`PERIMETER-ALERT-NAME-PERSON-1`, `GUEST-GATE-DOOR-IDENTITY-1`, `ARRIVAL-DEPARTURE-NOTIFY-1`,
`CENSUS-FACE-RESOLVER-MIGRATE-1`, `GUEST-COUNT-DEDUP-MIGRATE-1`, `SECURITY-CENSUS-UNKNOWN-WIRE-1`,
`UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`. `EGRESS-INTERIOR-COUNT-REINFORCE-1` (status `planned`)
sits on the same input.

Today's discovery (`EGRESS-CAMERA-DEAD-CONFIG-1`): **2 of the 5 configured egress cameras are dead
Frigate-1 names** — Garage A and Garage B resolve to nothing. Memory records that garage + family
room is this house's *primary* entry route.

So every one of those eight cards is a consumer of a producer that is missing its two most important
cameras. Per the standing rule *"always measure the real production rate of the new value first — a
sparse producer caps every consumer's value"*, *none of these should be scoped until the egress
config is fixed and the coverage re-measured.* They are not wrong; they are **premature**, and their
value estimates are all understated by an unknown amount. This also means the ~7% egress coverage
figure may have been partly a config bug, not a face-recognition reach limit.

**Action: gate all eight behind `EGRESS-CAMERA-DEAD-CONFIG-1` + a re-measure. Do not close, do not
scope.**

---

## 2. Marginal cards — enumerated

Marginal = keep-but-demote, or needs its premise checked before it earns work. **None of these is
proposed for deletion** (dead ≠ delete).

| Card | Why marginal | What would settle it |
|---|---|---|
| `CHATTER-CAMERA-CONFIDENCE-FLAP-1` | Sibling detector of the STEP chatter mechanism — which today's hand check shows detects **zero** across every room, including sensors a different detector flags 3,043×. Building a second sibling of a detector that found nothing is premature. | Recalibrate or retire the parent first. |
| `SENSOR-MULTISTATE-FAULT-1` | Same — second STEP sibling, same reasoning. | As above. |
| `HVAC-PRESET-RESTORE-MISS-1` | Substantially the same defect as `HVAC-MANUAL-PRESET-CONTRACT-1` (zone 1 stuck in a manual hold through home_day). Two cards, one bug. | Merge into the contract card as its founding case. |
| `ARRESTER-CLOUDFLAP-FALSEPOS-1` | Premise weakened today: a full error-log scan (12,652 entries, 32 components) contains **no Carrier/Bryant component at all**. The cloud-flap story rests on one 62-second unavailability window. | Find a second instance, or downgrade to "watch". |
| `HVAC-GUEST-AS-ZONE-PERSON-1` | Operator states the zone sleep latch already depends on actual occupancy. If so, 1 of the 3 "lost protections" the card is built on isn't lost — the framing came from my reading, not a test. | Verify the sleep-veto path reads occupancy vs person membership. |
| `CONFIG-SUBENTRIES-MIGRATION-1` | Large platform migration with no forcing function, and URA is explicitly single-install with no back-compat obligation — which removes much of the usual motivation. | Name the concrete pain it removes, or park. |
| `ENTITYDESC-RUNTIMEDATA-HYGIENE-1` | Self-described "opportunistic" hygiene. No goal root, no defect. | Fold into whatever cycle next touches those files; never its own cycle. |
| `UNLOAD-SYMMETRY-TASK-HYGIENE-1` | Tech-debt hardening with no observed failure attached. | Attach a real incident or keep parked. |
| `PATHBETA-VESTIGIAL-1` | Dead-code cleanup. House rule is explicit that dead ≠ delete, and a reviewer already warned against bundling it. | Run the three-bucket triage; expect KEEP+DOCUMENT. |
| `TABLET-FLEET-1` | New capability, unscoped, no stated goal link. | Needs a value case before planning. |
| `IOS-APP-PLAN-CARD-1` | Explicitly "gated design blueprint (tracked)" — a placeholder, not work. | Fine as a placeholder; should not appear in any near-term ranking. |
| `SWEEP` | Process card, `waiting_me`, untouched since 08-17. Board hygiene, not work. | Close or re-scope. |
| `ROADMAP-STALE-AGENTIC-LAYER-1` | Real (roadmap says v4.0.0 next; we are at v5.85.0) but zero urgency and no consumer. | Batch with the other roadmap/memory meta cards into one docs pass. |

## 3. Board-hygiene defect (not a card)

**33 cards carry `status: null`** — no status at all. They are invisible to any status-based
ranking and cannot be triaged. Most are census/identity follow-ups from 08-18. This is the single
biggest thing degrading the board's usefulness: a third of it is unsorted. Recommend a one-pass
status assignment before the next planning cycle, not a per-card investigation.

## 4. Cards whose merit is confirmed strong

`HVAC-MANUAL-PRESET-CONTRACT-1` (9–14h/day lockout, measured) · `EVSE-DRAIN-PRECEDENCE-KNOB-80-1`
(mis-sourcing confirmed in live snapshot data) · `EGRESS-CAMERA-DEAD-CONFIG-1` (new; 2/5 egress
cameras dead) · `HVAC-ANOMALY-BLIND-1` (3 of 5 metrics never sampled; root cause already in backlog)
· `D2-CANARY-GUEST-PREDICATE-1` (2,525 hits in 5h, confirmed today) · `RECORDER-BLOAT-LOGFLOOD-1`
(31 GB/7 days on flash at 51% life; two new flood sources found today) · `ZIRI-COLLEGE-PERSISTENT-AWAY-1`
(real life change with presence/census consequences) · `TEST-STRATEGY-REARCH-1` (hollow-anchor and
order-pollution failures are both evidenced).

`TEST-1` (boot-time shadow diff of legacy vs resolver leg sets) deserves **promotion, not demotion** —
it is exactly the check that would have caught today's dead egress config automatically.

---

## 5. Method note

Three mechanisms I asserted this session were refuted by evidence (DP `max()` swallowing, the
Carrier write-failure feedback loop, "both gates clear simultaneously"). All three shared a shape:
**a plausible mechanism inferred from partial evidence and then built upon before being falsified.**
The marginal list above is largely the same shape caught earlier — cards whose premise is a reading
rather than a measurement. Worth treating "what measurement is this card's premise resting on?" as a
standing question at card-creation time.

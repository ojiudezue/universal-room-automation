# URA v5.108.37: arrivals named from a face plus the person's own phone arrival (step 7 S1)

Card: EGRESS-DIRECTION-AWARE-IDENTITY-1 (S1; the card stays open for the parked slices). Plan:
`docs/planning/PLANNING_egress_direction_aware_identity.md` rev 3.2 (plan review fixes da9ed11cd). D0:
`docs/planning/AUDIT_step7_d0_2026_11_17.md`. Tier 2-DB (elevated) + G: build 6b0401670, reviews A+G SHIP, B SHIP,
C FIX-REQUIRED (minor), fix pass d8ce7275e, hermetic-test fix c937f2717. Review records
`docs/reviews/code-review/v_step7_s1_review_{A_G,B,C}.md`.

Operator 2026-11-17: "1 - yes 2 - yes. We should do face after phone if gaps remain on ident. Phone is more reliable
now 3 - yes." "Ok on 0.6" "Jaya Ezinne not only confusable pair. It can also be Jaya Oji."

## What it does

The door tracker calls 9 of 15 graded entries "exit", and phones mark residents home 1-3 minutes before they reach the
door, so arrival notices often read "Someone left" or "Someone arrived" for a resident whose face the camera saw.

A notice now names the person ("Jaya Udezue arrived", whatever direction the tracker gave) when BOTH hold:
- a face leg at the crossing for that person (provenance `face` or `ble+face`; a single 0.6 face is enough), and
- that person's own counted arrival edge (not stale-source, not in the boot window) within
  [crossing - `EGRESS_ARRIVAL_EDGE_LEAD_S` (300 s), crossing + 45 s].

It does not name when the edge ring is truncated, or when a partner in "Faces often confused" also has an arrival edge
in that window. The combined evidence counts as 0.75 against the notification bar (`CONSUMER_CLASS_MIN_CONFIDENCE`
by name). It changes only the notification text: the bus event, crossing record identity / direction, DB rows, census
and every security / access reader are unchanged (INV-SECURITY, test-proven with a resolver person_id that differs from
the anchor slug). `const.py` refuses to load if the anchor confidence reaches the security bar.

## New setting

Coordinator Manager options, Presence step: **Faces often confused** (`CONF_EGRESS_CONFUSABLE_PAIRS`), pairs like
`jaya|ezinne, jaya|oji`. Empty by default (guard inert). Names resolve through the person-id rule; an unresolvable or
ambiguous name is skipped with a warning. Saving it does not reload the Coordinator Manager entry.

## Knobs (rung 1, `const.py`)

`EGRESS_ARRIVAL_EDGE_LEAD_S` 300 (0 = off, byte-identical to v5.108.36), `EGRESS_ARRIVAL_EDGE_CONFIDENCE` 0.75, the
minimum face tier, and the D3 trip-wire thresholds.

## Observability

Counters on the presence layer diagnostics (`edge_anchor_*`: anchored, pair_blocked, truncated, error); D8a outcome
rows carry an `edge_anchor` key; a nightly trip-wire pages if the feature never anchors over 7 days of rows that all
carry the key (quiet for the first 7 days after install, silent with LEAD 0).

## Live checks after install

1. Set "Faces often confused" to `jaya|ezinne, jaya|oji`; the entry does not reload; the setting reads back.
2. First phone-first resident arrival with a face at the door: notice "<Name> arrived"; D8a row `edge_anchor` set;
   bus `person_id` / `identity_confidence` unchanged from the resolver.
3. A Jaya / Ezinne (or Jaya / Oji) arrival together: anonymous text, `edge_anchor_pair_blocked` +1.
4. Grade the D0 candidates (11-13 18:18, 11-15 18:13 and the 4 pair-blocked crossings) on the grading page to check names.

## Validated 2026-11-19

Live from the 14:11:44 CST restart (with v5.108.38; the release was installed 11-18 23:50, after an operator-tapped HA core update restarted at 23:03).

| Criterion | Result | Evidence |
|---|---|---|
| 1 Setting | PASS | CM options Presence step shows `egress_confusable_pairs`; set to `jaya|ezinne, jaya|oji` via the options flow at ~14:30 (diff of all options: only that key changed, 292 -> 293; no CM reload) |
| 2-3 First named / pair-blocked arrival | Pending event | needs a phone-first resident arrival with a face at the door |
| 4 Names grading | Pending | names batch g20261119-0017 on the grading page |

## Not done (accounted, plan §11)

- P-1 face-before-phone naming: parked until identity gaps remain after S1 (operator Q2).
- P-6 ArrivalNotifier move: dropped under "Only proven code should supersede correct code"; S1 is an `anchor` keyword on
  the existing `_arrival_departure_notify`.
- P-7 departure naming: unchanged by design.
- Post-crossing waiter, follow-ups, perimeter pair-state, F5/HVAC, ambiguous crossings: parked with triggers.
- A ledger read error inside `get_person_edges_since` returns no edges and is not counted as `edge_anchor_error`
  (documented; the result is today's text).

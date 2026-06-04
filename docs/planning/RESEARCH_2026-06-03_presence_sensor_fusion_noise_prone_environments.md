# RESEARCH — Sensor fusion for presence in noise-prone (fan / pet) environments

**Status:** STUB + prior-art scan done 2026-06-03. Full write-up + reusable HA
blueprint = future work (pick up after exit). This doc captures the prior-art
landscape so we don't re-hoe a hoed road.

**Thesis (operator, 2026-06-03):** mmWave presence in rooms with ceiling fans
(and pets) is plagued by false-positives. Lots of people struggle with this. A
clear write-up + a **reusable, URA-independent HA blueprint** ("add BLE and your
noisy fan/pet rooms get reliable") could help many. Differentiator vs existing
work: **BLE-corroboration gating**, especially **zone-level BLE absence** +
**adjacent-room BLE-drift tolerance**.

## CORE REFRAME (operator, 2026-06-03) — fusion ≠ interference rejection

Prior art solves **FUSION** ("combine N noisy independent sensors into one
occupancy probability"). It does NOT solve **INTERFERENCE** ("one sensor is
*actively lying* because a mechanical noise source — fan, pet — is driving it").
Different problems. The operator runs Area-Occupancy-Detection (AOD) and reports
it "hasn't been great." Mechanism hypothesis (NOT YET verified against AOD source
— verify before publishing any claim about AOD specifically, per no-fabrication):

- Fusion integrations assign each sensor a **STATIC** reliability
  (`P(mmWave=on | empty)` = fixed small). When a fan is on, that probability is
  no longer small — but the model doesn't know the fan is on, so it keeps
  trusting a fan-fooled mmWave.
- **Decay does not save it.** Decay fires when signals go *quiet*; a fan-driven
  mmWave never goes quiet (stays continuously hot) → posterior pins to "occupied"
  and decay never engages. This is a STRUCTURAL blind spot, not a tuning miss —
  which is consistent with the operator's lived AOD experience.

**The missing primitive = INTERFERENCE-AWARE CONDITIONAL RELIABILITY.** When a
known interferer (fan == on) is active, mmWave's standalone vote collapses toward
zero UNLESS a fan/pet-immune signal corroborates it. That is a different mechanism
class than static-weight fusion, and it's the publishable contribution.

**Pets sharpen note a.** PIR rejects fans (blades aren't warm) but does NOT reject
pets (a dog is warm AND moving → PIR fires). The one signal that rejects BOTH fans
and pets is **BLE zone-absence** (neither has a phone). This is exactly why
zone-BLE-absence is "the strongest gate that works for all room kinds" — it's the
unifying corroborator, not a nice-to-have.

**Do NOT depend on / defer to AOD.** Cite fusion as a solved sub-problem; the
headline mechanism (interference-conditioned gating + BLE zone-absence) is ours.

## Aqara FP2 caveat (operator)

FP2 on-device pet AI does NOT count as prior art that solves this: notoriously
inconsistent, proprietary, and not universal (not everyone will buy Aqara). The
value of our approach is it works with cheap/any mmWave + BLE the user already has.

> Audience note: this is intentionally NOT a URA artifact. The blueprint must run
> on plain HA entities (a mmWave binary_sensor, optional PIR, BLE/area presence,
> a fan switch) + template/Bayesian helpers. URA can later adopt the same ideas
> internally, but the public deliverable stands alone.

## Prior art (scanned 2026-06-03 — cite, don't reinvent)

| Source | What it solves | Implication for us |
|---|---|---|
| **Hankanman/Area-Occupancy-Detection** (HA integration) | Bayesian FUSION of many sensor inputs WITH probability **decay** | Solves fusion, NOT interference. Operator runs it — "hasn't been great" (consistent with the static-reliability blind spot above). Cite as fusion baseline; do NOT depend on it or treat it as solving fan/pet interference. |
| **PIR + mmWave hybrid blueprint** (HA community t/...834566) | Combined occupancy from PIR + mmWave | The OR-vs-fusion question is already public. Compare our approach; credit it. |
| **Aqara FP2** | On-device AI pet filtering | Hardware path; best-in-class but imperfect, and proprietary. Our value = works with cheaper/any mmWave + BLE. |
| Hardware geometry | Ceiling-mount 15–30° down angle; 24GHz < 5.8GHz false-positive rate near fans/vents | Include as "mitigations before software." |

**Gap nobody fills cleanly:** using **BLE / area presence as a GATE** — "don't
even bother disambiguating mmWave if there's BLE anywhere in the zone" — with
**drift tolerance** for phones that flip between adjacent rooms. That's the
contribution worth publishing.

## Proposed blueprint shape (sketch — to be designed)

- Inputs: `mmwave` (binary_sensor), `fan` (switch/fan state — the interferer),
  optional `pir` (binary_sensor), and a **3-layer BLE corroboration ladder**:
  `ble_room_present`, `ble_adjacent_present` (configured adjacent rooms),
  `ble_zone_present` (any BLE in the zone). Per operator (2026-06-03): "its room,
  adjacent rooms AND zone absence. These layers will matter."
- Logic (interference-conditioned gate FIRST, then BLE ladder):
  1. **Layer 1 — room BLE present** → occupied, full trust, **never pause**.
  2. **Layer 2 — room absent but adjacent present** → DRIFT case → lean occupied,
     hold under decay, **do not pause** (this layer kills the false-pause).
  3. `pir` recently fired → warm-body corroboration (beats fans, NOT pets).
  4. **Interference gate:** `fan == on` AND mmwave is the only signal AND no BLE
     layer 1/2 AND no recent PIR → mmwave's standalone vote **collapses** → hold
     last-known under a decay timer (don't drop, don't pause yet).
  5. **Layer 3 — zone-wide BLE absence** at decay-expiry (nobody anywhere in
     zone; beats pets too) → discount mmwave / optional **fan-pause-and-recheck**
     (the rare, justified disruption).
- Output: a `binary_sensor` (occupancy) + reason attribute (which layer/gate
  decided).

## Open questions for the write-up

- Bayesian (Area-Occupancy style) vs simple decay-timer template — which to lead
  with for a general audience?
- How to express "adjacent rooms" portably (HA areas? a user-listed group?).
- Pet handling: does BLE-gating + decay already make pets a non-issue, or do we
  still recommend mmWave AI / mounting geometry?

## Cross-refs
- URA-side cycle + the Tier-1 PIR/mmwave OR split prereq: `docs/BACKLOG.md`
  (Fan-noise entry) + `docs/TECH_DEBT.md` (Tier-1 OR provenance).
- Memory: `project-fan-noise-mmwave-mitigation-backlog` (rehydration anchor).

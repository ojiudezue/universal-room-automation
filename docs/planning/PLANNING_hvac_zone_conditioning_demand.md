# PLANNING — HVAC Zone Conditioning Demand (kind-aware, per-room hold, OR aggregation)

**Card:** `HVAC-ZONE-CONDITIONING-DEMAND-1` (step 4 of `HVAC-SUPPLE-SEQUENCE-1`)
**Tier:** 2-DB (regression-prone, cross-coordinator ripple — presence ↔ HVAC ↔ compliance)
**Status:** pre-build. Stage 0 confirmed (42 corridor : 0 dwelling). Operator checkpoint cleared.
**Revision:** Plan-review round 1 findings folded 2026-09-16 (CRIT-1 fixed, HIGH-1/2 fixed, MEDs fixed; CRIT-2 flagged OPERATOR-PENDING — see §0a).
**Companions (read first):**
- `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`
- `docs/planning/AUDIT_hvac_conditioning_demand_supersession_and_reuse_2026_09_16.md`

This plan graduates the proposal to a buildable spec. No versioning — unshipped.

---

## 0. Falsifiable invariant (single load-bearing property) — CONTINGENT ON §0a

> **A house-zone whose only occupied member rooms are `hallway`-typed (circulation)
> is NEVER conditioned via the DAYTIME preset path. A zone with any dwelling-typed
> member room whose HVAC-occupancy signal is true (kind-aware presence, layered on
> the room's grace-held `STATE_OCCUPIED`, held for that room's `hvac_vacancy_hold`)
> IS conditioned. Retreat happens exactly once, at the zone level, after the LAST
> HVAC-occupied member room has been clear for `vacancy_grace` (10 min live).**

Corollaries reviewers must falsify:
- Aggression is **absolute** on the daytime path: no relaxation, no soft posture, no partial vote from hallways.
- Grace-hold is **inherited, not rebuilt**: HVAC-occupancy is a kind-aware filter *on top of* the room's already-grace-held `STATE_OCCUPIED`, never over raw substrate reads.
- The two dwell timers (per-room `hvac_vacancy_hold` for adopt, zone `vacancy_grace` for retreat) never stack — the zone-level `CONF_HVAC_ZONE_ENTRY_DWELL` defaults to **0** in the same cycle the per-room hold ships.

**Caveat "DAYTIME preset path" is required** because the night-trust branch at `hvac.py:2027` (`if effective_preset == "away" and self._house_state in FAN_TRUST_STATES`) can flip `away` back to a home-flank preset based on `zone_persons` phone-home state alone, bypassing room occupancy entirely. Under night-trust, a corridor-only zone remains conditioned. This is **the reason** Stage 0's 42:0 waste tally is overnight-heavy — and the reason CRIT-2 (§0a) is unresolved.

---

## 0a. CRIT-2 — OPERATOR-PENDING: night-trust interaction with the invariant

**Not for the plan-reviewer to resolve. The build must not dispatch until the operator picks A or B.**

The invariant above is FALSE at night as written. Evidence in code:

- `hvac.py:2027` — night-trust branch: `if effective_preset == "away" and self._house_state in FAN_TRUST_STATES` (where `FAN_TRUST_STATES` = `home_night` / `sleep` / `waking`). If any `zone_persons` entity reads `home`, the branch un-flips `away` back to a home-flank preset, WITHOUT consulting `zone.any_room_occupied`.
- The entire zone-vacant override at `hvac.py:1793` is inside `if zi:` and its grace uses `_vacancy_grace_constrained` (further compressed under energy coast/shed).
- Stage 0's measured 42:0 (corridor:dwelling) episodes are **overnight** — precisely when night-trust runs. Under Option A the cycle helps mostly by day.

**Option A — restate the invariant with its real antecedents (recommended for scope discipline).**
- Invariant reads: "*by day (house_state not in FAN_TRUST_STATES), a zone whose only occupied rooms are `hallway`-typed is never conditioned; night-trust behavior is unchanged.*"
- **Comfort implication:** overnight comfort unchanged. Sleeping resident with phone-home keeps every zone in a home-flank preset; corridor-only zones stay conditioned overnight (today's behavior).
- **Energy implication:** most of Stage 0's 42:0 waste is NOT recovered this cycle. The cycle recovers daytime pointless conditioning + any overnight episode where every `zone_persons` phone is away or unreadable. Estimated savings a fraction of the measured baseline; the fast/large win is deferred.
- **Scope:** trust hierarchy untouched. Ship risk minimal.

**Option B — bring the night-trust gate into scope (broader change, larger prize).**
- Add a member-room-occupancy consideration to the night-trust branch: an empty-corridor zone may retreat even under `FAN_TRUST_STATES` if no member room's HVAC-occupancy is true.
- Concretely: at `hvac.py:2027`, the guard becomes "if `effective_preset == "away"` AND `self._house_state in FAN_TRUST_STATES` AND `zone.any_room_occupied`, then re-consult `home_persons`; else let `away` stand." (Sketch — the builder pins the exact condition after review.)
- **Comfort implication:** a sleeping resident whose phone reads `home` no longer keeps EVERY zone conditioned — a zone the resident is not physically in retreats to `away` overnight if empty past grace. Rooms downstream of a hallway that the resident is not in also retreat. The founding rationale for night-trust (mmWave drops still bodies) means false-retreat risk in the resident's OWN bedroom is real unless the per-room HVAC-occupancy signal correctly holds via mmWave-still — which is the whole point of D1. Requires validation that Stage A holds actually pin the bedroom on overnight before this can ship.
- **Energy implication:** recovers most of the 42:0 waste. Materially larger prize.
- **Scope:** trust-hierarchy change — a delicate cross-coordinator invariant is edited. Elevates review posture (Tier 2-DB is the floor; operator may elevate to Tier 3 given the night-safety concern).
- **Prior context:** `project_zone_away_when_occupied_home_night_gap` documents that this branch is INTENTIONALLY sleep/night-flank inclusive because of the 2026-06-05 finding (Zone 1 flipped `away` 7+ times during `home_night`). Option B partly reverses that intent, contingent on Stage A being trustworthy at night.

**Operator decision required before build dispatch.** Pick A or B. The rest of this plan (D1–D6) is written assuming Option A — if the operator picks B, add D7 (below) to scope.

**Optional D7 (only if operator picks Option B) — Night-trust gate consults member-room HVAC-occupancy.**
- **What.** Edit `hvac.py:2027` block to short-circuit un-flipping `away` when `zone.any_room_occupied` (post-swap: any member room's HVAC-occupancy is true) is false.
- **Non-negotiable pre-req:** Stage A holds must be measured to reliably pin at least one dwelling room in the resident's bedroom overnight (i.e. mmWave-still holds through the sleep cycle without dropout past `hvac_vacancy_hold`). If the measurement fails, D7 stays parked; ship Option A.
- **Review posture:** elevates to Tier 2-DB minimum; operator may declare Tier 3 (falsifiable-invariant framing #D = "no sleeping resident's own bedroom ever falls to away overnight").

---

## 1. Institutional context verified (REUSE-or-BUILD per piece)

Sources: audit §(ii), re-verified this session against source. File:line citations authoritative. **Revised** to reflect the CRIT-1 correction: we introduce a SIBLING signal on `RoomCondition` consumed ONLY by the conditioning/preset path, and leave `RoomCondition.occupied` untouched for lights/fans/covers/confidence.

| Piece the plan needs | Verdict | Existing prior art | Notes |
|---|---|---|---|
| Kind-aware presence (mmwave / motion / occupancy) | **REUSE** | `occupancy_substrate.is_kind_active(room, kind)` at `occupancy_substrate.py:732`; `get_room_kinds` at `:747`; module handle at `hass.data[DOMAIN]["occupancy_substrate"]` (see `presence.py:2592`) | Zero new wiring. |
| Per-kind provenance at zone boundary | **REUSE** | `ZonePresenceTracker.provenance_for(room)` at `presence.py:707` | Fan-hold-aware view. Not the one D1 uses; the direct `is_kind_active` gives fan-hold-*excluded* semantics for HVAC-occupancy. Documented in D1. |
| Per-room, per-consumer secondary hold pattern | **REUSE (shape)** | `CONF_FAN_VACANCY_HOLD` at `const.py:966`; `DEFAULT_FAN_VACANCY_HOLD=300` at `const.py:1153`; consumer `automation.py:2164` | New `CONF_HVAC_VACANCY_HOLD` follows this shape. `DEFAULT_HVAC_VACANCY_HOLD` lives ONCE at `const.py` (no `hvac_const.py` duplicate — `DEFAULT_FAN_VACANCY_HOLD` is already the cautionary tale, doubled at `const.py:1153` + `hvac_const.py:821`). |
| Zone occupancy confidence | **REUSE (unchanged)** | `presence.check_zone_occupancy_confidence(zone)` at `presence.py:2057`; Source-4 at `presence.py:2150` counts `rc.occupied` | **No-swap here** — see HIGH-2 verdicts §2a. `rc.occupied` remains the lighting-fused signal; Source-4 keeps its established semantics. |
| Grace-hold semantics | **REUSE (untouched)** | `coordinator.py:2925-2938` ARM; `coordinator.py:3581-3585` consume | New HVAC-occupancy view derives from `data[STATE_OCCUPIED]` (grace-held), never raw substrate. |
| Zone OR aggregation (adopt) | **REUSE (existing OR)** | `hvac_zones.py:148` `any_room_occupied = any(r.occupied ...)` | **Kept** for the lighting/fan/cover/vacancy-sweep semantics unchanged. **A new sibling zone attribute (`any_room_hvac_occupied`)** is introduced and consumed ONLY by the preset-decision path at `hvac.py:1794`. See D1/CRIT-1. |
| Zone retreat (grace) | **REUSE** | `hvac.py:1786-1791` grace_minutes gate | Reads `any_room_hvac_occupied` post-CRIT-1-fix (was `any_room_occupied`). |
| Population point | **REUSE (add sibling; do NOT swap)** | `hvac_zones.py:546` (`RoomCondition.occupied` from `data["occupied"]`) | ADD `RoomCondition.hvac_occupied` fed by the new producer, adjacent to the existing `occupied` line. Existing `occupied` field UNCHANGED. |
| ROOM_TYPE defaults tables | **REUSE (pattern) + BUILD (new table)** | `ROOM_TYPE_TIMEOUTS` at `const.py:1171`. All five `ROOM_TYPE_*` tables use `.get(type, DEFAULT)` — see §D4 for the enumerated list. | Add `ROOM_TYPE_HVAC_HOLD` mirroring shape. |
| Fast sub-loop (Stage D fast-in) | **DEFERRED** | `SOLAR_FOLLOW_TICK_S=60` `energy_const.py:996`; `_solar_follow` `energy.py:1382` | Not built. |
| `hallway` room_type enum value | **BUILD (safe additive)** | Enum in `const.py:421-429`; create-flow selector `config_flow.py:1387`; **options-flow selector `config_flow.py:10410-10420`** (the reclassification surface for the 6 existing hallways) | Both selector lists must be edited (HIGH-1). |
| `CONF_HVAC_VACANCY_HOLD` (per-room) | **BUILD** | `CONF_FAN_VACANCY_HOLD` is the template. | New per-room CONF. |
| Per-room HVAC-occupancy entity | **BUILD** | No equivalent. `OccupiedBinarySensor` is sibling, not equivalent. | Operator mandate: must be observable. |

**Design docs read, planning docs consulted, memory bodies, code locations surveyed:** unchanged from round 0 (see git history). Additionally verified for this revision: `hvac.py:2027-2040` (night-trust branch), `hvac.py:3149-3220` (`_execute_vacancy_sweep`, no per-room occupancy guard), `hvac_fans.py:1477` (`_read_room_occupied_state`), `hvac_covers.py:626` (`STATE_OCCUPIED` cover close), `presence.py:2150` (Source-4 counting `rc.occupied`), `config_flow.py:10410-10420` (options-flow room_types selector).

---

## 2. Deliverables

### D1 — Per-room HVAC-occupancy producer + SIBLING `RoomCondition.hvac_occupied` (CRIT-1 fix)

**Correction from round 0.** The prior draft said "swap the input at `hvac_zones.py:546`, no parallel field, 12+ consumers see the new semantics transparently." **That is unsafe.** `RoomCondition.occupied` is read not only by preset/conditioning decisions but by:

- `_execute_vacancy_sweep` at `hvac.py:3149-3220` — turns off `CONF_LIGHTS + CONF_NIGHT_LIGHTS + CONF_FANS` **in every `zone.rooms` room, including hallways, with NO per-room occupancy guard** (light loop lines 3180-3193). A hallway person with a hallway light manually on would have that light killed the moment the zone sweep fires, because the corridor room contributes nothing to `any_room_occupied` post-swap. This is a Bug Class #63 lighting-actuator-reading-conditioning-value collision.
- `hvac_fans.py:1477` `_read_room_occupied_state` — fan-OFF suppression guard; must retain lighting-hold semantics or fans flicker off on the same corridor-crossing latency the plan is trying to introduce.
- `hvac_covers.py:626` `STATE_OCCUPIED` — occupied-cover-close policy.
- `presence.py:2150` `check_zone_occupancy_confidence` Source-4 — counts `rc.occupied` rooms as an evidence source; changing meaning shifts confidence math silently.

**Corrected design.**

- Introduce a **new field on `RoomCondition`**: `hvac_occupied: bool` (default False), populated adjacent to the existing `occupied=...` at `hvac_zones.py:546` from the new producer:

    ```
    hvac_occupied = self._hvac_occupancy.value_for(room_name)
    ```

- Add a **new derived attribute on `ZoneState`**: `any_room_hvac_occupied = any(rc.hvac_occupied for rc in zone.room_conditions)`, computed at the same place as `any_room_occupied` in `hvac_zones.py:148`.
- **Rewire ONLY the preset-decision reads** to consume the new attribute:
  - `hvac.py:1794` `not zone.any_room_occupied` → `not zone.any_room_hvac_occupied`
  - The retreat/grace timestamp update at `hvac_zones.py:555-566` (`zone.last_occupied_time = now if zone.any_room_occupied`) uses `any_room_hvac_occupied` for the CONDITIONING timeline. **Requires care:** `last_occupied_time` also gates `_execute_vacancy_sweep` firing (via `zone_vacant_past_grace`). Since the vacancy sweep is downstream of the preset flip (`hvac.py:1804`), it fires only when the preset went `away` — which under the new rule requires HVAC-vacant, which is the correct gating. The lighting-fused `any_room_occupied` remains available for anyone who needs it and is untouched.
- **Do NOT touch:** `_execute_vacancy_sweep` (still iterates `zone.rooms` unchanged — sweep fires when the zone flips `away`, which is now driven by HVAC-occupancy; the per-room light-off inside the sweep continues to be the "zone went away" downstream effect), `hvac_fans.py:1477`, `hvac_covers.py:626`, `presence.py:2150`. All continue to read `rc.occupied` / `any_room_occupied` (lighting-fused). See §2a for per-site verdicts (HIGH-2).

**Producer semantics (unchanged from round 0).**

```
hvac_occupied(room) =
    room[STATE_OCCUPIED]                             # grace-held, fused
    AND kind_aware_filter(room)                      # is_kind_active over allowed kinds
    AND room_type(room) != "hallway"                 # aggression = absolute
    with tail-hold(room, hvac_vacancy_hold)          # per-room decay
```

`kind_aware_filter`: any of `mmwave` / `occupancy` / `motion` via `occupancy_substrate.is_kind_active`. AND-on-`STATE_OCCUPIED` inherits grace-hold (Bug Class #7 defense).

**Acceptance criteria (D1):**
- **Verify:** `RoomCondition.occupied` field, `any_room_occupied`, and every non-preset consumer (§2a) are byte-identical pre/post. `git diff` proves untouched.
- **Verify:** the preset path at `hvac.py:1794` and the retreat timestamp write in `hvac_zones.py:555-566` are the only sites reading `any_room_hvac_occupied`.
- **Verify:** on sensor blip, `hvac_occupied(room)` mirrors `data[STATE_OCCUPIED]` — grace_hold rides.
- **Sensor:** `binary_sensor.<room>_hvac_occupied` (D2) matches the producer per tick.
- **Test:** `test_hvac_occupancy_sibling_field_isolation` — mutate the producer to always-False; assert lighting sweep still triggers per zone-away, fans/covers unchanged, `check_zone_occupancy_confidence` Source-4 returns pre-cycle count.
- **Test:** `test_hvac_occupancy_grace_hold_inherits`, `test_hallway_returns_false_regardless_of_kinds`.
- **Live (discriminating):** with a person walking a hallway and dwelling rooms empty, `sensor.hvac_zone_<N>_status.attributes.any_room_hvac_occupied == false` while `any_room_occupied` (retained attribute if surfaced) or `<hallway>_occupied` remains `on`. **Under the wrong-fix failure mode** (a swap rather than sibling), the hallway light would go dark on the next zone-sweep tick — observable and distinct.

### D2 — Per-room HVAC-occupancy diagnostic entity (observability)

Unchanged from round 0. `binary_sensor.<room>_hvac_occupied` mirrors `OccupiedBinarySensor` shape; attrs include `kinds_active`, `hvac_vacancy_hold_s`, `hold_expires_at`, `room_type`, `source = "hvac_occupancy"`.

**Acceptance criteria (D2):** as in round 0.

### D3 — `ROOM_TYPE_HVAC_HOLD` defaults + `CONF_HVAC_VACANCY_HOLD` per-room override + single-home default

**What.**
- Add `DEFAULT_HVAC_VACANCY_HOLD: Final = 60` in `const.py` **exactly once** (adjacent to `DEFAULT_FAN_VACANCY_HOLD` at `const.py:1153`). Do NOT add a copy in `hvac_const.py` — `DEFAULT_FAN_VACANCY_HOLD` is already the doubled cautionary tale (`const.py:1153` + `hvac_const.py:821`).
- Add `ROOM_TYPE_HVAC_HOLD` dict in `const.py` alongside `ROOM_TYPE_TIMEOUTS` (`const.py:1171`). Initial values (seconds):
  - `hallway`: `0` (hallway short-circuits in D1 regardless)
  - `bathroom`, `closet`, `garage`, `infrastructure`, `utility`: `0`
  - `bedroom`: `120`
  - `common_area`, `generic`: `DEFAULT_HVAC_VACANCY_HOLD` (60)
  - `media_room`: `180`
- Add `CONF_HVAC_VACANCY_HOLD` in `const.py` next to `CONF_FAN_VACANCY_HOLD` (`const.py:966`). Room-level override; unit = seconds; effective value resolves via `ROOM_TYPE_HVAC_HOLD.get(type, DEFAULT_HVAC_VACANCY_HOLD)`.
- Read the effective value at the D1 producer via the same shape as `automation.py:2164` reads `CONF_FAN_VACANCY_HOLD`.

**Acceptance criteria (D3):**
- **Verify:** grep `DEFAULT_HVAC_VACANCY_HOLD` returns exactly one definition (in `const.py`).
- **Verify:** no inline `60` literal in D1 or D2 — the constant name is used.
- **Verify:** `ROOM_TYPE_HVAC_HOLD` reads use `.get(type, DEFAULT_HVAC_VACANCY_HOLD)`; subscript access forbidden.
- **Test / Live:** as in round 0.

### D4 — `hallway` room_type enum value + reclassification of 6 rooms (HIGH-1 + MED (c) fix)

**What.**
- Add `ROOM_TYPE_HALLWAY = "hallway"` to the enum block at `const.py:421-429`.
- **Edit BOTH selector lists** — create-flow AND options-flow:
  - `config_flow.py:1387` (create-flow `room_types` list — new-room setup).
  - `config_flow.py:10410-10420` (**options-flow `room_types` list, selector at `:10431`**). This is the surface the operator actually uses to reclassify the 6 hallways; the round-0 plan omitted this list and would have made D4's own reclassification acceptance criterion unachievable.
- Reclassify the 6 known hallways (Garage Hallway, Kitchen Hallway, Kitchen Hallway Garage, Master Hallway, Upstairs Hallway, Foyer) via a **one-shot options-flow edit** per room — NOT an auto-migration. Document exact rooms and expected effect in the README.
- Wire `ROOM_TYPE_HALLWAY` into ALL FIVE `ROOM_TYPE_*` tables (audit + this revision re-verify `.get()` safety across each):
  1. `ROOM_TYPE_TIMEOUTS` (`const.py:1171`) — set `hallway` to a short value (e.g. `120`). **MED (b) caveat:** `ROOM_TYPE_TIMEOUTS` is consumed by `config_flow.py:1379-1382` on room *create* to seed `occupancy_timeout`; it does NOT re-seed the 6 existing hallways on options-flow reclassify. Two acceptable dispositions — pick ONE at build:
     - (b-i) State in the README that the hallway timeout applies to newly-created hallway rooms only; existing 6 keep their current `occupancy_timeout` (mostly 300s, 360s for Garage Hallway). Acceptable because their existing timeouts are already short and the HVAC path no longer depends on this value for retreat.
     - (b-ii) Add an explicit operator step to the reclassification runbook: "for each of the 6 hallway rooms, set `occupancy_timeout = 120` in the options flow." Preferred if operator observability is desired.
  2. `ROOM_TYPE_RECHECK_FACTOR` (grep `const.py` for the recheck-factor table) — safe additive; set `hallway` to the same value as `common_area` or lower.
  3. `ROOM_TYPE_FAILSAFE_DURATIONS` — hallway short.
  4. `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` / `ROOM_TYPE_BLE_HOLD_CAP_DURATIONS` — safe additive.
  5. `ROOM_TYPE_FEATURE_DEFAULTS` — safe additive; hallway defaults conservative (no music-follow, etc.).
  6. `ROOM_TYPE_HVAC_HOLD` (new; D3) — `hallway = 0`.

`.get()` safety confirmed across all consumers (`coordinator.py:695,3814`, `config_flow.py:1381`, `presence_fan_recheck.py:1102`). New enum value cannot KeyError.

**Acceptance criteria (D4):**
- **Verify:** both selector lists at `config_flow.py:1387` and `config_flow.py:10410-10420` carry the `hallway` option, with matching label.
- **Verify:** every `ROOM_TYPE_*` table listed above has a `hallway` entry OR is explicitly `.get(..., DEFAULT)`-safe with a documented default that suits hallway.
- **Verify:** the 6 hallway rooms carry `room_type: hallway` in `.storage/core.config_entries` post-reclassification.
- **Verify (MED-b):** README states the chosen disposition (b-i or b-ii) and, if b-ii, includes the runbook step.
- **Test:** `test_hallway_room_type_no_keyerror_across_tables` iterates all five `ROOM_TYPE_*` tables with `hallway`.
- **Live (discriminating):** person crosses all 6 hallways in sequence during a vacant daytime zone; `sensor.hvac_zone_<N>_status.attributes.any_room_hvac_occupied` stays `false`; every `<hallway>_hvac_occupied == off`. **Under the wrong-fix failure mode** (hallway added to create-flow only), the 6 existing rooms cannot be reclassified via options flow and remain `common_area` — Live fails immediately.

### D5 — Retire zone-level `zone_entry_dwell` (default 0, keep field one release)

Unchanged from round 0. Flip `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` at `hvac_const.py:377` from `3` → `0`. Leave `CONF_HVAC_ZONE_ENTRY_DWELL`, `number.py:417` `ZoneEntryDwellNumber`, and consumer `hvac.py:1986-1996` in place with a LEGACY comment. Deletion next release.

### D6 — Zone-aggregation retreat semantics preserved (documentation-only)

Unchanged from round 0. Documentation-only; comment update at `hvac.py:1786-1791` + README note that `vacancy_grace` is the sole retreat timer and per-room `hvac_vacancy_hold` is a gap-bridger only. **Amended:** the retreat now reads `any_room_hvac_occupied` (D1); block comment should call that out.

### D7 — (CONDITIONAL, Option B only) Night-trust gate consults member-room HVAC-occupancy

See §0a. Do not scope, do not build until operator picks Option B.

---

## 2a. HIGH-2 — Explicit swap/no-swap verdict per non-preset consumer

Post-CRIT-1 fix, the default posture is **no-swap, keep lighting semantics** — `rc.occupied` is the lighting-fused signal for lighting/fan/cover/confidence paths. Explicit per-site verdicts:

| Site | Reads | Verdict | Reasoning |
|---|---|---|---|
| `_execute_vacancy_sweep` at `hvac.py:3149-3220` | `zone.rooms` (iterates ALL rooms unconditionally, no per-room `rc.occupied` guard) | **NO-SWAP (n/a — no rc.occupied read)** | Sweep runs after the zone flips `away`. The zone-flip is now HVAC-occupancy driven (D1). Inside the sweep, per-room iteration has no `.occupied` check — the light kill is intentional "zone went away, kill all URA-managed lights in it." No change. |
| `hvac_fans.py:1477` `_read_room_occupied_state` (fan-OFF suppression guard) | `rc.occupied` (implicit — read the site's own callers) | **NO-SWAP — keep `rc.occupied` (lighting-fused)** | Fan-OFF suppression guards against yanking the fan off a person still in the room. Lighting-hold semantics are the more generous, correct choice here — a shorter HVAC-occupancy signal would let fans flick off on transient crossings the person is still standing in. |
| `hvac_covers.py:626` `STATE_OCCUPIED` (occupied-cover-close policy) | room `STATE_OCCUPIED` (lighting-fused, held) | **NO-SWAP — keep lighting-fused** | Cover close is a courtesy/privacy action; a longer hold is the correct policy. HVAC-occupancy would cause covers to close on brief transit — not desired. |
| `presence.py:2150` `check_zone_occupancy_confidence` Source-4 (counts `rc.occupied` rooms) | `rc.occupied` | **NO-SWAP — keep `rc.occupied`** | Source-4 counts rooms as *evidence sources* for zone-occupancy confidence — a lighting-fused reading is the intended "the room saw activity recently" signal. Swapping introduces a silent confidence-math shift for a change the consumer never asked for. |
| `hvac.py:1794` preset flip (`zone_vacant_past_grace`) | `zone.any_room_occupied` | **SWAP to `any_room_hvac_occupied`** | The CRIT-1 fix. This is the ONE conditioning-decision site. |
| `hvac_zones.py:555-566` `last_occupied_time` write / `continuous_occupied_since` / `current_session_start` | `zone.any_room_occupied` | **SWAP to `any_room_hvac_occupied`** | These timestamps feed the preset flip and D5/D6 stale/session logic — they must move together with the preset decision or the grace timer references a different definition than the flip. |
| D6 stale-occupancy branch `hvac.py:1814-1820` | `zone.any_room_occupied` | **SWAP to `any_room_hvac_occupied`** | Stale-sensor failsafe must be in the same denomination as the preset flip; else it fires stale against a signal the preset never used. |
| Other 8-ish `RoomCondition.occupied` / `any_room_occupied` consumers listed in audit (`hvac_override.py:2282,2433`, `hvac_predict.py:578,1368`, `hvac_zones.py:584`, `hvac_egress.py:483`, `hvac_fans.py:755,986`, `hvac.py:1787,1808,3462,3627`) | mostly `rc.occupied` or `any_room_occupied` | **VERDICT PER-SITE AT BUILD** — presumption **NO-SWAP** unless the site is a preset/conditioning-decision consumer | Builder task: enumerate each in the D1 changelist, cite whether it participates in the preset flip (SWAP) or in a lighting/fan/cover/prediction/override/egress semantic (NO-SWAP). The presumption for anything not in the preset path is NO-SWAP. Any SWAP requires an explicit line in the changelist naming the site + reasoning; a silent SWAP is a review-blocking finding. |

Rule of thumb for the builder: **swap iff the site is on the code path from `zone.any_room_occupied` to `effective_preset` mutation.** Everything else stays on the lighting-fused reading.

---

## 3. Code supersession triage (audit §(i), amended for CRIT-1 fix)

Zero-DELETE outcome preserved. Key changes vs round 0:

- **S3 changed.** No longer a repoint of `RoomCondition.occupied`. Now: ADD `RoomCondition.hvac_occupied` sibling at the same population site. `RoomCondition.occupied` untouched.
- **S1 unchanged** — `CONF_HVAC_ZONE_ENTRY_DWELL` default 0 (D5).
- **S4 unchanged** — documentation.
- **S5/S6/S7 unchanged** — untouched, block comments updated.
- **S8** — re-grep at build time.

---

## 4. Knob ladder

Unchanged from round 0, with the D3 clarification: `DEFAULT_HVAC_VACANCY_HOLD` lives once, in `const.py`, as a module constant (reviewed code change to change the default). `CONF_HVAC_VACANCY_HOLD` is the per-room override (options flow). Diagnostic entity is not a knob.

---

## 5. Tier 2-DB review protocol (three framing-disjoint axes)

Amended for CRIT-1 and CRIT-2:

- **Review A — correctness + edge cases on the D1 producer + sibling field isolation.** Grace-hold inheritance; kind-aware filter under mmWave dropout / PIR-only / fan-hold interactions; per-room hold decay across restart; hallway short-circuit; **byte-identity of `RoomCondition.occupied` and every non-preset consumer** (mutation drill: neuter D1 producer to always-False; lighting sweep + fans + covers + Source-4 must be unaffected).
- **Review B — cross-coordinator / precedence / no-flap.** Zone retreat unchanged in shape; per-room hold does not stack with `vacancy_grace`; `CONF_HVAC_ZONE_ENTRY_DWELL=0` default honored fresh + restart; pre-arrival exemption at `hvac.py:1993` unaffected; **night-trust branch at `hvac.py:2027-2040` explicitly re-examined** under the chosen §0a option (A: verify unchanged; B: verify D7 semantics + Stage A hold reliability at night).
- **Review C — surfaces + test authority.** `binary_sensor.<room>_hvac_occupied` round-trips options/registry/RestoreEntity; `ROOM_TYPE_HALLWAY` no KeyError across all five `ROOM_TYPE_*` tables (name each); both selector lists (`config_flow.py:1387` AND `:10410`) updated; reclassification of 6 hallway rooms persists across reload; each behavioral test is mutation-anchored (neuter the hallway short-circuit; specific test fails).

If operator picks Option B, review posture may elevate to Tier 3 (add adversarial-completeness pass D on the invariant "no sleeping resident's own bedroom falls to away overnight").

---

## 6. Non-goals (explicit)

Unchanged from round 0, plus:
- **Option B night-trust change is a non-goal UNLESS the operator explicitly picks it.**
- **Swap of `rc.occupied` / `any_room_occupied` at ANY non-preset consumer.** Presumption is NO-SWAP per §2a.

---

## 7. Source disagreements resolved

1. Live vs default `vacancy_grace` / `zone_entry_dwell`: resolution unchanged from round 0.
2. Proposal A′-2 vs audit S1: resolution unchanged (audit's staged approach).
3. **NEW — round 0 vs plan review.** Round 0 followed the audit's "swap the input at `hvac_zones.py:546`, no parallel field" advice. Plan review CRIT-1 correctly identified this as unsafe: the audit's consumer census counted preset consumers but missed the lighting/fan/cover/confidence semantics of the same field. **Resolution:** SIBLING field (`RoomCondition.hvac_occupied` + `zone.any_room_hvac_occupied`), consumed only by the preset flip and its co-timestamps (§2a). The audit's "swap not parallel" recommendation is superseded on this point.

---

## Summary of round-1 changes vs prior draft

- **CRIT-1 (fixed):** D1 restructured — sibling `RoomCondition.hvac_occupied` + `zone.any_room_hvac_occupied`, populated adjacent to `.occupied` at `hvac_zones.py:546`. Preset path and its co-timestamps consume the new signal; lighting/fan/cover/confidence sites remain on `rc.occupied`. §2a lists every consumer with an explicit SWAP or NO-SWAP verdict.
- **CRIT-2 (OPERATOR-PENDING, §0a):** invariant qualified "DAYTIME preset path"; two options (A restate scope / B bring night-trust into scope with a conditional D7) laid out with comfort/energy/scope implications. Build must not dispatch until operator picks.
- **HIGH-1 (fixed):** D4 now edits BOTH selector lists — create-flow `config_flow.py:1387` AND options-flow `config_flow.py:10410-10420`. Live-verification of hallway reclassification is now achievable.
- **HIGH-2 (fixed):** §2a explicit per-site SWAP/NO-SWAP verdicts for `_execute_vacancy_sweep`, `hvac_fans.py:1477`, `hvac_covers.py:626`, `presence.py:2150`, plus the rule of thumb for the remaining ~8 consumers.
- **MED (a) (fixed):** `DEFAULT_HVAC_VACANCY_HOLD` lives once in `const.py`; no `hvac_const.py` duplicate; no inline `60` literal in D1/D2/D3.
- **MED (b) (fixed):** D4 calls out `ROOM_TYPE_TIMEOUTS` create-time-only semantics and requires the build to pick disposition (b-i new-only / b-ii runbook step for the 6 rooms).
- **MED (c) (fixed):** D4 enumerates all five `ROOM_TYPE_*` tables by name.

## Operator options for CRIT-2 (recap)

- **A — restate invariant to DAYTIME.** No trust-hierarchy change. Cycle recovers daytime waste only; most of the 42:0 baseline is overnight and stays. Recommended for scope discipline; the trust hierarchy is delicate and Stage 0 waste can be revisited in a follow-up cycle.
- **B — bring night-trust into scope (D7).** Reads member-room HVAC-occupancy in the `hvac.py:2027` branch so empty-corridor zones may retreat even under `FAN_TRUST_STATES`. Larger prize; requires proving Stage A holds reliably pin the resident's bedroom overnight (mmWave-still through the sleep cycle) before it is safe to ship. Elevates review posture; may warrant Tier 3.

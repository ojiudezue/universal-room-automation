# Room & Zone Classification — canonical map

**Status:** authoritative reference · **Written:** 2026-09-14 (ROOM-CLASSIFICATION-CONSISTENCY-1, D1)
**Verified against:** live tree + adversarial plan-review greps (file:line below are review-confirmed).

URA has **no single "room class" field.** Classification is spread across several independent
surfaces on two axes — a room's **function** (`CONF_ROOM_TYPE`, an enum) and a set of **load-bearing
property flags** (guest, wet, shared, outdoor). This doc is the map: what each surface is, who
produces it, who consumes it, and the two places where the neat "one producer per flag" story has a
documented exception. Read it before touching any classification consumer — the failure mode is a
"small surgical fix" that silently moves a safety or presence decision (Bug Class #53, one-missed-site).

Live config snapshot (2026-09-14, 46 URA entries): `common_area` 15, `closet` 7, `bathroom` 7,
`bedroom` 6, `generic` 2, `garage` 2, `utility` 2, `infrastructure` 1, `media_room` 1. **0 rooms typed
`basement`; 0 zones flagged `outdoor`.** Two classification code paths (basement bands, outdoor
coercion) therefore fire for **no configured room today** — see §Dead-but-load-bearing.

---

## The two axes

- **FUNCTION — `CONF_ROOM_TYPE`** (a single enum value per room): `generic`, `common_area`, `bathroom`,
  `bedroom`, `closet`, `garage`, `utility`, `infrastructure`, `media_room`. Const block `const.py:421-429`.
  Keys into **five** behaviour tables (below).
- **PROPERTY FLAGS** (independent booleans, a room/zone can carry several): `CONF_ROOM_IS_GUEST_ROOM`,
  `CONF_WET_ROOM`, `CONF_SHARED_SPACE` (room-scoped) and `CONF_ZONE_IS_OUTDOOR` (**zone-scoped** — the
  one flag that is not per-room).

---

## Surface-by-surface

### `CONF_ROOM_TYPE` → five behaviour tables
A room_type value is not "just a label" — it is a key into five tables, each with its own default for
an absent key. Adding a new room_type value silently falls through **all five** to defaults:

| Table | Definition | Default when key absent |
|---|---|---|
| `ROOM_TYPE_TIMEOUTS` | `const.py:1171-1181` | `DEFAULT_OCCUPANCY_TIMEOUT` 300s (`const.py:1132`); seeded at create `config_flow.py:1371-1374` |
| `ROOM_TYPE_FAILSAFE_DURATIONS` | `const.py:1196-1199` | 4h (`coordinator.py:696`) |
| `ROOM_TYPE_RECHECK_FACTOR` | `const.py:765-768` | 1.0 (`presence_fan_recheck.py:1100-1102`) |
| `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` | `const.py:1207-1210` | False (`coordinator.py:710`) |
| `ROOM_TYPE_FEATURE_DEFAULTS` | `const.py:1232-1245` | no seed (`config_flow.py:1449-1450`) |

**Coincidental equality (Bug Class #63):** `utility` and `garage` both map to 600 in `ROOM_TYPE_TIMEOUTS`
(`const.py:1177`). They are equal by config accident, not by concept — a discriminating change to one
must not assume the other follows.

### `CONF_ROOM_IS_GUEST_ROOM` (property, room)
- **Producer:** the flag itself; the guest-detection path is additionally gated by
  `PresenceGuestDetectionEnabledSwitch` (`switch.py:3621`).
- **Consumers:** the **flag** is read at `presence.py:4879` (trust decision). `presence.py:5741` and
  `:6321` consume the **gate RESULT**, not the flag directly — do not mistake them for flag readers.
- **Blast radius:** GUEST-mode arming. FP-sensitive (see memory `guest_mode_false_positive_backlog`).
  Do not alter these read patterns without the Tier-2-DB guest-FP framing.

### `CONF_WET_ROOM` (property, room)
- **Producer:** the flag; **seeded true for bathrooms at create time** (`const.py:1234` via
  `config_flow.py:1449`).
- **Consumers (complete, repo-wide):** `automation.py:2522` (read), `:2528` (sleep-policy fan
  exemption), `:2632` (presence-runtime arming). No others.

### `CONF_SHARED_SPACE` (property, room)
- **Consumers:** `automation.py:3150` accessor (callers `:3172`, `:3213`) — auto-off policy;
  `aggregation.py:1508` alert thresholds; `aggregation.py:1211` display.

### `CONF_ZONE_IS_OUTDOOR` (property, **zone**) — TWO coercion sites
This flag is coerced into a `room_type == "outdoor"` string at **two** places. Conflating them is the
CRITICAL a plan-review caught:
- **Display only:** `safety.py:428` inside `evaluate_zone_chip()`, behind
  `aggregation.ZoneSafetyAlertSensor` (`aggregation.py:4570`). Cosmetic.
- **Load-bearing:** `safety.py:1319-1323` in the safety coordinator's sensor discovery — writes
  `self._sensor_room_types[eid] = "outdoor"`, consumed by:
  - `safety.py:2076` — **hard early-return suppressing ALL humidity hazards** (real NM pages),
  - `safety.py:2146` — swing-trigger gate,
  - `safety.py:707/766/799` — rate-detector `exclude_room_types`.
  This coercion was **built deliberately by the NM overhaul (Cycle A: A4 / fix-up H1 / B-HIGH-1)** to
  stop outdoor humidity sensors paging — see the comment at `safety.py:1301-1307`. **The
  `room_type=="outdoor"` code path is dead BY DESIGN; that is a feature, not debt.** Removing the
  coercion resumes outdoor humidity NM pages.
- **Also:** `presence.py:5661` AWAY-veto exclusion.

---

## Dead-but-load-bearing (KEEP + DOCUMENT — never delete)

- **`basement` humidity bands** (`safety.py:214`, values `{low 65, medium 75, high 85, window 2.0h}`):
  unreachable — no `ROOM_TYPE_BASEMENT` const, absent from both dropdowns (`config_flow.py:1377`,
  `:10374`), no producer. **Not neutral to wire:** activating it turns on `safety.py:2082` (a ladder
  with no CM-knob override — basement is *more* alert-prone than a tuned `normal` room), `:2146` (swing
  disabled), and critically `:2209` — a **LOW-severity NM page at 65% RH** where a normal room logs
  silently. Wiring basement is a deliberate alerting decision, tracked as parked D2 of
  ROOM-CLASSIFICATION-CONSISTENCY-1.
- **`_humidity_table_key` "outdoor" return** (`safety.py:286-287`): unreachable because
  `resolve_safety_bands` early-returns on `rt=="outdoor"` at `:324`. Semantically load-bearing; keep.

---

## Infrastructure: enum vs switch — the reload window

`ROOM_TYPE_INFRASTRUCTURE` and the live `switch.infrastructure` are two representations of one property,
and the "switch is runtime authority" story has a caveat:
- **Producer of `_infrastructure_room`:** `coordinator.py:336` — a **hardcoded `"infrastructure"` string
  comparison** against room_type (not the enum symbol), re-derived on **every coordinator construction**.
- The switch (`switch.py:5107`) re-asserts its restored state only **after the entity is added**
  (`switch.py:5130-5137`).
- **Therefore:** there is a reload window in which the **enum (via coordinator.py:336), not the switch,**
  is authority. A change to one representation must account for the other during reload.
- **Consumer:** energy exclusion aggregates infrastructure rooms out (`aggregation.py:3522+`).

---

## Rules for changing a classification consumer

1. **Grep every consumer first — the count is a hypothesis until verified.** The `CONF_ZONE_IS_OUTDOOR`
   surface looked like one coercion site and was two; one of them pages NM.
2. **Display vs trust:** separate cosmetic chip helpers (`evaluate_zone_chip`, aggregation display) from
   trust decisions (safety hazard emission, presence gating). Moving a trust read is Tier-2-DB minimum.
3. **A new `room_type` value is never "just an enum member"** — decide its row in all five tables.
4. **Do not "clean up" a dead path without reading why it is dead.** The outdoor coercion and the
   basement bands are dead on purpose / for want of a consumer, not by neglect.

# PLANNING — Room classification consistency, Option A (ROOM-CLASSIFICATION-CONSISTENCY-1)

**Card:** ROOM-CLASSIFICATION-CONSISTENCY-1 · **Date:** 2026-09-14 · **Status:** operator-approved (Option A), plan-review pending
**Basis (read-only audit):** `docs/planning/AUDIT_room_classification_consistency.md`
**Tier:** 2-DB (three framing-disjoint reviews). Cross-coordinator: presence, safety, energy, security, automation.
**Operator direction:** "Option A but well documented."

Option A is the **low-churn** choice: keep every consumer's read pattern exactly as it is today,
and instead make the existing scattered classification surfaces *coherent and complete* through
documentation + two small orphan-wiring fixes. Option B (unify everything into one
`CONF_ROOM_CLASSES` multi-select) is explicitly REJECTED here — it rewrites every consumer across
five coordinators for low functional gain, and is parked with the revival trigger "a 6th class is
added or the flags start conflicting."

---

## Institutional context verified

Producer/consumer/blast-radius for all six surfaces is enumerated in
`AUDIT_room_classification_consistency.md` (grep-cited). Summary of what Option A touches:

| Surface | Today | Option A action | Consumers that must stay byte-identical |
|---|---|---|---|
| `CONF_ROOM_IS_GUEST_ROOM` | bool/room, const.py:386 | DOCUMENT only | presence GUEST gate presence.py:5741/:6321 — **do not touch** (FP-sensitive) |
| `CONF_WET_ROOM` | bool/room, const.py:1028 (+bathroom seed const.py:1234) | DOCUMENT the create-time seed cascade | automation.py:2522/2528/2632 |
| `ROOM_TYPE_UTILITY` | enum const.py:426 | DOCUMENT as near-vestigial (1 timeout row) | ROOM_TYPE_TIMEOUTS[utility]=600 |
| `ROOM_TYPE_INFRASTRUCTURE` | enum const.py:429 + live switch.infrastructure (switch.py:5107) | DOCUMENT switch = runtime authority, enum = seed default | energy exclusion aggregation.py:3522+; ROOM_TYPE_TIMEOUTS |
| `CONF_SHARED_SPACE` | bool/room, const.py:74 | DOCUMENT only | automation.py:3150 auto-off; aggregation.py:1508 alert thresholds |
| `CONF_ZONE_IS_OUTDOOR` | bool/zone, const.py:72 | **WIRE** (see D2) — make it the canonical outdoor producer | presence AWAY veto presence.py:5661; safety.py:428 humidity bands |
| `basement` (room_type key) | UNREACHABLE key in safety.py:214/:284 | **WIRE** (see D2) — add the enum member + dropdown | safety humidity bands |

**Memory bodies consulted:** `guest_mode_false_positive_backlog` (why the GUEST gate is untouchable),
`house_zones_vs_hvac_zones` (zone-vs-room scope). **Design doc:** none owns this cross-cut; the audit
is the authority.

---

## The falsifiable invariant

**Option A changes NO runtime behaviour for any already-configured room or zone.** Every consumer
read must return the same value before and after, for every existing config. The ONLY intended
behaviour deltas are: (1) a room explicitly typed `basement` now gets basement humidity bands
instead of falling through to the generic default; (2) an `outdoor` zone's humidity bands are
sourced through an explicit passthrough rather than the string-coercion at safety.py:428 — same
resulting band, cleaner path. Anything else moving is a regression.

---

## Deliverables

### D1 — Documentation: the "room-class attributes" model (the bulk of Option A)
A single canonical doc — `docs/architecture/ROOM_CLASSIFICATION.md` — that states, per surface:
its axis (FUNCTION `CONF_ROOM_TYPE` vs LOAD-BEARING PROPERTY flag), its scope (room vs zone), its
ONE producer, its consumers with file:line and trust-vs-display, and its blast radius. Plus the
three invariants:
1. **One producer per flag.** Call out the one dual-representation explicitly: `infrastructure`'s
   runtime authority is `switch.infrastructure`; the `ROOM_TYPE_INFRASTRUCTURE` enum only *seeds*
   the switch default. This is documented, NOT changed (changing it risks the RestoreEntity override).
2. **Explicit scope.** `CONF_ZONE_IS_OUTDOOR` is zone-scoped; every other flag is room-scoped.
3. **The two orphans are wired, not left as latent keys** (D2/D3).
Acceptance: **Verify** the doc lists all 6 surfaces with producer+consumers+blast-radius; **Verify**
it names the infra enum-vs-switch authority explicitly.

### D2 — Wire the `basement` orphan (KEEP+WIRE)
`safety.py:214/:284` key humidity bands on `"basement"`, but there is no `ROOM_TYPE_BASEMENT`
const, no dropdown option, no producer — so no room can ever *be* a basement and the bands are
dead. Add `ROOM_TYPE_BASEMENT` to `const.py` and the dropdown in `config_flow.py` (create + options).
- **Numbers-get-knobs:** none — this is an enum member, not a threshold.
- Acceptance: **Test** a room typed `basement` resolves the basement humidity band (not generic);
  **Test** the dropdown offers `basement`; **Verify** no existing room's band changes (nothing was
  typed basement before, because it was unselectable).

### D3 — Make `CONF_ZONE_IS_OUTDOOR` the canonical outdoor producer (retire the coercion)
Today `safety.py:428` coerces `room_type = "outdoor" if zone_is_outdoor`, inventing a room-type
string from a zone flag. Replace the string-coercion with an explicit `is_outdoor` passthrough into
`resolve_safety_bands` so the outdoor humidity band is selected by the boolean, not a magic string.
- **HARD constraint:** the resulting band must be **byte-identical** to today for every outdoor
  zone — this is a plumbing cleanup, not a band change. Prove it with a before/after table over the
  live zones.
- Also add `ROOM_TYPE_OUTDOOR` as a real enum member + dropdown option (so a *room* can be typed
  outdoor for the rare standalone case), but the ZONE flag remains the primary producer.
- Acceptance: **Test** an outdoor zone resolves the same humidity band before and after; **Test**
  the AWAY-veto exclusion (presence.py:5661) is untouched; **Mutation** — neuter the passthrough
  and a specific outdoor-band test must go red.

### D4 — Regression fence (the whole point of Option A being low-churn)
A test that asserts the invariant above: for a representative set of already-configured rooms/zones,
every classification-consumer read (GUEST gate armed?, wet-room fan exemption?, infra energy
exclusion?, shared-space auto-off?, outdoor AWAY-veto exclusion?, humidity band) returns the SAME
value pre- and post-change. This is the guard that Option A didn't silently move a consumer.

---

## Non-goals (explicit)
- **NOT** unifying the flags into one representation (that is Option B, parked).
- **NOT** touching the GUEST gate or AWAY veto read patterns (FP-sensitive; documented only).
- **NOT** changing the infrastructure enum↔switch duality (documented as-is; the switch stays authority).
- **NOT** deleting `utility` or any surface (dead-but-useful = KEEP+DOCUMENT).

## Plan-review checklist (Tier 2-DB, before build)
- Re-grep every consumer independently (the audit's list is a hypothesis).
- Confirm the `basement`/`outdoor` band values D2/D3 will select, against safety.py's actual tables.
- Confirm no options-flow migration is needed (adding enum members is additive; existing configs
  keep their current room_type).
- Confirm D3's passthrough is byte-identical on the no-outdoor-zone path.

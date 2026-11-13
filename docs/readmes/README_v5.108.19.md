# v5.108.19 — House-state step 1a: one arrival rule, residents-home producer, ARRIVING severity

Card HOUSE-STATE-FIRST-PRINCIPLES-1 (step 1a),
which folds in EXTERIOR-PERSON-SEVERITY-ARRIVING-BODY-ONLY-1 and EXTERIOR-PERSONS-HOME-ALWAYS-ZERO-1. Plan
`docs/planning/PLANNING_house_state_axes_step1.md` rev 3, Part A. Tier 3. Part B (vacation overlay) is not in this
release (HOUSE-STATE-VACATION-OVERLAY-1B).

## What changes

**Residency producer (new, display and severity only).** Presence records every resident's raw `person.*` home edge:
one `person_arrival` per `not_home | zone | unknown | unavailable -> home` edge and one `person_departure` per
`home -> not_home | zone` edge, each as a `memory_episodes` row. An arrival is `counted` by the same rule the garage
lockout uses (one shared function, `arrival_edges.counted_return`). New sensor
`sensor.ura_presence_coordinator_residents_home`: residents whose trusted state is home, minus anyone whose
phone-left-behind sensor is on. The house-state sensor gains `residents_home` and `occupancy` attributes.
`binary_sensor.ura_house_occupied` now reads the same `get_house_occupancy()` getter (same result as before).
Residents are the person coordinator's `tracked_persons`, which the live install stores as display names
(`'Oji Udezue'`); each is mapped to its `person.*` id by the person coordinator's own rule
(`person_coordinator.tracked_person_entity_id`). A resident's arrival stops counting as recent evidence once the same
person has a later departure. Each edge writes its own row: the 60 s per-type window in `log_memory_episode` is skipped
for these two types (`window_dedup=False`); a replay of the same edge is still deduplicated on its `source_ref`.

**Garage lockout: house edges no longer release on their own.** While a lockout episode is open, a HOME_* or ARRIVING
house-state edge releases only when it was an operator override (`override_set` or `override_clear`). Every other such
edge is logged `house_edge_ignored` and changes nothing. Real arrivals still release through the resident's own person
edge, WAKING still ends a sleep episode, the morning backstop still ends sleep-like episodes, and VACATION ends at a
resident arrival or by the operator. The ARRIVING "taint" from v5.108.18 is retired; its stored value loads as the new
page flag.

Behaviour changes versus v5.108.18:
- A default-trigger HOME_* edge in an episode that never saw ARRIVING used to release. It is now ignored.
- An `override_clear` edge now releases (before, only `override_set` did).
- With the guest stay rule switched OFF, a morning GUEST -> HOME_* exit with a guest-night lock is released by the
  backstop, not at the exit.
- VACATION selected while the family is home: the lock stays engaged through the override-clearing HOME_* edge until
  the night's SLEEP (then WAKING / backstop) or an operator action.
- The boot recheck no longer releases a `boot_unknown` lock found in an awake house; the backstop does (for an evening
  restart, the next morning).
- An operator override to ARRIVING with no open episode no longer unlocks a hand-locked lockout.
- The boot gap page also fires when the episode saw an empty house, not only when the restored house read away or
  arriving.
- A restart that finds a VACATION lock while the house reads neither vacation nor sleep marks the episode as having
  seen an empty house, so the boot gap page fires (with a resident home) instead of a silent stay. Vacation has no
  backstop (review D LOW-2).

Known and accepted (review D LOW-1, plan delta L1, unchanged): a lockout locked by hand while no episode is open has no
persisted reason, so a restart rebuilds it as `boot_unknown` (sleep-like) and the daytime backstop releases it. The
trigger is `backstop`, outside the house-edge rule.

**Exterior-person severity.**
- While the house reads ARRIVING, an exterior-person alert is CRITICAL unless a resident is home or made a counted,
  fresh-source arrival in the last 300 s outside the boot window. Before, it was always MEDIUM. Knob
  `EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT` (True; False = MEDIUM).
- `persons_home` (HOME_DAY / HOME_EVENING / GUEST egress rows) had always been 0 in production because the lookup could
  not reach presence. It now reads presence correctly, but feeds the residents-home count only with
  `EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY` True. The switch ships False, so paging is unchanged (operator
  decision Q4).
- The unused flat severity table is deleted.

## Knobs (all rung 1, module constants)

`RESIDENT_RETURN_MIN_AWAY_MIN` 15 (`GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` aliases it), `RESIDENT_RETURN_BOOT_WINDOW_S` 600
(`GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S` aliases it), `RESIDENCY_EVENT_LOG_PERSIST` True, `RESIDENCY_RECENT_EVENTS` 32,
`LOCK_HOUSE_RELEASE_OPERATOR_TRIGGERS` {override_set, override_clear}, `EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT` True,
`EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY` False, `EXTERIOR_SEVERITY_RECENT_ARRIVAL_S` 300. No config-flow field
and no Number entity.

## Live validation (to fill after restart)

- **L1:** within 24 h, `memory_episodes` `person_arrival` / `person_departure` rows match the recorder's resident
  `-> home` / `home ->` edges, one row per edge (each miss explained; no 60 s window applies to these types). Oji
  (two-word display name) must have rows.
- **L2:** the weekly writer-health check shows both types and does not page.
- **L3:** `sensor.ura_presence_coordinator_residents_home` equals the residents reading home minus any
  phone-left-behind `on`.
- **L4:** with the lockout switch on, `sensor.ura_security_coordinator_security_armed_state` carries
  `lock_regime_episode_saw_empty` and `lock_regime_house_edges_ignored` and no `lock_regime_arriving_*` keys; the first
  body-only ARRIVING in an episode shows `last_action.action == "house_edge_ignored"`; `decision_log` has 0
  `lock_regime_release` rows with a `house_state:*` trigger other than waking / operator.
- **L6:** 7 days after deploy, from the `ARRIVING exterior-person severity` INFO lines: every MEDIUM has a resident
  home or a counted arrival within the window.

## Rollback

The store migration is one-way (review B-L2). This release stops writing `garage_arrival_taint`; a lockout episode
open at the time of a rollback to v5.108.18 loads that taint as False, so an ARRIVING-then-HOME_* edge in that episode
releases again (the older, laxer rule). New episodes after the rollback behave exactly as v5.108.18. The new
`garage_episode_saw_empty` key is ignored by v5.108.18. Residency `memory_episodes` rows stay in the DB and are inert.

## Plan completion

- D0 (read-only probe) was not run by the build (the builder does not touch HA). `EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT`
  ships True and `EXTERIOR_SEVERITY_RECENT_ARRIVAL_S` ships 300 (the plan's default with fewer than 5 samples). The D0
  go/no-go gate (added pages <= 3 per week) is still owed before deploy.
- D1, D2, D4, D5, D6 built. Part B (vacation overlay) is out of scope.

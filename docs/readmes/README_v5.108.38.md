# URA v5.108.38: swept-lock freshness check + lock_unverified page; identity vetoes stop failing open

Cards: SECURITY-LOCK-STALE-STATE-1, LAYER-LEAK-CLEANUP-1 (L4 minimal). Ships in the same restart as v5.108.37.

## 1. Swept-lock freshness (SECURITY-LOCK-STALE-STATE-1)

Why: the garage hallway Kwikset (zwave_js node 10, re-included 11-14) stopped reporting 2026-11-16 07:37 CST; for ~55 h
HA held a restored `locked` while the door was physically unlocked (operator: "I'm finding it open often" / "I just
went through that door and it wa unlocked"). The sweep relocked only locks that READ unlocked, trusted `locked` with no
age check, and the only notice was a once-a-day digest "offline" after the node was finally marked dead. Nothing paged.
Evidence: `docs/planning/AUDIT_lock_report_staleness_2026_11_18.md`, D0 `AUDIT_lock_freshness_d0_2026_11_18.md`.
Plan: `docs/planning/PLANNING_security_lock_freshness.md`. Reviews A+G SHIP, B FIX-REQUIRED (night-page drop), C
FIX-REQUIRED (18 test gaps), fix pass e8b71e74d, manager review B2 SHIP, common-mode fix cdce7c21b; orchestrator
mutation (unverified gate disabled) -> 5 RED.

- **Freshness** (`security_lock_freshness.py`): newest of the lock's real report stamps and its zwave node `last_seen`
  sibling (device registry, disabled siblings included so a disabled signal is reported as disabled). Boot-grace stamps
  and unavailable->state cache restores never count as a report. A `lock_freshness` Store keeps the last real report
  across restarts.
- **Classes:** zwave locks with an enabled `last_seen`: stale after N = 12 h (Number). Locks without one (the Philips
  master lock; the garage lock while its `last_seen` is disabled): dead / unavailable page only.
- **Sweep gate (one site, security.py):** a stale `unlocked` lock still gets the existing `lock.lock` and retry cap AND
  pages; a stale `locked` lock is no longer counted compliant: one non-blocking zwave refresh + a page. INV-2: the
  check never adds a new lock command; all eight lock command sites are unchanged.
- **Pages:** HIGH `lock_unverified`: stale, dead (20-min debounce), "back online, not verified" after a cache restore,
  re-paged every R = 6 h (Number) until a real report; all swept locks down together = one page naming a Z-Wave/HA event
  (each down lock is also marked so its restore stays unverified). A page counts as sent only when NM reports it
  delivered, so a quiet-hours drop retries. One notice per incident (the old offline digest notice is skipped while a
  dead page owns the lock). D4: a swept zwave lock whose `last_seen` sensor is disabled pages "freshness signal disabled".
- **Shared action manager:** NotificationAction may carry `data["on_notify_result"]` (delivery callback) and service
  actions `data["blocking"]=False`; no existing action sets either key (review B2).
- N = 0 turns the whole check off (byte-identical sweep).

**Operator decisions:** (1) add `lock_unverified` to the night-bypass hazards (CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS) so a
night page wakes you; without it, a night page is delivered when quiet hours end. (2) Enable
`sensor.garage_hallway_doorlock_zwave_garagehallway_last_seen` (reloads Z-Wave JS once) so the garage lock gets the 12 h
stale page; until then it is dead-page-only and D4 pages that its signal is disabled.

## 2. Identity vetoes stop failing open (LAYER-LEAK-CLEANUP-1 L4)

Plan `docs/planning/PLANNING_layer_leak_cleanup.md` (re-cut 11-17 under "Only proven code should supersede correct
code"). Five identity vetoes (camera_census x4, transit_validator `_resolve_egress_face_identity_ex`) built
`person.<slug>` inline; for a person whose entity id differs from the slug (a second install, display-name people) the
veto failed open. New `person_ids.person_entity_for_slug`: exact `person.<slug>` first (unchanged, byte-identical for
this house); on a miss only, the one HA person entity whose id or configured name matches; zero or several matches keep
today's answer. Counted (and logged) as a last-resort fallback. Guard allowlist 259 -> 254. Review A SHIP.

## Live checks after install

1. 50/50 entries loaded; no URA errors; `lock_freshness` Store created.
2. Sweep sensor attributes carry `stale`, `unverified`, `freshness_age_h`; front lock fresh (last_seen ticks hourly).
3. Garage lock (dead today): one `lock_unverified` dead page after the debounce and the D4 "signal disabled" page; no
   duplicate offline digest notice; no new lock command to it.
4. Identity: `person_entity_fallback_*` counters present; this house's exact ids hit, fallback hits 0.

## Validated (to be written back after install)

## Not done (accounted)

- D5 (3 h door-activity tightening): parked, no registry link from a lock to its door evidence.
- L4 remainder and other leak groups: parked with triggers (plan).

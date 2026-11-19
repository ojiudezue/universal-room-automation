# PLANNING: swept-lock freshness check and dead-lock page

Card: SECURITY-LOCK-STALE-STATE-1 (thread security). Source audit: `docs/planning/AUDIT_lock_report_staleness_2026_11_18.md`.
Operator words: "Is lock sweep working? ... I'm finding it open often" / "I just went through that door and it wa unlocked".
Operator rule 2026-11-17: "We should not rebuild tier 3 that are hardened and work... Only proven code should supersede correct code."
So this plan ADDS a freshness gate and a page in front of the existing sweep branches. It does not restructure `_evaluate_lock_check`, the retry cap, the exclusion list, or `security_lock_regime.py`.

Not HVAC. Not presence in the occupancy sense; the only presence-adjacent input (door/egress evidence, an F3 crossing used purely as "someone used this door") is deferred to D5 and gated on a registry/config mapping, so the presence and identity manuals were not required reading for D1-D4. D5's build must read `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` first.

## 0. Config-first result

- One operator action is required and is not code: the garage lock's `sensor.garage_hallway_doorlock_zwave_garagehallway_last_seen` exists in the entity registry with `disabled_by: integration` (default-disabled by zwave_js). Node 3's `sensor.node_3_last_seen` is enabled. Enabling it (Settings > Entities) gives the garage lock the same freshness signal as the front lock. This alone does not fix the defect (the sweep never reads any freshness signal), so code is still needed.
- No existing knob makes the sweep age-check a `locked` state. `CONF_LOCK_UNAVAILABLE_DEDUP_S` (const.py:5992) only spaces the offline notice; it is RAM-backed (security.py:623) and MEDIUM, which queues to the digest.

## 1. Institutional context verified

Code read (verified 2026-11-18 on develop 7c4c4313e):
- `security.py:1816` `_evaluate_lock_check`. Lock loop 1836-1866: None/unavailable/unknown -> `unavailable` list + `continue` (1838-1842); `locked` -> clears retry episode, no action, no age check (1850-1851); `unlocked` -> `lock.lock` `ServiceCallAction` (1852-1866). Garage covers 1868-1891 (same shape, out of scope). Offline notice 1893-1933: `NotificationAction`, `Severity.MEDIUM`, `channels=["security"]`, dedup via `self._lock_unavailable_last_notified` (RAM dict, security.py:623).
- Sweep timer: `async_track_time_interval` at security.py:783, `CONF_SECURITY_LOCK_CHECK_INTERVAL` (const.py:4272); sweep dispatched from security.py:899.
- Retry cap: `SECURITY_LOCK_RETRY_CAP = 3` const.py:4432, `_lock_retry_allows` security.py ~1780-1815. Unchanged.
- Existing persistence pattern: `Store(self.hass, 1, f"{DOMAIN}.lock_regime_residents")` security.py:721.
- Lock regime `security_lock_regime.py`: `_UNREAL_STATES` (~107), skips unavailable lockout entities (~2046-2052). No staleness handling (grep for stale/last_reported finds only person-source staleness). Unchanged.

Prior-art scan, REUSE-or-BUILD per piece:

| Piece | Verdict | Evidence |
|---|---|---|
| State age from a stamp | REUSE pattern of `_state_age_s` energy_battery.py:90 (last_reported, CF-8 naive-stamp -> None). Not importable cleanly from security (energy module); copy the 10-line semantics into a security helper or move to a shared util. Builder picks move-to-util only if no import cycle. | grep `last_reported` across domain_coordinators |
| Stale-signal paging primitive | NOT REUSED for the page. `_stuck_signal_nm.fire_stuck_signal` (`_stuck_signal_nm.py:173`) latches per calendar day in RAM (`_LATCHES`, :47) and goes under a stuck_signal coordinator id; the card requires persistent dedup and a re-page interval. Reuse its lesson: MEDIUM reaches no channel under live NM config (docstring :186-189), so a page must be HIGH. | read _stuck_signal_nm.py:1-260 |
| Page transport | REUSE `NotificationAction` (base.py ~130-136: `severity`, `channels`, `hazard_type`) exactly as the offline notice already does at security.py:1922. | |
| Quiet hours | REUSE NM DND logic (notification_manager.py:1685-1740): life-safety hazards always bypass; HIGH bypasses only for recipients whose bypass set includes it. Promotion is an existing operator knob, `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` (const.py:4990, additive-only). | |
| Freshness source, zwave | REUSE the device's own zwave_js `last_seen` sensor, resolved by entity registry: same `device_id` as the lock, `platform == "zwave_js"`, `translation_key == "last_seen"` (verified in core.entity_registry for both nodes). Never by name. | registry dump |
| Wake action, zwave | REUSE HA service `zwave_js.refresh_value` (entity_id = the lock). Ping button (`translation_key == "ping"`, same device) as an alternative; plan picks refresh_value only (one action). | registry |
| Freshness source, non-zwave (Philips `lock.master_bedroom_lock`) | Registry shows only lock + `binary_sensor.master_bedroom_lock_door` + `sensor.master_bedroom_lock_battery` (platform philips_home_access). No last_seen. Freshness = max(last_reported) over the lock and its same-device siblings. Whether philips_home_access polls (so last_reported advances while silent) is UNVERIFIED; D0 measures it. It is in `security_lock_sweep_exclude`, so only D3 (dead page) applies to it today. | registry dump |
| Wake action, non-zwave | REUSE `homeassistant.update_entity`. | |
| Zwave node_status | Read but not trusted as fresh: card records node_status stayed `alive` through the silence (it went `dead` only after the 14:51 ping). `dead` is treated as dead (D3). | card why + audit Q1 |
| Restart-restore detection | NEW: persisted per-lock "last real report" (below). Nothing existing distinguishes a boot-time stamp from a device report. | grep restored/boot in security.py |
| New Store | NEW `f"{DOMAIN}.lock_freshness"`, same pattern as :721. Not the URA SQLite DB (no schema change, no write queue). | |

Prior plans/cards consulted: SECURITY-LOCK-SWEEP-RETRY-CAP-1 (done v5.108.6, episode/cap logic stays), LOCK-BOOT-RECHECK-ENGAGE-1 (shipped_organic, regime boot recheck at +120 s; unaffected), FRONT-DOOR-LOCK-OFFLINE-1, `AUDIT_security_sweep_and_mopup.md`, `PLANNING_stuck_signal_watchdog.md` (by docstring reference).

## 2. Falsifiable invariants

- **INV-1:** a swept lock whose freshness age exceeds `N` (or that is unavailable/unknown/node-dead) never produces a "compliant, no action" outcome in the sweep without a HIGH page having been dispatched (or being dedup-held by a persisted record younger than the re-page interval) for that lock.
- **INV-2:** the freshness check never adds a new lock command. The existing sweep `lock.lock` on an `unlocked` lock, stale or not, stays as it is, retry cap included.
- **INV-3:** a timestamp produced at HA boot (within `boot_grace` of the coordinator's start) never advances a lock's persisted last-real-report, so a restart cannot make a silent lock look fresh; and no freshness/dead page is emitted before `boot_grace` has elapsed.
- **INV-4 (no-op path):** a fresh, available lock produces byte-identical sweep actions and compliance to today.

D's job: break INV-1 with a legal config (for example a lock with no last_seen sibling and an integration that never updates last_reported, or a restart every 11 h).

## 3. Producer and consumer checks

Producer: `freshness_ts(lock) = max(real_report_ts persisted, live stamps that are real)`, where live stamps = lock `last_reported`, lock `last_changed`, and for zwave the same-device `last_seen` sensor's state value (a timestamp, read as a value, not its own state stamps). A live stamp is "real" only if it is later than `boot_ts + boot_grace` AND it is not the stamp of a recovery from unavailable/unknown to a lock state. That recovery is a cache restore, per D0 (11-16 09:10, 11-17 15:06). A recovery counts as a report only if a later stamp or a `last_seen` advance follows it. The staleness check (D2) applies only to locks with an enabled `last_seen`. Locks without one get the D3 dead page only. Each sweep writes back the new max to the Store (only when it advanced; one Store save per sweep at most, delayed save).
Dependency health measured in the audit: node 3 last_seen p50 0.1 h, p90 1.1 h, max 17.5 h over 8 d; lock-row gaps front max 25.9 h, master 31.9 h (overnight, restart-polluted); `last_reported` sporadic (front 26/44 rows null). Unmeasured: node 10 last_seen behaviour while silent (entity disabled), Philips poll cadence. D0 covers both.
Fire check: the offline notice fired once in the incident (11-18 21:41 UTC, digest, undelivered). The "stale" producer is new: it gets a fire counter on the sweep sensor (D4) and is expected to fire zero times in a healthy week; one fire per real silence.
Consumers: the sweep's own branch (trust decision, security.py:1850/1852), the page (NM), the sweep sensor attributes (display). Nothing else reads lock freshness; the lock regime keeps its own `_UNREAL_STATES` handling (not wired to freshness: non-goal, see 7).

## 4. Emission / decision sites

There are eight lock command sites (plan review 2026-11-18):

| Site | Command | Stale gate? |
|---|---|---|
| security.py:1862 | sweep `lock.lock` | No. It keeps running, and a stale lock also pages |
| security.py:1754 | lockdown lock | No |
| security.py:2337 | hazard egress unlock | No (life-safety) |
| security_lock_regime.py:899 | unlock | No (resident-driven) |
| security_lock_regime.py:2239 | unlock | No |
| security_lock_regime.py:2976 | unlock | No |
| security_lock_regime.py:2436 | engage | No |
| security_lock_regime.py:2830 | away-lock | No |

Ruling: none of them gets the stale gate. Sending a command to a silent lock does no harm and shows when the lock is dead. The unlocks are life-safety or resident-driven. The freshness check changes behaviour only for a stale `locked` lock. The builder re-greps `lock.lock|lock.unlock` and lists any site that is not in this table.

## 5. Deliverables

### D0: measurement probe, DONE (`AUDIT_lock_freshness_d0_2026_11_18.md`)
Findings that set the design:
- **Zwave lock with `last_seen` enabled:** node 3's `last_seen` has ticked about hourly since 11-13, with 0 false pages at 12 h. N = 12 h stands.
- **Philips (`lock.master_bedroom_lock`):** it has no `last_seen`, and `last_reported` does not advance on its poll. Real gaps run up to 37.2 h, so N = 36 h would false-page it. Philips (and any lock without `last_seen`) gets the dead/unavailable page only, never a staleness page.
- **Zwave lock with `last_seen` disabled (the garage today):** it falls into the no-`last_seen` class, so dead/unavailable page only. Consequence: the 11-16..11-18 silence would NOT have paged before the dead page at about 11-18 15:54. This supersedes the plan review's ~12 h simulation, which assumed lock stamps were usable at N = 12 h. The fix is the operator enabling the sensor (§9), and D4 pages "freshness signal disabled" so the gap is visible.
- **Cache restores:** an unavailable-to-state recovery (11-16 09:10, 11-17 15:06) is a zwave_js cache restore, not a report.
- **Common-mode blips:** all three locks showed 5-15 min unavailable blips together on 11-16 and 11-17.

### D1: freshness helper + persisted last-real-report
`_lock_freshness(lock_id) -> (age_s | None, source)`. Same-device siblings are resolved with `include_disabled_entities=True`, so a disabled `last_seen` sensor is reported as `disabled` (D4), not as missing. A sibling whose state is None or unavailable counts as no signal: it gives neither age 0 nor stale. Siblings are resolved from the registry once per sweep (re-resolved when the registry changes is a non-goal; resolve each sweep, it is cheap). Store `{lock_id: {"real_report_ts", "paged_ts", "paged_kind"}}`, loaded at setup, saved delayed.
- **Test:** `test_freshness_uses_max_of_stamps`, `test_boot_stamp_not_real_report`, `test_last_seen_resolved_by_registry_not_name` (fixture with a misleadingly named sensor on another device must be ignored), `test_store_round_trip`.

### D2: stale gate in the sweep (lock loop only)
Inserted after the unavailable check and the exclusion check, before the `locked`/`unlocked` branches: if age > N (or age is None and no real report recorded for > N since boot+grace), then: compliance = `"stale"`, issue ONE `zwave_js.refresh_value` (zwave) or `homeassistant.update_entity` (other), add the lock to a new `stale` list and emit the page (D3 rules). Then:
- **Stale `locked`:** `continue`. No command is sent and the retry episode is untouched.
- **Stale `unlocked`:** falls through to the existing branch, so `lock.lock` and the retry cap run unchanged, and the lock is also paged.

The fresh path is unchanged.
- **Verify (discriminating):**
  - A `locked` fixture lock whose last real report was 13 h ago gets a page and a refresh, and no lock command.
  - The same lock reported 11 h ago gets no page. This rules out a gate that pages every locked lock.
  - A stale `unlocked` lock gets a page plus the existing `lock.lock`. This rules out a gate that suppresses the proven command.
- **Test:** `test_stale_locked_pages_and_refreshes`, `test_fresh_locked_byte_identical`, `test_stale_unlocked_pages_and_still_commanded`, `test_excluded_lock_not_stale_paged`, `test_none_unavailable_sibling_is_no_signal`.
- **Live:** with the garage lock's last_seen enabled and the lock healthy, `sensor.ura_security_coordinator_security_last_lock_sweep` shows `stale: []` and `lock_actions_sent` unchanged in shape.

### D3: dead/unavailable/stale page with persistent dedup
Severity HIGH, `channels=["security"]`, `hazard_type="lock_unverified"` (new token; operator can promote it with `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` for quiet-hours delivery). Message names the door (lock friendly name from the registry, not the entity id) and the age ("Garage hallway lock has not reported for 13 h; state unknown, check the door"). Applies to: stale swept locks (zwave with `last_seen` only), and any swept-or-excluded lock that is unavailable/unknown or whose node_status sibling reads `dead`. **Debounce:** a dead or unavailable page fires only after the condition has held for `SECURITY_LOCK_DEAD_DEBOUNCE_MIN` (D0 saw 5-15 min common-mode blips). **Common mode:** when every swept lock goes unavailable together, the per-lock pages are suppressed and one page says it is a Z-Wave or HA event, naming the locks. Dedup from the Store `paged_ts`; re-page after `R` while the condition holds; on the first real report after a page, clear the record and send one MEDIUM "reporting again" notice. The existing MEDIUM offline digest notice (1893-1933) stays as is (removing it is a non-goal).
- **Verify:** restart between page and re-page interval does not re-page (Store) and does not lose the page (record survives).
- **Test:** `test_unavailable_blip_under_debounce_no_page`, `test_all_locks_unavailable_single_common_mode_page`, `test_cache_restore_not_a_report`, `test_dead_lock_pages_high_persistent_dedup`, `test_repage_after_interval`, `test_clear_on_report`, `test_no_page_within_boot_grace`.
- **Live:** NM `notification_log` shows a HIGH, non-digest row for an unavailable swept lock within one sweep interval after boot_grace (the garage lock is unavailable today, so the first post-deploy sweep after grace is the live check; expect exactly one row, and none after a second restart inside R).

### D4: observability + zero-fire trip-wire
Sweep sensor gains `freshness_signal` per lock (`last_seen` / `disabled` / `none`), `stale`, `stale_pages_total`, `last_stale_page`. No anomaly trip-wire for zero fires (zero is the healthy outcome); instead the trip-wire is the inverse. When a swept zwave lock's `last_seen` sibling is disabled or missing, there is an AnomalyDetector row plus one HIGH page: "freshness signal disabled for <door>; staleness cannot be detected". That is how the 11-18 blind spot existed. It is deduped per lock in the D3 Store and re-pages after R.
- **Live:** before the operator enables node 10 last_seen, the anomaly names the garage lock; after, it clears.

### D5 (gated, likely parked): door-activity tightening to M
Only if a lock-to-evidence mapping can be resolved without names: an explicit per-lock config list of evidence entities (independent of the lock radio; the lock's own door binary_sensor shares the radio and does not count). The ELK zone for the garage hallway door is not provable from the registry, and egress camera rows have no door id. Marginal benefit over D2: the 11-18 incident pages at ~12 h with D2 once `last_seen` is enabled (versus 55 h today, never paged); M would cut that to ~3 h after the first crossing, at the cost of a new config field and a cross-coordinator read. The plan review's simulation showed the saved last-report time surviving restarts. D0 then showed that, without `last_seen`, the lock falls to the dead-page-only class, so the 12 h page depends on the sensor being enabled. Recommendation: PARK with revival trigger "a stale-lock page arrives more than 3 h after a door crossing the operator cares about, or a mapping becomes resolvable from config already present."

## 6. Knobs

| Knob | Default | Rung | Why / kill switch |
|---|---|---|---|
| `SECURITY_LOCK_STALE_HOURS` (N) | 12 | Number entity (operator tunes by observation) | Under node 3 p90 1.1 h with margin; D0 gate. 0 = freshness gate off (byte-identical to today). |
| `SECURITY_LOCK_DEAD_DEBOUNCE_MIN` | 20 | module const | Above the 5-15 min common-mode blips D0 measured. 0 = page on the first unavailable sweep. |
| `SECURITY_LOCK_DEAD_REPAGE_HOURS` (R) | 6 | Number entity | Re-page cadence while dead/stale. 0 = page once per episode. |
| `SECURITY_LOCK_BOOT_GRACE_S` | 600 | module const | Lets zwave_js interview/cache settle; boot stamps inside it are not reports. Review-gated. |
| `SECURITY_LOCK_ACTIVITY_STALE_HOURS` (M) | 3 | parked with D5 | Not built. |

## 7. Non-goals

No change to the retry cap, exclusion list, garage cover loop, lockdown, `security_lock_regime.py`, or the existing MEDIUM offline notice. No lock/unlock command ever added. No DB schema. No name-based resolution. No change to NM routing (promotion is the operator's existing knob). D5 not built.

## 8. Tier

Tier 2, elevated to the 3-framing Tier 2-DB review protocol: it changes a safety decision in the security sweep (regression-prone, and a persistence Store is added), but it is additive at one decision site, threads no value through many emission sites, and touches no shared primitive, so not Tier 3. Framings: A correctness and clock edges (boot grace, naive stamps, restart inside R); B lifecycle (Store load before first sweep, registry lookups, refresh_value failure must not raise); C per-site mutation (gate bypass, the never-command guard, the boot-stamp filter, the persistent dedup). One plan review before build.

## 9. Operator decisions

1. **Required before deploy: quiet hours.** The question is whether `lock_unverified` joins `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS`, which would make it bypass DND at night. Recommended default: promote it. An unverified lock at night is when the page matters most, and the dedup and R limit the volume. The coordinator will ask the operator.
   - **Live:** after the decision, `nm_extra_life_safety_hazards` in the options matches it. A stale or dead page during quiet hours is either delivered (promoted) or held (not promoted), as shown in `notification_log`.
2. Enable `sensor.garage_hallway_doorlock_zwave_garagehallway_last_seen`.
   Until it is enabled, the garage lock gets no staleness page (D0), only the dead page and the D4 "freshness signal disabled" page.

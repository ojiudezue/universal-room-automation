# AUDIT: NM no_channel_fired / delivered=2 (card NM-NO-CHANNEL-FIRED-1)

Probed 2026-11-13 01:50-02:10 CST. Read-only. Sources: notification_manager.py (NM), database.py, live URA DB via `ssh ha sqlite3 -readonly`, `.storage/core.config_entries`, HA REST states.

## Answer (lead)

**Confirmed: sub-threshold alerts (MEDIUM/LOW) reach nobody. Not delivered, not queued for digest, not shown on any surface.** `delivered=2` is not evidence of delivery. The cause is settings, and a settings change fixes it.

Cause: the single NM recipient has `delivery_pref=digest`, but every channel severity gate is HIGH or CRITICAL. For a MEDIUM/LOW alert the router returns an empty channel set, so (a) no immediate send, and (b) no digest-queue row is written (queue writes are also gated on `_router_allowed`). The only row left is the per-recipient audit sentinel (`message='[audit]'`), which the digest reader explicitly excludes.

## (1) Semantics (file:line)

- `no_channel_fired`: `notification_manager.py:2168`, `bucket_outcome = "accepted" if per_person_fired else "no_channel_fired"`, `delivered=1 if per_person_fired else 0` (:2170). Means: zero channels fired for this recipient on this notify. It is an audit row, `message='[audit]'`.
- `delivered=0`: digest-queue marker (`database.py:4926` pending reader; comment NM:358-362).
- `delivered=2`: set by `mark_digest_delivered` (`database.py:4958`): `UPDATE ... SET delivered=2 WHERE person_id=? AND delivered=0 AND severity IN ('LOW','MEDIUM')`. It is a queue-sweep marker. It sweeps `[audit]` sentinels too (docstring :4937-4945 says so deliberately). So `delivered=2` on a `no_channel_fired` row means only "a later digest flush ran and tidied the row". It says nothing about any message being sent.
- `-1` (NM_DELIVERED_FAILED, NM:363) is a failed immediate send; not involved here.

## (2) Does any later path deliver them? No.

- `get_pending_digest` (`database.py:4910-4930`) selects `delivered=0 AND severity IN (LOW,MEDIUM) AND message != '[audit]'`. Audit rows are excluded by design, so the sentinels never enter a digest body.
- DB fire check: `select ... from notification_log where message!='[audit]' and delivered in (0,2) and timestamp>='2026-10-01'` returns **zero rows**. Not one real LOW/MEDIUM item has been queued for digest since 10-01. In the window since 11-01, every non-audit row is `delivered=1` on companion (445), imessage (95), pushover (95), whatsapp (95), all HIGH/CRITICAL (perimeter, envoy, hvac_override, optimization, high_co2 HIGH).
- First `no_channel_fired` row: 2026-10-14 08:45 UTC, 1251 total. (Matrix/audit code arrived in f6e53a96, 2026-07-20.)
- The daily digest timer (`_setup_digest_timers` NM:5407, `_fire_digest` NM:5456) is registered for this person (pref=digest; 08:00 and 18:00 evening enabled). With nothing queued and no optimizer section it takes the heartbeat branch (NM:5478-5490, `NM_DIGEST_HEARTBEAT_ENABLED = True`, :268) and sends "URA Daily Summary ... All quiet — no items." via whatsapp/imessage (`digest_channels`). Consequence: the operator likely receives "all quiet" while MEDIUM alerts are being dropped. That is misleading. I could not confirm the digest sends actually landed: `_deliver_digest` writes no DB row and INFO logs aren't in `/api/error_log` (grep for "digest" empty). Unknown whether delivered; not proven either way.
- Even the Weekly Routine Digest (the "digest sender" the sweep saw) is itself a victim: notification_log ids 25135 (11-01) and 26218 (11-08) are `[audit]`, `no_channel_fired`, `delivered=2`; activity log says "LOW alert: Weekly Routine Digest via none" on 10-18, 10-25, 11-01, 11-08. It routes through `async_notify` at LOW, so it is dropped by the same gate. `routine_change_notification_mode=weekly_digest` therefore never delivers.
- No other surface reads these rows: `bucket_outcome` is referenced only in notification_manager.py and database.py (grep). No panel/dashboard consumer.
- Misleading health signals: `sensor.ura_notification_manager_notification_delivery_rate` = 100.0 and `..._notification_channel_status` = ok, `..._notification_diagnostics` = healthy (live 2026-11-13). They do not count dropped audit rows.

## (3) Config that causes it

From `.storage/core.config_entries`, Coordinator Manager entry 01KJEC3FYPYAGBQKZWC94CR8GR (secrets omitted):
- `nm_persons`: one person, `person.oji_udezue`, `nm_person_delivery_pref: "digest"`, `digest_channels: [whatsapp, imessage]`, no routing matrix, no hazard overrides.
- Channel gates: companion HIGH, pushover CRITICAL, whatsapp CRITICAL, imessage CRITICAL (all enabled); lights disabled; tts disabled (CRITICAL).
- Quiet hours: manual 22:00-07:00 plus `nm_quiet_use_house_state: true`. Not the cause: quiet-hours rows show up separately as `quiet_hours_suppressed` (13 perimeter rows) and MEDIUM suppressed only for immediate pref.
- Mechanism: no matrix, so `_route_for_recipient` takes layer D (NM:5105-5117, `_channel_qualifies` NM:5374-5401 = `severity >= threshold`). MEDIUM (and LOW) < HIGH, so empty set. NM:2045+ digest-queue writes need `"<chan>" in _router_allowed`, so none are written.
- CRITICAL/HIGH are forced immediate (NM:1919-1927), which is why perimeter/envoy/co2-HIGH do reach companion/etc.

Breakdown since 11-01 (no_channel_fired rows, all `[audit]`): stuck_signal MEDIUM 142 + LOW 46, energy circuit_anomaly MEDIUM 133, presence LOW 96, evse_fill_priority LOW 30, security MEDIUM 29, safety high_co2 MEDIUM 15, high_tvoc LOW 7, perimeter MEDIUM 6, hvac MEDIUM/LOW ~10; plus `delivered=0` leftovers (not yet swept) security 5, presence 4, stuck_signal 4, circuit_anomaly 3.

## (4) high_co2: any real hazard? No evidence of one.

- 15 MEDIUM rows (11-01 to 11-12) are 1500-1597 ppm, mostly Master Bathroom/Study A at 1500-1504: threshold-edge flapping (safety.py:189-191 MEDIUM=1500; hysteresis `CO2_CLEAR_OFFSET_PPM` safety.py:262 mentions the "1500-1502 flap"). That is a ventilation/stuffiness band, not a hazard.
- Two HIGH events, both Kitchen, 2026-11-05 18:49 and 19:30 CST (11-06 00:49 and 01:30 UTC), 2851 and 2681 ppm. These did deliver (companion, delivered=1, DB rows at 11-06T00:49:31 and 01:30:31). 2681-2851 ppm is well under the common 5000 ppm occupational limit (my general knowledge, not a repo citation) but above the URA HIGH rung 2500 (safety.py:191). Kitchen Apollo sensor `sensor.airquality_co_co2_pressure_apollo_wif_bt_kitchen_uptime` = 2026-11-05T21:02:47Z, i.e. rebooted ~3.8h before the first HIGH (firmware 26.10.8.1). I could not retrieve the kitchen CO2 history (the CO2 entity is not in the recorder's states_meta, so unknown; likely excluded). Cause (cooking/occupancy vs sensor artifact) is **unknown**. Because HIGH delivered normally, the missed-safety-alert concern does not apply to real hazards; only the 1500-1600 ppm MEDIUMs were dropped.
- CO and smoke classes are CRITICAL/HIGH life-safety (route immediate). Confirmed none of the 520 rows is a CO hazard type; `safety` rows are high_co2 and high_tvoc only.

## Falsification checks done

- "Maybe digest rows exist under another person_id/channel": the delivered in (0,2) non-audit count since 10-01 is 0 across all coordinators/channels.
- "Maybe immediate sends happen without rows": all send paths write a `delivered=1` row; MEDIUM sends would appear; none exist, and gates are > MEDIUM by config.
- Not verified: whether the heartbeat "All quiet" digests reached WhatsApp/iMessage (needs BlueBubbles/WhatsApp-side evidence; I did not use stored credentials).

## Fix

Config-first (settings change fixes it, no code):
1. Preferred: set `nm_whatsapp_severity` and/or `nm_imessage_severity` to LOW/MEDIUM (e.g. whatsapp MEDIUM) AND keep `delivery_pref=digest`. Then LOW/MEDIUM alerts get digest-queue rows (NM:2045+ gate passes) and flush at 08:00/18:00 to digest_channels. Caveat: with pref=digest, CRITICAL/HIGH still go immediate to every channel whose gate passes, so lowering the gate only widens the digest path for sub-HIGH, because `effective_pref` is forced immediate only for HIGH/CRITICAL (NM:1919-1927). Verify before turning the knob, since lowering to MEDIUM makes MEDIUM fire as immediate when pref is immediate; with pref=digest it queues.
2. Alternative: author a routing matrix for the person with `LOW/MEDIUM: whatsapp/imessage true`; same effect, per-recipient.
3. Volume check before doing 1: about 520 rows per 12 days, roughly 43/day of which duplicates group by title in the digest body (`_format_digest` NM:5646). Expect a long digest; consider also reviewing noisy producers (circuit_anomaly 133, stuck_signal 142, presence LOW 96) rather than routing all of it to the operator.

Code needed (minimal, independent of config), recommended as follow-ups:
- (a) Heartbeat honesty: do not send "All quiet" when audit rows with `no_channel_fired` exist in the window; or include "N alerts had no route" in it. Smallest fix: count `bucket_outcome='no_channel_fired'` since last flush in `_fire_digest` and append a line.
- (b) Make `delivery_rate`/`channel_status` diagnostics count `no_channel_fired` (it reads 100%).
- (c) Trip-wire in code (per fire-check rule): anomaly to NM when >N `no_channel_fired` rows for severity>=MEDIUM in 24h.
- (d) A MEDIUM alert for a digest-pref recipient with an empty router set should still queue a real digest row (currently the queue write is gated on the same channel set, so digest pref + high gates = silent drop). That is the actual logic hole; the config change in 1 just bypasses it.

## Cards / state
Board not edited. Suggested disposition: NM-NO-CHANNEL-FIRED-1 confirmed real; split config (operator knob) vs code (d) + (a) + (c).

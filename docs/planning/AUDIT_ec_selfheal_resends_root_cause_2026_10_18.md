# AUDIT: EC-SELFHEAL-UNEXPLAINED-RESENDS-1 root cause (re-verified)

Run Sun 2026-10-18 20:59-21:10 CDT (`date`). Read-only. Prober. Not read: HVAC/presence state-of-play (not relevant).
Operator question (10-18): "why a new setting? What's the real problem". Operator answer on the card: keep the +/-2 tolerance; next = plan review of PLANNING_ec_reserve_witness_fix.md.

## Verdict

**The real problem is a dead witness, not a missing setting. No setting is needed.**
The reserve write verifier reads `number.enpower_482348004678_reserve_battery_level` as its "local witness". That entity is a dead reading: it has only ever been 10.0 or `unavailable` in the live recorder (2026-10-11 11:10 to 10-19 01:36 UTC, 90 rows), while the real reserve moved 5..99 on both the cloud number and the Envoy's own sensor. Any commanded reserve other than 10 therefore looks "unapplied" and runs the 15/30/60 min re-send ladder, a CRITICAL page and a 3 h stand-down. The correct, live, already-existing source is `sensor.envoy_482543015950_reserve_battery_level`. The minimal fix is a REUSE source-swap inside the existing resolver (no new CONF, no new sensor), which is what PLANNING_ec_reserve_witness_fix.md already specifies. This audit independently confirms its premise.

## 1. Which entity, why frozen, since when

- Checker: `_local_entity_for(RESERVE)` -> `battery._get_entity("reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY, role="read")` (`custom_components/universal_room_automation/domain_coordinators/energy_write_verify.py:369-409`, key_map at ~:392-396). Default resolves to the Enpower number above. The docstring of the reader (`:1555` area) says the honest witness is the Envoy reserve sensor; the code reads the number (doc/code mismatch). The `hw_witness: "envoy_reserve_battery_level"` label in anomaly rows is a literal string, not the entity read.
- Live recorder, `ssh ha sqlite3 -readonly /config/home-assistant_v2.db`, states since 9 days ago:
  - number.enpower_482348004678_reserve_battery_level: 90 rows, states {unavailable, 10.0} only.
  - number.iq_battery_hacs_battery_reserve (cloud): 91 rows, {5,6,7,8,9,10,12,13,14,15,20,80,81,90, unavailable, unknown}.
  - sensor.envoy_482543015950_reserve_battery_level: 191 rows, {5..26, 80, 81, 90 ...}.
- URA DB `anomaly_log` metric `write_local_witness_divergence`, surface reserve_soc: local_seen = 61.0 from 2026-07-20 07:31Z to 08-04 22:23Z (2,937 rows by my query; prior audit counts 2,979), then 10.0 from first row 2026-08-05 16:37Z onward (commanded 80, local_seen 10.0). Even on 08-04 21:18Z a commanded 10 was met with local_seen 61.0, so the number was not tracking in July either; it was stale at 61 then stale at 10. Frozen at 10 since 2026-08-05 (~2.5 months), stale before that.
- WHY it froze: UNKNOWN. Not verifiable from this host (no integration log retained that far; the number has no long-term statistics, so the recorder cannot show the transition). The HA core source says the number's value_fn is `reserved_soc` from the Enpower storage-settings payload while the working sensor is the Encharge aggregate `reserve_soc` (PLANNING_ec_reserve_witness_fix.md section 1.2, citing enphase_envoy number.py:63-70 / sensor.py:754-760; I did not re-read HA core). The card's belief that local battery writes died with fw 8.2.4225 is consistent but I did not verify the firmware date. Do not assert a cause in the fix; assert only "different payload field, empirically frozen, sibling sensor alive".
- Not a cloud-vs-local issue: the sensor is also local (enphase_envoy integration) and tracked ground truth in both known episodes (10-12/13 read 14 while number said 10; 10-14 cloud 90 at 15:47:36, sensor 90 at 15:48:22 per the card).

## 2. Prior art: does URA already read the right value elsewhere?

- Cloud oracle `number.iq_battery_hacs_battery_reserve` is the verifier's primary oracle and is correct but can stall (card: 10-14 09:08-15:47 CDT stuck at 6.0 with no state update for 6.5 h while the sensor went 6->8->10). That stall is a second, real issue, and is exactly why a second honest local witness matters.
- grep of `custom_components/universal_room_automation` (excluding tests) for `reserve_battery_level` returns no production reader of the Envoy sensor. So there is no existing read to REUSE for the sensor itself; the REUSE is the resolver (`_local_entity_for`), the registry-sibling pattern (`_nws_last_updated_entity`, energy_battery.py ~3049-3075, per the planning doc) and the configured SOC entity as the serial anchor. Planning doc section 1.2 has the full REUSE/NEW table; nothing in it adds a CONF.
- `energy_reserve_soc_entity` must NOT be repointed: it is also the local write-fallback target (energy_battery.py ~842-883 per card). Config-first therefore does not solve it.

## 3. Quantification (URA DB, `anomaly_log`, reserve_soc surface, CDT-agnostic UTC dates)

`pending_write_stuck` severity 3 (attempt rows) / severity 4 (CRITICAL attempt 3), all with oracle_seen=10.0 (my query counted `oracle_seen 10.0` in every one):

| Date | sev3 | sev4 |
|---|---|---|
| 10-10 | 2 | 1 |
| 10-11 | 7 | 3 |
| 10-12 | 6 | 2 |
| 10-13 | 2 | 1 |
| 10-14 | 7 | 3 |
| 10-15 | 3 | 1 |
| 10-16 | 3 | 0 |
| 10-17 | 4 | 1 |

Sev-3 rows alone appear on 27 of the 31 days from 09-18 to 10-17 (2-10/day). So roughly 3-10 false watchdog events per day, 0-3 CRITICAL pages/day, each event re-sending the same reserve value (attempts at 15/30/60 min) plus a 3 h hard stand-down. Also in the same window: `write_local_witness_divergence` 13-172 rows/day (the same defect, info severity). `write_verification_failed` / `write_reverted` (30-75/day on 10-13/10-14) come from the cloud-oracle stall, NOT from this witness; the fix does not remove them.

Effect: cost is bounded because resends carry a value the battery already holds. Real behavior effect: the stand-down makes `_result` skip same-value re-dispatch for up to 3 h (card log evidence, energy_write_verify.py:2310, energy_battery.py ~6487). Safety effect: the dead witness also hides some real failures (a command that never lands but equals 10 reads "converged").

## 4. Falsification and caveats

- Would disprove "dead witness": any non-10 reading of the number. Recorder shows none in 9 days; URA DB shows none since 08-05.
- Operator-held +/-2 tolerance: with `_compare` +/-2.0 (energy_write_verify.py:1136-1140, per planning doc) the 10-17 case (commanded 10, actual 9) is "converged" against ANY witness. The card's acceptance direction (2) as written ("real alert in the 9-vs-10 case") cannot pass under ±2; restate it against the 10-12/13 case (commanded 10, battery 14), which is outside tolerance. This matches the planning doc's section 0 item 2 and the operator's "keep the margin".
- Not re-verified by me: the 28-page-days figure and the artifact/probable split (311/300/11) from the 10-17 audit; the stand-down log line (HA system_log, 10-16 23:42 CDT) is the card's evidence, not re-read.

## 5. Recommendation

Proceed with the planned Tier 2 source-swap (plan review next, per operator). Prefer the Envoy reserve sensor via registry unique_id lookup, falling back to today's number for homes without the sensor. No new setting, no change to `energy_reserve_soc_entity`, no tolerance change. Separately card (not this fix): the cloud-number stall (6.5 h on 10-14) and the commanded-3-below-minimum-5 clamp.

# AUDIT — Hand-Built Memory: room:study_a, July 2026

Stage 0 of MVP_hierarchical_memory.md. Built 2026-08-02 entirely from
existing data: URA DB (environmental_data 2.5k Study A rows/window,
occupancy_events, ura_activity_log, house_state_log 1,379 July
transitions) + HA recorder (retention back to 2026-07-26). All queries
read-only. Timestamps in source DBs are UTC-naive; everything below is
converted to CDT. This artifact is the acceptance fixture for Stage 1:
the implemented facade must reproduce §4's answers by diff.

## 1. Episode ledger (hand-adjudicated, memory_episodes shape)

| # | node_id | type | started (CDT) | ended | adjudication | adjudicated_by | attrs (abridged) | source_ref |
|---|---|---|---|---|---|---|---|---|
| E1 | room:study_a | hazard_recurrent | 07-03 08:18 | 07-03+ (462 recurrences through July) | confirmed_low_value | operator (this audit) | {type: high_co2, severity: LOW, count: 462} | ura_activity_log:hazard_detected |
| E2 | room:study_a | comfort_fan_on | 07-26 17:23 → 07-31 19:31 (6 events) | — | confirmed (occupied-evening comfort; home/sleep family at fire time) | this audit | {temps: 80–83°F, speeds 33–100%} | ura_activity_log:fan_on |
| E3 | room:study_a | occupancy_phantom | 08-01 08:05 | ~12:00 (~4h) | **phantom** (fan-transition onset; InvisOutlet mmWave held presence; no PIR corroboration) | operator + probe (AUDIT_fan_signature_separability_probe) | {fan: dreo704s at 100%, house: away, mechanism: boot fan-on (v5.42.0 BUG-1) → mmWave self-excitation loop} | ura_activity_log 08-01 08:05 "Fans on at 100% (79°F)" |
| E4 | room:study_a | sensor_dropout | 08-01 13:49:10 | brief | confirmed_local (InvisOutlet motion+occupancy both unavailable same second; no sibling correlation) | this audit | {entity: invisoutlet_b7d0, kind: device-local} | recorder states |
| E5 | room:study_a | config_changed | ~07-30 | — | confirmed | operator | {mmWave moved occupancy_sensors→presence_sensors (7-room remediation); InvisOutlet excluded from trusted set} | session record / core.config_entries |
| E6 | room:study_a | config_changed | 08-01 ~19:00 | — | confirmed | operator | {room_cameras added: g3_instant_last_motion, camera.armcrestash41b_2} | core.config_entries |
| E7 | house | systemic_dropout | 08-01 20:36 | ~60s | confirmed_systemic (**228 distinct** studya/studyb/invisoutlet-matching entities unavailable in one 6-min window = restart boot transient, not device fault) | this audit | {cause: v5.46.1 deploy restart} | recorder states |
| E8 | room:study_a | occupancy_phantom | 08-01 evening (away 18–20 CDT bin shows occ_rate 0.032 vs 0.000 all-July prior) | — | phantom (post-restart re-excitation, same chain as E3) | this audit | {residual of E3 mechanism pre-v5.46.0} | environmental_data.occupied |

**Writer-gap finding (Stage-1 input):** E3 — the month's most important
event — does NOT appear in `occupancy_events` (zero Study A rows on
08-01; July has only 160 entry/150 exit rows, trigger_source
overwhelmingly `occupancy_sensor`). The phantom lived in entity state
and the activity log but no episodic record exists anywhere. This is
the vision's core claim ("history owned by nobody") demonstrated in our
own DB, and it validates Stage 1's episode writers at the trust-stack
sites.

## 2. Baseline table (metric_baselines shape, CDT 3h-bin × family, July)

Key form: `room:study_a / <signal>:<bin>:<family>` → (mean, sd, n).
Full grid computed; the load-bearing rows:

| context | n | temp °F | humidity % (±sd) | occ_rate |
|---|---|---|---|---|
| h06-08 × home | 1002 | 75.3 | 59.7 ± 3.5 | 0.080 |
| h09-11 × home | 1044 | 76.1 | 60.1 ± 3.4 | 0.193 |
| h12-14 × home | 1046 | 76.4 | 60.3 ± 3.3 | 0.210 |
| h09-11 × away | 99 | 78.9 | 56.3 ± 2.2 | **0.000** |
| h12-14 × away | 93 | 79.8 | 55.1 ± 1.8 | **0.000** |
| h15-17 × away | 163 | 81.2 | 55.4 ± 1.6 | 0.006 |
| h18-20 × away | 190 | 81.9 | 55.6 ± 1.7 | 0.032 † |
| h21-23 × sleep | 779 | 75.4 | 60.3 ± 4.1 | 0.096 |

† poisoned — see fact F3 correction in §3.

Two structural reads: **away-daytime occupancy for Study A is
identically zero across the entire month** (the sharpest possible
anomaly prior — ANY away-hours occupancy is a >3σ event), and **away
humidity sits in a tight 54–56% band (sd ≈ 1.2–2.2) vs home 59–61%
(sd ≈ 3.4)** — context-conditioning matters; the same 62% reading is
normal at home, 4σ away.

## 3. Consolidated facts ledger (memory_facts shape)

| id | node | topic | statement | confidence | derived_from |
|---|---|---|---|---|---|
| F1 | room:study_a | occupancy_reliability | mmWave-sole occupancy onsets coincide to the second with fan power/speed transitions; steady-state fans produce none. | high | E3, E8 + probe events (Jaya 07-29) + separability audit |
| F2 | room:study_a | sensor_trust | InvisOutlet (b7d0) holds presence without corroborating cause and drops out device-locally; excluded from trusted set by operator. | high | E3, E4, E5 |
| F3 | room:study_a | occupancy_baseline | Away-hours occupancy rate ≈ 0.000 (all daytime away bins, full July, n=355+). | high | §2 grid |
| — F3.1 (supersedes F3-naive) | | | *Worked correction:* naive fold gives away 18-20 occ_rate 0.032 and away 15-17 0.006 → "occasional away-evening occupancy is normal." Both traced to adjudicated phantom episodes (E3/E8). F3 EXCLUDES phantom-window samples per the quality gate; superseded_by lineage records the correction. Without episode-adjudication feedback into baselines, the phantom teaches the room that phantoms are normal — the poisoning failure mode, observed in our own data. | | supersedes F3-naive; derived_from E3, E8 |
| F4 | room:study_a | notification_hygiene | high_co2 LOW hazard recurs ~15×/day when occupied (462 in July); individually logged, never adjudicated, no escalation ever warranted so far. | medium | E1 |

## 4. The seven queries (MemoryAnswer form)

**Q1 — sibling room (Study B): "sensor dropouts overlapping my 08-01
window?"** → verdict **ok**, support 8: Study B's ESPHome still_energy
dropped at 08:05, 10:27, 14:02, 14:46 CDT (device-intermittent,
recurring singly) — AND at 20:36 CDT both rooms dropped together with
**228 sibling entities** (E7). Value: my 13:49 InvisOutlet dropout (E4)
had NO sibling correlate → local fault; the 20:36 event had 228 → not
my problem, boot transient. Distinction made from data, not from the
troubleshooting checklist. *(provenance: recorder states; E4, E7)*

**Q2 — NM: "is 62% humidity unusual for Study A right now?"** → depends
on context, which is the point: house=home, h12-14 → baseline 60.3±3.3
→ z≈0.5, verdict ok/normal → **damp severity**. house=away, h12-14 →
55.1±1.8 → z≈3.8, verdict ok/unusual → **keep or raise severity**.
July's 462 LOW CO2 hazards (F4) are the live use case: a
baseline-aware NM digest ("recurrent, normal-for-occupied-context,
462nd occurrence") replaces per-event lines. *(provenance:
metric_baselines rows §2)*

**Q3 — operator: "why did the fan run 4 hours on 08-01?"** →
`narrative(room:study_a, 08-01 06:00–13:00)`: house AWAY all morning
(house_state_log) → 08:05 restart-window fan-on at 100% at 79°F
(activity log; v5.42.0 BUG-1, since fixed) → fan transition excited
InvisOutlet mmWave (F1) → mmWave-sole occupancy held ~4h with zero PIR
(E3, phantom) → no release until [fan/state edge ~12:00] → cites F1,
F2 for mechanism; notes E5 (this sensor no longer trusted) and that
three fixes shipped v5.40–v5.46 target each link. *(provenance: E3 +
house_state_log + activity_log + F1/F2)*

**Q4 — dashboard: "what was unusual in Study A this week?"** →
`unusual(room:study_a, 07-26..08-01)`, ranked: (1) away-hours occupancy
08-01 morning+evening, z→∞ vs 0.000 prior (E3/E8); (2) fan-on at 08:05
away (never observed in July's 6 prior fan-ons, all home/sleep-family
evenings); (3) temp 83°F 07-26 evening, high tail of home band; (4)
InvisOutlet double-dropout 13:49 (E4). Items 1–2 ARE the incident —
a dashboard consumer would have surfaced it in real time. *(provenance:
§2 grid + episode ledger)*

**Q5 — diagnosis session: "episodes matching occupancy_phantom, July
window?"** → verdict ok, support 2: E3 (08-01 morning, adjudicated
phantom, fan-transition onset) + E8 (08-01 evening residual). On the
NEXT phantom anywhere, recurrence match arrives in one call with the
adjudication and mechanism attached — July's answer took a 14-hour
forensic session to construct the first time. *(provenance:
memory_episodes)*

**Q6 — facts(room:study_a)** → F1–F4 as §3, each citable with
derived_from — including the F3.1 supersession showing the correction
lineage working on real data. *(provenance: memory_facts)*

**Q7 — profile(room:study_a) + profile(coordinator:energy)** →
room: **contains** — occupancy substrate {Zigbee occupancy/lux/temp/
humidity (trusted), InvisOutlet mmWave (presence bucket, untrusted per
F2), room_cameras: G3 Instant (motion-only; no person capability) +
Armcrest via Frigate (person, face-capable)}; actuators {3 lights, 1
night-light, Dreo tower fan, blinds, climate: shared Bryant zone-1
(zone-tier owned)}. **Can do** (declared × enabled × actionable):
lighting ✓/✓/✓; comfort-fan ✓ w/ away-veto+D2+transition-gate /✓/ ✓;
humidity-fan ✗ declared; covers ✓/✓/✓; camera-person fusion ✓/✓/
✓-as-of-08-01-restart (E6 + v5.46.1). July config deltas: E5, E6.
coordinator:energy: **contains** ≈ nothing (thin by design). **Can
do** — reserve/TOU arbitrage strategy (enabled; observation-mode off),
peak-avoidance + AC-ramp savings accounting, load proposals (shed
parked), EVSE precedence, DB write governance. The capability ladder is
the answer shape for every "why didn't X happen": declared? enabled?
actionable-now? *(provenance: config entries + registries, live read;
capability registry = Stage-1 code artifact)*

## 5. Gate self-assessment (operator judges; my honest scoring)

| Q | Earned its keep? | Why |
|---|---|---|
| Q1 | YES | fault-vs-systemic distinction from data; checklist step 3 automated |
| Q2 | YES | 462 real July notifications compress; context flip (home-normal vs away-4σ) is decisive |
| Q3 | YES | the actual 14-hour forensics, replayed as one call with mechanism facts attached |
| Q4 | YES | would have surfaced the incident in real time (away-occupancy z→∞) |
| Q5 | YES (conditional) | value realizes on the NEXT phantom; July itself only proves the shape |
| Q6 | YES | F3.1 correction on real data is the anti-poisoning proof |
| Q7 | PARTIAL | answer is constructible and useful, but mostly restates config + session knowledge; the declared-capability registry doesn't exist yet, so this one is a design template, not a data result |

Self-score: **6 of 7** (Q7 partial), against a gate of 4/7.

## 6. Data gaps found (Stage-1 requirements, discovered not assumed)

1. The month's defining event has no episodic record anywhere (E3
   writer gap) — episode writers at the trust-stack sites are the fix.
2. `notification_log` July has zero Study-A-attributable rows despite
   462 hazards — room attribution missing in the notification path;
   Stage-1 NM consumer should write its conditioning decisions as
   episodes or this stays invisible.
3. `anomaly_log` has no room-scoped entries (metric_baselines is
   coordinator/circuit-scoped today) — confirms the baseline-writer
   deliverable is new work, not duplication.
4. Recorder retention is ~7 days — month-scale answers MUST come from
   URA-owned tiers; narrative()'s raw-log reach is a week deep at best.
   (Architecture already assumes this; now it's measured.)
5. DB timestamps are UTC-naive; the facade must own the tz conversion
   or every context bin is off by 5 hours (found the hard way in this
   audit's first baseline pass).

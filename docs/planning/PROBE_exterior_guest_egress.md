# PROBE — EXTERIOR-GUEST-EGRESS-1 (D0 gate)

**Card:** `EXTERIOR-GUEST-EGRESS-1` · **Thread:** presence
**Gates:** D1 / D2 / D3 of `docs/planning/PLANNING_exterior_guest_egress.md` (rev 486627875)
**Author:** oji@outlook.com · **Date:** 2026-08-17
**Kind:** READ-ONLY measurement probe. No design. All DB reads `mode=ro`.

**Data surfaces used**
- URA DB (own store, NOT recorder-purged): `/config/universal_room_automation/data/universal_room_automation.db` via `ssh ha` + `sqlite3 ?mode=ro`.
- HA recorder (`purge_keep_days: 7`): `/config/home-assistant_v2.db`. True window observed: **2026-08-10 14:15 → 2026-08-18 02:50 UTC** (~7.5 d).
- Live entity registry: `~/ha-config/.storage/core.entity_registry`.
- `ura-sqlite` MCP is not configured; used `ssh ha` throughout (CLAUDE.md `/Users/ojiudezue/...` path is stale).

D0 gate thresholds from the plan: **D1 needs ≥30% face-sighting coverage per entry event; D2 needs that AND ≥3 entry-events/week.**

---

## Q1 — Does `ura_person_egress_event` fire, and how often?

**METHOD.** The bus event is persisted by `database.log_entry_exit_event()` into table **`person_entry_exit_events`** (schema: `timestamp, person_id, event_type, direction, egress_camera, confidence`). Producer stamps `datetime.utcnow().isoformat()` (`database.py:3725`) — **timestamps are UTC-naive**. Queried row count, min/max, per-day and trailing-window rates.

```sql
SELECT count(*), min(timestamp), max(timestamp) FROM person_entry_exit_events;
SELECT count(*) FROM person_entry_exit_events WHERE direction='entry' AND timestamp>=datetime('now','-7 days');
```

**RESULT.**
- **6651 rows**, spanning **2026-03-04 → 2026-08-17** (166 days). This table is URA's own store and is **not** subject to the 7-day recorder purge, so the full history is available.
- `event_type` = `egress` for 100% of rows.
- Trailing-7-day: **347 total events, 186 `entry`, ~50/day.** Trailing-28-day: 438 entry events.
- Per-day is bursty (0–363) but non-zero on essentially every active day.

**CONFIDENCE: HIGH.** Direct count over the producer's own persisted table.

---

## Q2 — Direction + confidence distribution

**METHOD.** `GROUP BY direction`, `GROUP BY confidence`, `GROUP BY person_id` over all 6651 rows.

**RESULT.**
| direction | rows |
|---|---|
| entry | 3352 |
| exit | 3299 |
| **ambiguous** | **0** |

| confidence | rows |
|---|---|
| 0.8 | 3814 |
| 0.9 | 2837 |

- `person_id`: **NULL for 100%** of rows (D1 identity plumbing not yet built — hard-coded `None` at `transit_validator.py:1106`/`:1121`).
- **Zero ambiguous / zero low-confidence (0.3/0.4) rows — by construction.** The producer only persists when `direction != "ambiguous"` (`transit_validator.py:1114`), so ambiguous verdicts fire on the bus but never reach this table. The persisted set is therefore **100% high-confidence** (0.8 single-platform / 0.9 multi-platform).

**Interpretation vs the "overwhelmingly ambiguous = NO-GO" test:** the opposite holds. Every *persisted* egress verdict is high-confidence. (Caveat: the ambiguous *fraction* of all bus fires is not measurable from the DB because it is filtered at source; that would require bus-event capture, out of scope for a read-only probe.)

**CONFIDENCE: HIGH** for the persisted distribution; **MEDIUM** on the true ambiguous rate (unobservable offline).

---

## Q3 — Face-sighting coverage per entry event

**METHOD.**
1. Enumerated `sensor.*_last_recognized_face*` in the live entity registry.
2. Correlated `entry` events (7-day, UTC) against named-face state changes in the recorder within the code's actual window (`EGRESS_ENTRY_WINDOW_SECONDS = 45`, const.py:2119), and a generous ±120 s comparison. "Named" excludes `unknown/Unknown/unavailable/None/""`. Two camera scopes: (a) egress-adjacent + door cameras only, (b) all cameras incl. interior.

```
# registry: EVERY recognized-face entity carries the _2 suffix
sensor.madrone_g6_entry_last_recognized_face_2, sensor.front_door_aerial_last_recognized_face_2, ... (23 total)
```

**RESULT — structural.** Confirmed the earlier probe: the code builds `sensor.{base}_last_recognized_face` (no suffix); **every live entity is `_2`**. The unsuffixed entity does not exist → the face-recognition subscription resolves to nothing → **face coverage is 0% today.** The fresh-face identity path is structurally dead until the cycle-2 `_2`-suffix fix lands.

**RESULT — what coverage WOULD be after the suffix fix** (queried the `_2` entities directly, 7-day recorder window, n = 186 entry events):

| scope | window | covered | coverage |
|---|---|---|---|
| egress-adjacent + door cams | ±45 s (code's window) | 13 | **7.0%** |
| egress-adjacent + door cams | ±120 s | 22 | 11.8% |
| all cams (incl. interior) | ±45 s | 32 | 17.2% |
| all cams (incl. interior) | ±120 s | 56 | 30.1% |

Named-face changes in 7 d: 218 total across ALL cameras, but only **18** at egress-adjacent/door cameras — the recognized faces cluster on interior cameras (playroom, master_hallway, staircase, upstairs_hall), not the doors that gate egress. (`Unknown` = face-detected-but-unrecognized fired 575× in 7 d; those would yield `person_id="unidentified"`, not an identity.)

**Assessment vs the 30% D1 gate:** at the window and camera scope the code actually uses, post-fix coverage is **~7%** — far below 30%. The only configuration that reaches 30% (±120 s AND counting interior cameras) is not the egress identity path. **The D1 coverage gate is not met even after the cycle-2 suffix fix.**

**CONFIDENCE: HIGH** for 0%-today (registry-confirmed structural dead path) and for the ~7% post-fix figure at the code's window; **MEDIUM** on exact percentage (7-day sample, timezone aligned via UTC on both sides).

---

## Q4 — Approach-track terminations at an egress-adjacent camera

**METHOD.** `memory_episodes` where `episode_type='exterior_track'`. For `classification='approach'` AND `label='person'`, extracted the last hop `json_extract(attrs_json,'$.path[#-1]')` and tested membership in `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` (const.py:1859) ∪ {`madrone_g6_entry`}.

**RESULT.**
- `exterior_track` episodes: **1327 rows**, but window is only **2026-08-06 → 2026-08-17 (~11 d)** — this table is compacted far more aggressively than `person_entry_exit_events`.
- Classification split: approach 649 · pass_by 417 · circling 261.
- **approach + person = 220 tracks; 207 (94%) terminate at an egress-adjacent/door camera** (~18/day). Top last-hops: front_side_ptz 124, rear_ptz 38, hot_tub 27, utilities_ptz 9, g5_bullet 5, armcrest 3, front_door_aerial 1.

The approach→egress-adjacent-termination signal is **strong and abundant, and does NOT depend on face recognition.** It is a proximity/behavioral signal (not identity), so it fits INV-4 path (b) — a `census_confidence` contribution — not the identity plumbing.

**CONFIDENCE: HIGH** for the ratio; **MEDIUM** on absolute daily rate (11-day compacted window).

---

## Go / no-go per deliverable

| Deliverable | Gate | Measured | Call |
|---|---|---|---|
| **D1** — populate `person_id` on egress event | ≥30% face-sighting coverage/entry | **0% today** (dead `_2` path); **~7%** post-suffix-fix at code's ±45 s window; 30% only at ±120 s + interior cams | **NO-GO** |
| **D2** — guest corroboration (dwell/confidence) | D1 coverage AND ≥3 entry/wk | entry rate **186/wk** (62× threshold) ✓ but D1 coverage fails ✗ | **NO-GO** (inherits D1 block) |
| **D3** — approach-track corroboration | approach tracks terminating at egress cams | **207/220 (94%)**, ~18/day, face-independent | **GO** (data-supported) |

**D1 — NO-GO.** Not merely blocked on the cycle-2 `_2` suffix fix: even *with* the fix, in-window identity coverage at door/exterior cameras is ~7% (recognized faces land on interior cameras). Populating `person_id` would attach an identity to fewer than 1 in 10 entry events. Revisit only if face recognition is materially improved AT the door/exterior cameras (the probe would then re-run Q3). The suffix fix is still worth shipping in cycle 2 for the interior-camera identity paths that consume these sensors — it just does not unblock egress identity.

**D2 — NO-GO.** The entry-rate half of the gate passes comfortably; the coverage half fails through D1. Identity-weighted guest corroboration has no identity to weight.

**D3 — GO.** The approach-track → egress-adjacent-termination signal is strong (94%), abundant (~18/day), and independent of the dead face path. Per INV-4 this must be wired as a `census_confidence` contribution to the *existing* unid gate (path b), never as a third arm (INV-1/INV-4). It is a proximity signal, not identity — the plan's guest-corroboration value should be re-scoped onto D3, with D1/D2 parked behind a face-recognition-at-doors trigger.

**Net:** build D3; park D1/D2 with the explicit revisit trigger "face recognition coverage at door/exterior cameras ≥30% in a re-run of Q3."

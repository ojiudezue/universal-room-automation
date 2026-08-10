# AUDIT — HVAC duty-cycle limiter firing frequency

**Date:** 2026-08-09 (data through 2026-08-10T00:17Z)
**Mode:** strictly read-only (`mode=ro` URIs, recorder queries scoped by `metadata_id`)
**Author:** measurement probe (no code changed, no services called)

## Mechanism (given, not re-derived)

`domain_coordinators/hvac_const.py:392-394` — `DUTY_CYCLE_WINDOW_SECONDS = 20*60`,
`DUTY_CYCLE_SHED = 0.50`, `DUTY_CYCLE_COAST = 0.75`. In shed/coast only, a zone
exceeding its share of compressor runtime in the rolling 20-min window sets
`runtime_exceeded = True`, forcing preset `away` (`hvac.py:1445`). Normal mode has
no limit; sleep is exempt.

---

## Verdict summary

| Question | Verdict |
|---|---|
| **Q1 — how often?** | **~8.7 forced-away events/day house-wide**, 100% of them inside the daily 21:00–01:00Z coast window, 67% while the zone was occupied. Bursty: a single zone can flip 8 times in 2h20m. |
| **Q2 — recent or long-standing?** | **The behaviour is long-standing; the *visibility* is new.** The `reason` ledger only exists from v5.56.0 (first reasoned row 2026-08-07T00:40Z). A ledger-independent behavioural proxy (short-cycle away→return ≤20 min) is **flat across the full 31-day window** and is if anything *lower* in the last three days than in mid-July. The constraint itself has not become more aggressive: coast is a flat ~3.96–4.00 h/day for the whole recorder window. **Not a regression from the v5.47→v5.64 train.** |

---

## Data sources & retention

- **URA DB** `/config/universal_room_automation/data/universal_room_automation.db`,
  `ura_activity_log`. Actual retention observed: **2026-07-10T07:00Z → 2026-08-10T00:17Z**
  (31 days, longer than the assumed ~14). 17,598 rows; 3,154 `preset_change`.
- **HA recorder** `/config/home-assistant_v2.db`, `states` scoped to
  `metadata_id` 16391 (`sensor.ura_energy_coordinator_hvac_constraint`) and
  16372 (`sensor.ura_energy_coordinator_tou_period`). Retention 2026-08-02 → now.

---

## Q1 — Quantification

### Ledger coverage caveat (read this before the counts)

`reason` is present on **268 of 3,154** `preset_change` rows. Every row before
`2026-08-07T00:40:54Z` carries exactly the key set
`('house_state','new_preset','old_preset')` — no `reason`, no `runtime_exceeded`,
no `home_persons`. So all Q1 numbers below describe a **~3.1-day window**
(2026-08-07T00:40Z → 2026-08-10T00:17Z), not the full retention.

Reason vocabulary observed in the ledger era: `vacant_past_grace` 134,
`house_state_transition` 107, `runtime_exceeded` 27. (`stale_occupancy` and
`pre_arrival` did not appear as preset-change reasons in this window.)

### Per day, per zone

| Day (UTC) | zone_1 | zone_2 | zone_3 | total |
|---|---|---|---|---|
| 2026-08-07 (partial, from 00:40Z) | 5 | 0 | 0 | 5 |
| 2026-08-08 | 6 | 0 | 1 | 7 |
| 2026-08-09 | 5 | 7 | 2 | 14 |
| 2026-08-10 (partial, to 00:17Z) | 0 | 1 | 0 | 1 |
| **Total** | **16** | **8** | **3** | **27** |

**Rate: 27 events / 3.06 days ≈ 8.8 forced-away events per day house-wide.**

### Occupied subset (comfort-relevant)

**18 of 27 (67%)** fired with `home_persons` non-empty:

| `home_persons` | count |
|---|---|
| `[]` (nobody home per the person entities) | 9 |
| `["person.oji_udezue"]` | 8 |
| `["person.ziri","person.jaya"]` | 7 |
| `["person.ezinne","person.oji_udezue"]` | 3 |

Note: `home_persons` is a **house-level** person list, not zone occupancy — it is
the best occupancy proxy the ledger carries, but a non-empty list does not prove
the *flipped zone* was occupied. Zone-level corroboration was not attempted
(would need recorder occupancy per zone; flagged as a follow-up).

### Episode structure

Episodes = runs of `runtime_exceeded` triggers on one zone separated by <60 min.

| Zone | triggers | episodes | flips/episode | episode span |
|---|---|---|---|---|
| zone_1 | 16 | 5 | 2, 3, 3, 4, 4 | 35–60 min |
| zone_2 | 8 | **1** | **8** | **140 min** |
| zone_3 | 3 | 3 | 1, 1, 1 | 0 min (isolated singles) |

Detail:

- **zone_1** — five tight episodes, each 35–60 min, 2–4 flips. Example
  2026-08-07 21:12/21:37/21:52/21:57Z, all `home -> away`, `home_persons =
  [oji]`, `house_state = home_day`, returning to home at 22:02Z. This is the
  classic sawtooth: forced away, window resets, preset returns, compressor
  catches up, limiter fires again ~15–25 min later.
- **zone_2** — the outlier by *structure*, not count. A **single 2h20m episode**
  on 2026-08-09 with **8 flips** (21:54, 22:14, 22:34, 22:54, 23:19, 23:34,
  23:54, 00:14Z), continuously occupied by `["person.ziri","person.jaya"]`,
  spanning `home_day` → `home_evening`. Cadence is a near-perfect 20-min beat —
  i.e. the zone re-saturates its 75% coast allowance in essentially every window
  for the entire evening. It never gets a clean return within the episode.
- **zone_3** — three isolated singles, each returning within ~10 min. Benign.

So: **not** "ten flips spread over two weeks". zone_1 produces recurring
short-burst sawtooth every evening; zone_2 produced one sustained
whole-evening oscillation under confirmed occupancy. That zone_2 episode is
the comfort complaint.

Three triggers show `old_preset = manual` (e.g. zone_1 2026-08-08T22:11Z,
zone_2 2026-08-09T21:54Z) — the limiter is overriding an operator manual preset,
which is worth a separate look.

### Time-of-day vs TOU

All 27 events, hour-of-day (UTC): 21:00 → 6, 22:00 → 7, 23:00 → 7, 00:00 → 7.
**Zero events outside 21:00–01:00Z.**

Measured windows from the recorder:

- `hvac_constraint` enters `coast` at **21:00Z** and returns to `normal` at
  **01:00Z**, every single day 2026-08-04 → 2026-08-09.
- `tou_period` = `peak` 4.00 h/day, matching that window.

So the distribution is **100% coincident with TOU peak / coast**, which is
exactly what the mechanism predicts (the limiter is inert in `normal` and
`pre_cool`). There is no evidence of the limiter firing outside its intended
window.

### Is zone_2 an outlier?

By raw count, no — zone_1 fires twice as often (16 vs 8). By **episode shape**,
yes: zone_2's 8 triggers are one uninterrupted 140-minute oscillation, whereas
zone_1's 16 are spread over five bounded 35–60 min bursts and zone_3's are
isolated singles. zone_2 is the only zone that failed to recover inside its
episode.

---

## Q2 — Is this recent?

### The instrumentation confound — stated plainly

**v5.56.0** (`d604716f7`, "hvac: delete Writer B + add preset reason-ledger",
tagged 2026-08-06 17:40 PDT = **2026-08-07 00:40Z**) is what created the
`reason` field. The last `preset_change` row *without* a reason is
**2026-08-07T00:40:54Z** — the changeover is exact to the minute of the tag.

Therefore: **the `reason='runtime_exceeded'` series cannot be extended before
2026-08-07.** Any naive "0/day before 08-07, 9/day after" reading is
instrumentation appearing, not behaviour changing. On that field alone, Q2 is
**undeterminable**.

### What *can* be determined — ledger-independent proxy

Pre-ledger rows still record `old_preset` / `new_preset` / `house_state` /
timestamp / zone. The duty-cycle limiter's signature is a **short-cycle**: a
flip to `away` followed by a return to non-`away` within ≤20 min (the window
length). That proxy is computable across the full 31 days.

Short-cycle count per day (all zones, all reasons — an upper bound on
limiter activity):

| Period | mean short-cycles/day |
|---|---|
| 2026-07-10 → 07-26 (pre-train, 17 d) | **18.0** |
| 2026-07-27 → 08-02 (train start, 7 d) | 2.7 |
| 2026-08-03 → 08-06 (mid-train, 4 d) | 16.8 |
| 2026-08-07 → 08-09 (ledger era, 3 d) | **12.3** |

Daily detail (excerpt): 07-15 → 29, 07-22 → 28, 07-25 → 28, 07-20 → 26,
08-05 → 25, 08-04 → 22, **08-07 → 20, 08-08 → 7, 08-09 → 10**.

Total `preset_change` volume per day is likewise flat: 51–183/day across the
whole window, with the ledger-era days (130, 68, 72) sitting at or below the
31-day median. The 07-27→08-02 trough coincides with an away/low-occupancy
stretch (zone_1 and zone_2 short-cycles drop to ~zero while zone_3 continues),
not with any release.

**Conclusion:** short-cycle churn in the last three days is *lower* than the
mid-July baseline. There is no step change at any release boundary — not at
v5.56.0, not anywhere in the v5.47→v5.64 train.

### Has the *constraint* become more aggressive?

No. Hours per day by `hvac_constraint` state (recorder, 16391):

| Day | coast | normal | pre_cool |
|---|---|---|---|
| 2026-08-02 (partial) | 2.98 | 3.85 | 6.62 |
| 2026-08-03 | 3.99 | 7.29 | 12.72 |
| 2026-08-04 | 3.96 | 4.23 | 15.80 |
| 2026-08-05 | 4.00 | 4.88 | 15.12 |
| 2026-08-06 | 3.94 | 5.24 | 14.82 |
| 2026-08-07 | 3.96 | 3.18 | 16.85 |
| 2026-08-08 | 3.96 | 4.38 | 15.67 |
| 2026-08-09 | 3.99 | 5.18 | 14.83 |

**`shed` never occurred** in the recorder window — every observed limiter firing
was under the *looser* 75% coast threshold, not the 50% shed threshold. Coast
is pinned at ~3.96–4.00 h/day, clock-driven off the 4h TOU peak. The exposure
window has not widened. **This is not an energy-side regression.**

Recorder retention (7 days) does not reach back to mid-July, so coast hours
cannot be compared against the pre-train baseline — but since coast is derived
from a fixed TOU peak schedule that is itself 4.00 h/day every day observed,
there is no plausible mechanism by which it was materially different in July.

### Code history

```
git log -S"DUTY_CYCLE"            -- custom_components/   # newest: b53e6e97d (v4.7.30)
git log -S"runtime_exceeded"      -- custom_components/   # newest: 8f665d0ff, d604716f7 (v5.56.0)
git log -S"_energy_constraint_mode" -- custom_components/ # newest: 7d6ac1196 (v3.17.0)
```

- The **thresholds themselves** (`DUTY_CYCLE_*`) were last touched in
  **v4.7.30**, long before this train.
- The **constraint-mode derivation** (`_energy_constraint_mode`) was last touched
  in **v3.17.0**.
- The only recent `runtime_exceeded` commits are **v5.56.0** (`d604716f7` add
  reason ledger + delete Writer B) and its fix-up (`8f665d0ff`) — i.e. the
  observability change and the Writer-B removal, not a threshold change.

Writer-B removal is the one substantive behavioural change in the window. It
consolidated preset writers; it did not alter the duty-cycle thresholds or the
coast schedule. The flat short-cycle proxy across the v5.56.0 boundary
(08-06 → 11, 08-07 → 20, 08-08 → 7) shows no step.

---

## Verdicts

**Q1 — How often:** ~8.8 duty-cycle forced-away events per day house-wide over
the measurable 3.06-day ledger window; 27 total, split zone_1 16 / zone_2 8 /
zone_3 3. **67% (18/27) fired with people home.** 100% inside the 21:00–01:00Z
coast/TOU-peak window, all under the 75% coast threshold (shed never engaged).
The shape matters more than the rate: zone_1 runs 2–4-flip sawtooth bursts most
evenings; zone_2 produced one **8-flip, 140-minute continuous oscillation** on
2026-08-09 with two occupants present. Three events overrode a `manual` preset.

**Q2 — Recent or long-standing:** **Long-standing behaviour, newly visible.**
The `reason` field is a v5.56.0 artefact (first reasoned row exact to the tag
minute), so the reason series alone cannot answer Q2 — stated explicitly. But
the ledger-independent short-cycle proxy is flat-to-declining across the full
31 days (18.0/day mid-July vs 12.3/day now), total preset-change volume is flat,
the duty-cycle constants last changed in v4.7.30, the constraint derivation in
v3.17.0, and coast exposure is pinned at ~4.0 h/day with no widening. **No
release boundary in the v5.47→v5.64 train shows a step change.** This is not a
regression we shipped; it is a pre-existing coast-window comfort cost that the
reason ledger has now made legible.

## Follow-ups (not actioned — read-only audit)

1. **Zone-level occupancy corroboration.** `home_persons` is house-scoped;
   confirm the zone_2 2026-08-09 episode had occupants *in zone_2* via recorder
   occupancy sensors before treating it as a comfort defect.
2. **`manual` preset override.** Three triggers overrode an operator manual
   preset. Whether that is intended precedence deserves its own look.
3. **Sawtooth damping, not threshold raising.** The failure mode is oscillation
   (window reset → immediate re-saturation), not the threshold value. A
   post-trip cooldown or hysteresis on re-entry would address the zone_2 shape
   without weakening the coast budget. Marginal-benefit decomposition required
   before any build.
4. **Extend the proxy backwards** if a longer-horizon confirmation is wanted —
   `ura_activity_log` retention is ~31 days, not 14, so a second month of
   pre-ledger proxy is available on the next rollover.

## Queries used

Probe scripts were run as `ssh ha "python3 -" < script.py`, all DBs opened
read-only:

```python
sqlite3.connect("file:/config/universal_room_automation/data/"
                "universal_room_automation.db?mode=ro", uri=True)
sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
```

1. **Schema + action census**
   `select sql from sqlite_master where name='ura_activity_log'`;
   `select action,count(*) from ura_activity_log group by 1 order by 2 desc`.
2. **Reason coverage over time** — pull
   `select timestamp,zone,details_json from ura_activity_log where action='preset_change' order by timestamp`,
   `json.loads` each, bucket by `timestamp[:10]` counting total vs
   `"reason" in details`.
3. **Per-day/per-zone runtime_exceeded** — filter the same set to
   `details["reason"]=="runtime_exceeded"`, `Counter((day, zone))`.
4. **Occupied subset** — `sum(1 for d in re_rows if d.get("home_persons"))`.
5. **Episodes** — per zone, sort triggers by time, split runs on >3600 s gaps;
   locate the return flip as the first later event with `new_preset != "away"`.
6. **Time-of-day** — `Counter(int(ts[11:13]))` over the trigger set.
7. **Ledger-independent short-cycle proxy** — over *all* `preset_change` rows,
   per zone: for each flip with `new_preset=="away"`, find the next event with
   `new_preset != "away"`; count it if the delta ≤ 20 min. Bucket by day/zone.
8. **Pre-ledger key sets** —
   `Counter(tuple(sorted(details)) for rows without "reason")`
   → uniformly `('house_state','new_preset','old_preset')`, 2,886 rows.
9. **Constraint / TOU dwell** — recorder, scoped:
   `select last_updated_ts,state from states where metadata_id=? order by last_updated_ts`
   for `metadata_id` 16391 and 16372; integrate consecutive-row deltas into
   per-day hours per state; print transition timestamps where state changes.
10. **Code history** — `git log -S"DUTY_CYCLE" -- custom_components/`,
    same for `runtime_exceeded` and `_energy_constraint_mode`;
    `git log --tags --simplify-by-decoration --pretty="%ci %h %d"`.

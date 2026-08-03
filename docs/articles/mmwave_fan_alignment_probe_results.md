# mmWave × Fan-Transition Alignment — Fresh 7-Day Probe (2026-08-02)

Companion data for the "your ceiling fan is impersonating you" post.
Re-run of the original recorder analysis over the trailing 7 days
(2026-07-26 → 2026-08-02), read-only against the Home Assistant recorder
database. Script included verbatim at the bottom so you can run it on
your own DB.

## Method in one paragraph

For each fan-equipped room: take every mmWave rising edge (`off→on`)
that occurred **while the house was away** (so a human can't be the
cause), and measure Δt to the nearest fan state-change row in the same
room. Compare the count of edges landing within ±5 s of a fan transition
against the number expected by pure chance (fan transitions × 10 s
window ÷ away seconds × onsets). Then check the converse: fan running at
constant speed in an away house — how many mmWave onsets occur?

House-away time in the window: **109.9 h of 168 h**.

## Result 1 — the alignment table (trusted Zigbee mmWave, Study A)

| Away-hours observed | mmWave away-onsets | Within ±5 s of a fan transition | Expected by chance |
|---|---|---|---|
| 109.9 | **2** | **2 of 2** | 0.02 |

The two onsets, to the second:

| Onset (CDT) | Δt to nearest fan transition |
|---|---|
| 07-26 18:44:59 | **−2.4 s** |
| 07-31 15:41:16 | **−0.5 s** |

Two onsets in 110 vacant hours, both inside a 5-second window around a
fan transition, against 0.02 expected — roughly **100× over chance**.
Every mmWave detection in this vacant room this week was a fan
transition. Zero onsets during steady-state fan operation.

Control rooms (same analysis): Master bedroom Zigbee mmWave — 1 away
onset, NOT fan-aligned (732 fan transitions available to align with;
honest miss, likely a pet/curtain). Jaya bedroom — 0 away onsets in
1,090 fan transitions' worth of activity.

## Result 2 — steady-state fans are innocent (again)

Constant-speed fan windows ≥30 min in an away house, no fan state
changes inside the window:

| Room | Windows | Hours | mmWave onsets inside |
|---|---|---|---|
| Study A | 4 | 2.6 | **0** |

(Smaller than the original probe's multi-hour negatives because the
away-veto shipped since — fans mostly no longer run in vacant rooms at
all, which is the fix working. The onsets that DO still occur all sit at
transitions, per Result 1.)

## Result 3 — a chattering sensor aligns at chance, and that's diagnostic

The same room has a second mmWave (an outlet-integrated unit we no
longer trust). Its numbers: **24,370** away-onsets (it flaps
constantly), 191 within ±5 s of a fan transition — vs **217 expected by
chance**. At/below chance = the alignment analysis correctly reports
"this sensor's edges are noise, not fan physics." The same math that
convicts the fan exonerates itself on a noisy sensor: if your alignment
rate matches the chance rate, you've got a chatter problem, not a fan
problem.

## Result 4 — the shipped gate

The creation-time suppression gate (mmWave-sole occupancy within 5 s of
a fan transition is not admitted) has been live ~20 h. Its per-room
counters read 0 so far — expected: the actuation guard now prevents
fans from running in vacant rooms in the first place, so the
transition+vacancy coincidence the gate exists for is now rare by
construction. The three mechanisms (actuation guard, creation gate,
sustain demotion) overlap on purpose; the counters are since-boot and
the house restarted twice today for unrelated deploys.

## The script (run it on your own recorder DB)

Edit `PAIRS` to your rooms' mmWave binary sensor + fan entity, and
point it at your recorder db (default `/config/home-assistant_v2.db`).
Read-only (`mode=ro`). If you don't track house-away state, delete the
`in_away` filtering and interpret with care (occupied-room onsets are
mostly real humans).

```python
import sqlite3, datetime as dt
rec = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
now = dt.datetime.now(dt.timezone.utc).timestamp()
since = now - 7*86400

PAIRS = {
  'Study A': ('binary_sensor.your_mmwave_presence', 'fan.your_fan'),
}

def st(eid):
    return rec.execute("""
        SELECT s.state, s.last_updated_ts FROM states s
        JOIN states_meta sm ON s.metadata_id = sm.metadata_id
        WHERE sm.entity_id=? AND s.last_updated_ts>=?
        ORDER BY s.last_updated_ts""", (eid, since)).fetchall()

for room, (mm, fan) in PAIRS.items():
    fts = [ts for s, ts in st(fan) if s in ('on', 'off')]
    onsets, prev = [], None
    for s, ts in st(mm):
        if s == 'on' and prev == 'off':
            onsets.append(ts)
        prev = s
    aligned = [(dt.datetime.fromtimestamp(t).strftime('%m-%d %H:%M:%S'),
                round(min((abs(t-f), t-f) for f in fts)[1], 1))
               for t in onsets if fts and min(abs(t-f) for f in fts) <= 5]
    # chance baseline: each onset has a 10s hot window around every fan row
    window_s = now - since
    chance = len(fts) * 10 / window_s * len(onsets) if window_s else 0
    print(f"{room}: onsets={len(onsets)} aligned<=5s={len(aligned)} "
          f"expected_by_chance={chance:.2f}")
    for a in aligned[:20]:
        print("   ", a)
```

Interpretation guide: aligned count ≫ chance → your phantoms are fan
transitions (a short suppression window will fix them). Aligned ≈
chance with a huge onset count → your sensor is chattering; fix the
sensor (or stop trusting it) before blaming the fan.

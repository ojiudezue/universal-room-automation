# PROBE — Healthy mmWave Reporting Cadence & Corrected `T_floor` Calibration

**Type:** Read-only measure-before-build probe. No code built. No files
modified other than this doc.
**Date:** 2026-08-19
**Author:** Oji Udezue
**Doctrine:** "Measure Before You Build" (CLAUDE.md). Directly calibrates
the **D-HIGH-1** finding from the STEP-chatter Tier-3 Review D: *the mmWave
`T_floor` default (1.5s) is likely TIGHTER than a healthy fast mmWave's
reporting cadence, which would false-quarantine healthy sensors and violate
the un-fakeable-definition safety property.*

**Companion probes (read first):**
- `PROBE_sensor_chatter_definition_handcheck.md` — established the amended
  definition: **provenance gate + device-sourced floor + burst requirement**
  (single-event is NO-GO). This probe does NOT re-open that; it calibrates
  the `T_floor` number and the burst threshold that probe left open.
- `INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md` — the incident
  the detector must catch (Garage-B ratgdo + Master-Bedroom Zigbee mmWave).

---

## Data path used

Direct read-only SQLite over the **live HA recorder** on the HAOS host via
`ssh ha 'python3 -' < probe.py`, opened
`file:/config/home-assistant_v2.db?mode=ro`. The Samba `immutable=1` path is
rejected (returns `database disk image is malformed` on the live WAL — same
finding as the prior handcheck). Window: **last 7 days** (recorder retention;
DB is 33 GB). Method per sensor: pull all `states` rows ordered by
`last_updated_ts`, keep only real `on`↔`off` transitions (drop
`unavailable`/`unknown`, which reset the interval so we never span a dropout),
compute the inter-transition interval distribution and rolling-window burst
counts.

`T_floor` is a floor on the **inter-transition interval** (time since the
prior transition), per the handcheck definition — either edge (OFF→ON
re-detect or ON→OFF release).

---

## Method note — where healthy mmWave sub-floor events actually come from

Every healthy mmWave sensor holds its **ON** state for a long fixed hold /
presence-timeout (measured `dwell_ON` minima: Zigbee 30–48 s, Screek 6–10 s,
esphome ~26 s). The short inter-transition intervals are almost all on the
**OFF edge**: the sensor releases, then **re-detects the same active person
within a fraction of a second**. That OFF→ON re-detect is *legitimate,
healthy behavior during active motion* — it is exactly the signal a `T_floor`
must not punish. This is the mechanism behind D-HIGH-1.

---

## Finding 1 — every healthy mmWave family's minimum inter-transition is FAR below 1.5s

Per-family inter-transition distribution (7 d), and the sub-3s histogram
(buckets `<0.5 / 0.5-1 / 1-1.5 / 1.5-2 / 2-3` s):

| family (representative units) | min | p1 | p5 | p50 | sub-3s hist | healthy-min |
|---|--:|--:|--:|--:|---|--:|
| **esphome wifi mmWave** (kitchen, studyb) | **0.00** | 1.50 | 6.16 | 36.8 | 4/2/31/26/36 | 0.00 |
| **meross wifi mmWave** (jaya, mediaroom) | **0.00** | 0.43 | 1.08 | 6.9 | 92/84/533/220/292 | 0.00 |
| **Zigbee mmWave t/h/l** (master, living, up-hall) | **0.12** | 2.32 | 9.67 | ~70 | 1/3/4/10/25 | 0.12 |
| **Aqara Zigbee presence** (`0xa4c1382e60e05225`) | **0.07** | 2.03 | 8.58 | 46.2 | 1/0/2/7/6 | 0.07 |
| **Zigbee mmWave** (game/jaya/media/study/ziri) | **0.39** | 4.18 | 27.1 | ~130 | 4/1/0/1/10 | 0.39 |
| **Screek L13** (2412s, b38b24) | **0.21** | 1.24 | 5.43 | 33–140 | 3/8/9/11/18 | 0.21 |
| **Hobeian Zigbee occupancy** (garagea, dining…) | **1.51** | 1.73 | 13.4 | ~63 | 0/0/0/5/2 | 1.51 |
| reed/contact (freezer, dishwasher door) | 0.56 | 1.28 | 3.42 | ~40 | 0/1/3/1/6 | 0.56 |
| opener ratgdo dry-contact (door reed) | — no cycles in window — | | | | | — |
| athom ESP mmWave / PIR; Seeed wifi | — 0 transitions (idle/offline in window) — | | | | | — |

**Verdict on D-HIGH-1: CONFIRMED, with margin.** Six of seven healthy mmWave
families reach a minimum inter-transition interval of **0.00–0.39 s** — an
order of magnitude below the 1.5 s default. Under a **single-event** rule the
1.5 s mmWave floor scores healthy sub-floor events routinely: the Meross
family alone logs **323–386 sub-1.5s intervals per 7 days** (see Finding 3).
A single-event mmWave floor at 1.5 s **would false-quarantine healthy
sensors.** The framing hypothesis ("healthy fast mmWave cadence ≈ 1 s, floor
1.5 s too tight") is not only correct — the true healthy floor is ~**0 s**,
not 1 s, for the fast wifi mmWave families.

> Corollary: the "set `T_floor` strictly BELOW the healthy minimum so a healthy
> sensor scores ZERO sub-floor events" reading is **UNACHIEVABLE** for the
> fast-wifi-mmWave family — its healthy minimum is 0.00 s. A floor below that
> is 0 s, which catches nothing. The un-fakeable definition therefore cannot
> rest on a per-event floor alone for mmWave; it **requires the burst rule**
> the handcheck already mandated. Finding 2 shows floor+burst does separate.

---

## Finding 2 — floor + burst DOES separate healthy from chatterer; the corrected floor is 1.0s

Because a per-event floor cannot separate fast mmWave (healthy min = 0 s), the
discriminator is the handcheck's mandatory **burst rule**: count sub-`T_floor`
events in a rolling **300 s** window. Table = max sub-floor events in ANY 5-min
window over 7 days, at three candidate floors:

| sensor | class | maxBurst/5min @1.0s | @1.5s | @3.0s |
|---|---|--:|--:|--:|
| Meross jaya | HEALTHY | **7** | 9 | 15 |
| Meross mediaroom | HEALTHY | **7** | 10 | 14 |
| esphome kitchen | HEALTHY | 3 | 4 | 4 |
| Screek 2412s | HEALTHY | 1 | 2 | 3 |
| Zigbee jaya | HEALTHY | 1 | 1 | 1 |
| Zigbee t/h/l master | HEALTHY | 1 | 1 | 1 |
| Aqara | HEALTHY | 1 | 1 | 2 |
| Hobeian garagea | HEALTHY | 0 | 0 | 2 |
| **ratgdo motion** | **CHATTER** | **22** | **23** | **109** |
| **invisoutlet motion** | **CHATTER** | **13** | **13** | **24** |
| **invisoutlet occupancy** | **CHATTER** | **13** | **13** | **24** |

Reading the gap between the worst healthy sensor (Meross) and the weakest
chatterer (invisoutlet) at each floor:

| floor | worst healthy burst | weakest chatterer burst | separating band for K |
|---|--:|--:|---|
| **1.0 s** | **7** (Meross) | **13** (invisoutlet) | **clean — K∈[8,12], pick K=10** |
| 1.5 s (current) | 10 (Meross) | 13 (invisoutlet) | fragile — only K∈{11,12}, ~1 event of margin |
| 3.0 s | 15 (Meross) | 24 (invisoutlet) | K∈[16,23], but Meross creeping up |

**The current 1.5 s mmWave floor leaves ~1 event of margin** between a busy
healthy Meross night (10) and the invisoutlet chatterer (13) — a single busier
motion window flips a healthy sensor into quarantine. **Lowering the mmWave
floor to 1.0 s widens the gap to 7 vs 13** and is the corrected default.

**Key simplification:** a 1.0 s floor with burst **still catches BOTH known
chatterers decisively** — ratgdo bursts to **22/5 min** and invisoutlet to
**13/5 min**, both ≥ K=10, while every healthy sensor stays ≤7. The
handcheck's worry that "only a ~3 s floor catches the ratgdo" applied to a
*single-event* rule (ratgdo is only 0.26% sub-0.5s). **Under the burst rule a
1.0 s floor catches it via its sustained flap** — so the per-family
opener-vs-mmWave floor split the handcheck proposed is **not required**; a
single unified 1.0 s floor + burst covers all blind-time families on this
dataset.

---

## Corrected `T_floor` calibration (the D-HIGH-1 fix)

| family | current default | measured healthy min | corrected `T_floor` | rationale |
|---|--:|--:|--:|---|
| mmWave (all sub-kinds) | 1.5 s | 0.00 s | **1.0 s** | 1.5 s fragile (10 vs 13 burst); 1.0 s → 7 vs 13, clean; still catches chatterers |
| PIR | 2.0 s | (see note) | **1.0 s** | unify; no healthy PIR exemplar chattered; 1.0 s catches ratgdo-class opener PIR |
| opener | 3.0 s | no healthy exemplar | **1.0 s** | only opener PIR in data is the *chatterer*; 1.0 s + burst catches it (22/5min) — 3.0 s unnecessary and pushes Meross to 15 |
| reed | 1.0 s | 0.56 s | **1.0 s** (keep) | reed min 0.56 s; keep, burst never approached (rare cycles) |

**Recommended unified default: `T_floor = 1.0 s` for ALL blind-time families,
paired with burst `K = 10` sub-floor events per rolling `300 s` window.**
On the 7-day dataset this yields: every healthy blind-time sensor ≤ 7 in any
5-min window; both known chatterers ≥ 13. Separating band [8, 12]; K = 10 is
the symmetric-margin choice.

**Per-entity overrides** are NOT required by the data — the unified 1.0 s
floor separates every observed family. Reserve per-entity override capability
(on the knob ladder) for a future device whose datasheet blind-time is known
to exceed 1.0 s (none observed here). Knob placement: `T_floor` and `K` are
review-gated safety bounds → **module constants** (energy_const-style), not
operator-facing entities (Numbers Get Knobs ladder rung 1).

---

## Does a separating floor exist for each family? (explicit verdict)

| family | clean floor+burst separation from chatterers? |
|---|---|
| esphome wifi mmWave | YES — healthy burst 3–4, well below K=10 |
| Meross wifi mmWave (fastest healthy) | **YES at 1.0 s (7 vs 13); NO/fragile at 1.5 s (10 vs 13)** — this is the load-bearing family |
| Zigbee mmWave (all) | YES — healthy burst ≤1 |
| Aqara Zigbee | YES — healthy burst ≤1 |
| Screek L13 | YES — healthy burst ≤2 |
| Hobeian Zigbee occupancy | YES — healthy burst 0 |
| reed/contact | YES — bursts never approached |
| opener PIR | **Unverifiable empirically** — the only opener PIR in the window IS the chatterer (ratgdo); no healthy opener exemplar exists to prove separation. Mitigated: it is caught (burst 22), and it shares the mmWave/PIR blind-time band, so the unified 1.0 s floor applies. Flagged as residual risk. |

**Single-event (no burst): NO clean floor exists for the fast-wifi-mmWave
family** — healthy min = chatterer min = 0.00 s. Confirms the handcheck: the
burst rule is mandatory, not optional.

---

## GO / NO-GO — "the un-fakeable definition is achievable with measured floors"

**GO — conditional on TWO corrections to the STEP defaults:**

1. **Lower the mmWave `T_floor` from 1.5 s → 1.0 s** (D-HIGH-1 fix). The 1.5 s
   default is fragile (≈1 event of burst margin against the invisoutlet
   chatterer) and outright false-quarantines under any single-event rule.
2. **Keep the burst rule (K = 10 / 300 s)** the handcheck already mandated —
   it is what makes the definition un-fakeable for fast mmWave, whose per-event
   healthy floor is 0 s. Unify PIR/opener onto the same 1.0 s floor; the
   separately-proposed 2.0 s/3.0 s family floors are unnecessary and (at 3.0 s)
   push the healthy Meross burst up to 15.

With those, on the observed 7-day data: **zero healthy false-positives**
(worst healthy burst 7 < K=10) and **both known chatterers caught** (ratgdo
22, invisoutlet 13 ≥ K=10). The un-fakeable safety property holds — a
correctly-working sensor cannot reach K=10 sub-1.0s events in 5 minutes.

**NO-GO for the definition AS DEFAULTED** (mmWave floor 1.5 s, single-event, or
per-family 2/3 s floors): fails the zero-false-positive constraint or the
margin test.

---

## Acceptance fixture emitted for the D-HIGH-1 fix build

- **Corrected defaults:** `T_floor = 1.0 s` (unified, all blind-time
  families); burst `K = 10` events / rolling `300 s`.
- **Negatives (MUST stay healthy under fix):** Meross jaya/mediaroom
  (maxBurst 7 @1.0s — the tightest healthy case, THE regression sentinel),
  esphome kitchen (3), Screek 2412s (1), all Zigbee mmWave (≤1), Aqara (1),
  Hobeian garagea (0).
- **Positives (MUST be flagged chatter under fix):**
  `binary_sensor.ratgdov25i_dbfe2a_motion` (burst 22 @1.0s),
  `binary_sensor.invisoutlet_b7d0_motion` (13), `…_occupancy` (13).
- **Discriminating criterion:** the fix is correct iff, at floor 1.0 s /
  K 10 / window 300 s, Meross scores < 10 AND both chatterers score ≥ 10.
  (If the build reproduces the current 1.5 s floor, Meross scores 10 = a
  FAIL boundary — the fixture discriminates the fix from the pre-fix state.)

---

## Caveats / residual risk

- **7-day retention only** — the 2026-08-09 incident window is purged; the
  ratgdo/invisoutlet ongoing storms are the incident-class proxy (strong,
  same as the handcheck).
- **Opener family has no healthy exemplar** — separation for opener PIR is
  argued by band-sharing with mmWave/PIR + the fact the chatterer IS caught,
  not by a clean healthy/chatter contrast. Residual risk if a future healthy
  opener PIR has a genuine >1 s re-fire cadence; add a per-entity override
  then.
- **athom ESP mmWave/PIR and Seeed wifi produced 0 transitions** in the
  window (idle rooms or offline) — not calibratable here; the unified floor
  applies by kind and should be re-checked if they become active.
- **Burst K and window are the second calibration knob.** K=10/300s is
  data-fit with ≥3 events of margin on both sides; both belong as review-gated
  module constants.

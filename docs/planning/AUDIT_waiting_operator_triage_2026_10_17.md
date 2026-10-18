# waiting_operator lane triage - 2026-10-17 (Sat, ~21:15 CDT)

Source: docs/planning/kanban.data.yaml, 40 cards with status waiting_operator (read: why/next/problem_solution/paged/reverified/measured). Read-only; nothing changed except this file. Operator away until Sun 10-18. Spot-checks via git log/grep are cited; everything else is from the card text and has not been independently re-verified.

Counts: PHYSICAL 8 | DEFAULT-TAKE 12 | STALE/CLOSE 1 | REAL DECISION 19 | total 40.

## Table

| Card | Bucket | Evidence | Proposed action / question |
|---|---|---|---|
| SAFETY-SENSOR-FLEET-HEALTH-1 | PHYSICAL | Heiman smoke s1_* unavailable since 10-15 12:46, re-verified 10-17 02:10; Thread re-commission needed | Re-pair smoke detector, check 4 leak pucks. The two config fixes (move gas sensor out of smoke list, drop ghost ziribathroom leak) are life-safety config, so keep them for an attended session |
| SAFETY-NO-INITIAL-SENSOR-PASS-1 | DEFAULT-TAKE | Card states recommended defaults (1c, 2a, 3=24h) | Take them; move to planned, build after feature/safety-nm-refire merges Sun 10-18 (Tier 2-DB) |
| OC-SHADOW-SAMPLES-EMPTY-1 | DEFAULT-TAKE | Code bug mechanism measured (optimization.py:1231 vs :1522, const.py:3985); commit d273f9cfe: shadow was a deliberate trust withhold | Take A: write validator fix + dedup into first slice of OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1 (doc only, no code now) |
| EC-SELFHEAL-UNEXPLAINED-RESENDS-1 | REAL DECISION | Energy reserve write path, "cannot fuck this up" arc | See Q1 |
| HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1 | REAL DECISION | Tier 3 presence state machine; accepting delayed security auto-arm | See Q2 |
| SAFETY-RATE-DETECTOR-DEAD-WINDOW-1 | DEFAULT-TAKE | Card recommends A; replay showed ~12 alerts/day of noise if revived (commit 9226af342) | Take A: doc note in Safety coordinator doc + code comment "dormant by design" (Tier 1) |
| FRONT-SIDE-PTZ-CHATTER-1 | REAL DECISION | Needs operator fact | See Q3 |
| FRIGATE-THRESHOLD-CLAIM-DISPUTED-1 | REAL DECISION | Needs operator data from Frigate host | See Q4 |
| CAMERA-SEAM-VALIDATION-1 | REAL DECISION | Operator is only oracle for physical adjacency; sheet docs/planning/VALIDATE_exterior_camera_seams.md | See Q5 |
| NM-BB-CHATGUID-SELFSEND-1 | PHYSICAL | Needs new Apple ID + Messages sign-in on Mac mini | One-line ask: create house Apple ID after the trip |
| ROADMAP-STALE-AGENTIC-LAYER-1 | DEFAULT-TAKE | Roadmap half already done: docs/ROADMAP_v12.md exists (DRAFT, 2026-08-28, supersedes v11); card says NO closes it | Close the roadmap half; park the agentic-layer vision doc with revival trigger "operator names it near-term" |
| EV-SENSOR-CLEANUP-1 | DEFAULT-TAKE | Dupe sensors already killed; residual is display-only (estimate labelled honest) | Decline per marginal-benefit; close, mark per-plug power hook "available if revisited". Low stakes, reversible: operator may flip to APPROVE (Tier 1) |
| EVCARD-1 | REAL DECISION | Dashboard spec needs operator review | See Q6 |
| SAFEWORD-WINDOW-1 | REAL DECISION | NM routing, outward-facing, regression-prone | See Q7 |
| DASH-QUICK-ACTIONS-1 | REAL DECISION | Definition of "common area" + scene contents | See Q8 |
| ROADMAP-UNDONE-REVIEW-1 | REAL DECISION | Operator read of a delivered doc | See Q9 |
| PWA-CENSUS-P12-RELEASE-1 | REAL DECISION | Deploys public site ura.phalanxmadrone.com; operator away | See Q10 |
| JEV-DECISION-CLASSIFIER-SPIKE-1 | REAL DECISION | Needs independent ground-truth labels | See Q11 |
| PERIMETER-DETECTION-WENT-DARK-1 | PHYSICAL | Coral hang suspected; back since 10-08 12:14; needs reseat/swap or detector move on Frigate host | Ask: reseat/swap Coral (A) vs scheduled Frigate restart (B) |
| CAMERA-SILENT-PRODUCER-TRIPWIRE-1 | DEFAULT-TAKE | Builder stopped after DO-NOT-SHIP; redesign (read quiet-duration from entities) is the stated recommendation, Tier 2 | Redo as proposed and re-run both reviews; keep digest routing as built, revisit paging later |
| PERIMETER-ALERT-VOLUME-FATIGUE-1 | REAL DECISION | Lever A depends on Q3; B/C change outward-facing alerts | See Q12 |
| COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 | DEFAULT-TAKE | Card recommends B (reuse CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY) | Take B; move to planned (Tier 2, 2 reviews) |
| ENVOY-FLAKINESS-181243-1 | DEFAULT-TAKE | Upstream bug #181243 open; drafting a report is reversible, posting stays with operator | Draft upstream report (A). Operator one-liner: anything scheduled ~23:05 CDT nightly? |
| ENERGY-CONSUMPTION-FORECAST-POISONED-1 | REAL DECISION | Two calls left; cleanup already done (v5.103.45) | See Q13 |
| ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 | REAL DECISION | Policy for paused rooms | See Q14 |
| DB-SIZE-GROWTH-1 | REAL DECISION | Deleting history is irreversible | See Q15 |
| LIGHTS-GUEST-MODE-BEHAVIOUR-1 | DEFAULT-TAKE | Recommended default is today's behaviour (no change) | Close as "no change"; optionally park per-room option with revival trigger |
| EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1 | DEFAULT-TAKE | Card recommends A; rung_1 only on 10-01, v5.103.37 removed night form | Park Tier-3 plan; revival trigger EC-EV-TOGGLE-TRIPWIRE-1 fires or >2 garage EVSE toggles/hour |
| HA-2027-DEPRECATIONS-URA-1 | DEFAULT-TAKE | Card recommends A (HA guidance: collapsible sections); breaks 2027.6+ | Take A; move to planned, fold into onboarding phase-2 plan before it builds |
| BLE-PROXY-PLACEMENT-1 | PHYSICAL | Mount proxies, power BP1_B | One-line ask: place Foyer first, power BP1_B |
| NIGHTLIGHT-SLEEP-ONSET-RECOLOUR-1 | REAL DECISION | Card says preference call, no recommendation | See Q16 |
| WIGTON-HA-UNRESPONSIVE-1 | PHYSICAL | Needs logs from Wigton HA UI or add-on install there | One-line ask: download Core/Supervisor/Host logs spanning a stall |
| CENSUS-ATHOME-RESIDENT-CORROBORATOR-1 | REAL DECISION | Multi-home policy + sensor | See Q17 |
| CENSUS-GROUND-TRUTH-CSV-FIX-1 | REAL DECISION | Needs operator's factual recollection | See Q18 |
| ROOM-ENERGY-SENSOR-MISPICKS-1 | REAL DECISION | Rooms' picks need operator choice (live config write) | See Q19 |
| CENSUS-PATIO-THROUGH-GLASS-1 | PHYSICAL | Mask/zone in Frigate2 and UniFi Protect NVRs (operator-owned hosts) | One-line ask: add patio mask/zone on family_room camera in both NVRs |
| FRONT-DOOR-LOCK-OFFLINE-1 | PHYSICAL | Lock unavailable, re-verified 10-17 02:10 | Swap batteries (lock; left to operator) |
| ELK-M1-HA-USABILITY-1 | PHYSICAL | 12 shorted zone loops at panel | Ask: check loops at panel terminals |
| HA-GC-GEN2-PAUSES-1 | DEFAULT-TAKE | Card states default: Health Monitor gc_refreeze_h 0 -> 4 h; measured pauses ~50/h x 0.6 s, no code | Set option in attended session, re-read gc_gen2_1h / loop_stalls 8-12h later. Note: it is an HA config-entry write, so not done by this read-only audit |
| HM-V21-LIVE-VALIDATION-1 | STALE/CLOSE | Live is now HM v2.2.0; v2.1 no longer installed; W13 PASS recorded 10-16; remaining W3/W10/W14/W15/W17 are operator-action checks on a superseded build | Close with "W3/W10/W14/W15/W17 unverified, accepted" (the card's own ACK path); write into README Validated table |

## REAL DECISION questions (one PICK each)

- Q1 EC-SELFHEAL-UNEXPLAINED-RESENDS-1: stale local reserve reading causes 1-5 false CRITICAL pages/day. PICK (A) new "reserve witness" options-flow entity, set to sensor.envoy_482543015950_reserve_battery_level (blank = today's behaviour) / (B) hard-code verifier to that sensor / (C) turn reserve pending watchdog off meanwhile. Recommend A.
- Q2 HOUSE-STATE-AWAY-FLAP: APPROVE the Tier-3 build of Plan Rev 2 (sustained-empty before AWAY), accepting security auto-arm up to 20 min later on a real departure? Yes/no. Recommend yes, but moot for this trip if family is back Sun; no action needed before Sunday.
- Q3 FRONT-SIDE-PTZ-CHATTER-1: Did you apply a crop/mask to front_side_ptz around 09-14/15? Yes (widen it) / No (camera detector fault on Frigate host).
- Q4 FRIGATE-THRESHOLD-CLAIM-DISPUTED-1: Share your score distribution or name a read-only host. If none, recommend close with "seven cameras stay at 0.7".
- Q5 CAMERA-SEAM-VALIDATION-1: tick/strike the 27 seams in docs/planning/VALIDATE_exterior_camera_seams.md and answer Q1-Q3 there.
- Q6 EVCARD-1: approve the redesigned EV card spec for the v8 Energy tab? Yes/no (fold into DASHBOARD-V8-FIX-BATCH-1).
- Q7 SAFEWORD-WINDOW-1: approve scope (perimeter-only, "duke Nh", 3 h cap) for a Tier 2 build? Yes/no.
- Q8 DASH-QUICK-ACTIONS-1: common-area = (A) room_type=common_area only or (B) plus hallways; and scene contents for Leaving/Good night. Recommend A.
- Q9 ROADMAP-UNDONE-REVIEW-1: read the delivered doc; ack to proceed with roadmap rewrite or close.
- Q10 PWA-CENSUS-P12-RELEASE-1: promote census-p12-exterior-dashboard to main and deploy the public PWA now (A) or after you are back Sunday (B)? Recommend B (no benefit to deploying a public site unattended).
- Q11 JEV-DECISION-CLASSIFIER-SPIKE-1: (A) you label 20-40 ambiguous occupancy cases / (B) approve me sourcing a disjoint truth signal (door count/manual log). Or park; the spike has no deadline.
- Q12 PERIMETER-ALERT-VOLUME-FATIGUE-1: lever (A) fix the front_side_ptz source first (depends on Q3, recommended) / (B) trim CRITICAL exterior_person channel fan-out (say which to keep) / (C) raise PERIMETER_ALERT_COOLDOWN_SECONDS from 300 s.
- Q13 ENERGY-CONSUMPTION-FORECAST-POISONED-1: (1) set dp_house_load_source to live_span, yes/no (still max_span_r1 on 10-10; it was re-checked and unchanged per commit 6d08df551)? (2) Option F + last-known-good seeding (Tier 2-DB, recommended) / Option S (Tier 2).
- Q14 ROOM-OVERRIDE-SWITCH-FORGOTTEN-1: for a paused room, (A) still turn lights OFF after vacancy timeout but never ON (Tier 2, recommended) / (B) no behaviour change, add reminder after N hours.
- Q15 DB-SIZE-GROWTH-1: retention for the 3 untrimmed history tables: (A) 90 days (recommended) / (B) 365 / (C) keep all; and does room_transitions get the same window?
- Q16 NIGHTLIGHT-SLEEP-ONSET-RECOLOUR-1: re-colour already-lit night lights to sleep red at Sleep onset? (A) yes / (B) no, today's behaviour (no recommendation; B costs nothing).
- Q17 CENSUS-ATHOME-RESIDENT-CORROBORATOR-1: (Q2) garage vouch default OFF on new installs so each house opts in? Recommend yes. (Q3) mis-vouch-rate sensor now or later? Recommend later.
- Q18 CENSUS-GROUND-TRUTH-CSV-FIX-1: on 10-03, who left by car ~12:13 vs ~13:55, and when did the long-stay guest return?
- Q19 ROOM-ENERGY-SENSOR-MISPICKS-1: pick which ONE of Living Room / Receiving Room keeps the shared SPAN plugs sensor, and whether Laundry Closet or Laundry keeps the shelly switch_0 meter; approve clearing Jaya Bedroom and Garage Hallway and fixing Guest Bedroom 2 Bathroom / Oji Vanity in an attended session.

## Notes

- Bucket choices lean conservative: anything touching energy reserve, presence state machine, public deploys, outward-facing alerts or irreversible deletion is REAL DECISION even where the card has a recommendation.
- Unverified: I did not re-check live HA state; PHYSICAL items rely on the 10-17 02:10 reverification stamps already on the cards.
- Nothing was moved or edited on the board; DEFAULT-TAKE actions are proposals for the driving session.

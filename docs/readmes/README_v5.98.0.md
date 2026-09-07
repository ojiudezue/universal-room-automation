# v5.98.0 — Wave-1 identity consumers

**Type:** Feature cycle (new user-facing capability) — first consumers of the
shipped egress `person_id` producer.
**Tier:** 2 (four low-risk additive consumers, disjoint files; consolidated
review pass + per-consumer mutation anchors + orchestrator independent
mutation-verify of the security-adjacent severity invariant).

## Why this cycle

The egress identity producer (v5.96.x BLE entry, exit backfill, v5.97.0 Frigate
face bridge) writes `person_id` onto crossing rows and exposes it as
`egress_identity_last_attach`. Until now that identity had **almost no
consumers** — the value was produced but not used. This cycle wires the four
lowest-risk, highest-value consumers so a recognized identity actually changes
what the operator sees. These four also act as the **live attach-rate
measurement** that gates the higher-risk Wave-2 consumers (guest gate,
unexpected-person, security verdict).

## What shipped

### C1 — Arrival / departure notification (`transit_validator.py`)
When an egress crossing resolves with a `person_id`, URA now fires a
best-effort NotificationManager notice: **"<Name> arrived"** / **"<Name>
left"** when identity confidence ≥ `ARRIVAL_NAME_CONFIDENCE_THRESHOLD` (0.75),
else the graceful-anonymous **"Someone arrived/left"** (notify > suppress).
- `direction=="ambiguous"` is skipped.
- `Severity.LOW` only — never an alert.
- The notify runs detached and is wrapped in `_safe_notify` (its own
  try/except) so an NM failure can never surface as an unhandled-task error
  **and** can never break the egress event emit / DB write (emit precedes the
  notify and is independently try-guarded at the call site).

### C2 — Named perimeter alert (`perimeter_alert.py`)
An exterior person alert whose camera has a recognized identity now appends
**" Identified: <Name>."** to the alert message.
- **Safety invariant (mutation-verified):** this mutates the message **TEXT
  ONLY** — severity and escalation are byte-identical to the un-named path.
- Confidence floor: Frigate legs (no numeric score) are admitted as
  engine-trusted (already floored at `FACE_MATCH_MIN_CONFIDENCE`=0.60 in the
  resolver); scored non-Frigate legs require ≥0.75.
- **Freshness gate:** legs older than `FACE_NAME_LATCH_TTL_S` are dropped, so a
  latched name from hours ago can never label a fresh 3am alert.
- Fully try-wrapped: any failure leaves the original message intact
  (anonymous).

### C3 — HVAC `camera_face` pre-arrival source (`hvac.py` + `hvac_const.py`)
`camera_face` is added to `DEFAULT_PRE_ARRIVAL_SOURCES` so a recognized face at
a door contributes to HVAC pre-arrival — a 2-line source-list add. The
membership filter still drops unknown sources; an operator who set a custom
`CONF_PRE_ARRIVAL_SOURCES` is unaffected (the default only applies when unset);
the producer already dispatches `{"source": "camera_face"}` — this only
unblocks a signal that was being filtered out.

### C4 — Egress-identity yield tile (`docs/dashboards/egress_identity_yield_card.yaml`)
A paste-in Lovelace panel surfacing the producer's live attributes (last
attach, 24h attach/ambiguity/abstain rates, BLE entry/exit counters, Frigate
face-bridge counters). Display-only; no new entities. Entity ids +
attach-dict keys **verified live 2026-09-06** against the running instance.

## Acceptance criteria — Live validation (prospective; write back post-restart)

- **C1 Live:** next resolved arrival/departure fires an NM notice with the
  correct name (or "Someone" when unresolved); an ambiguous crossing fires
  nothing; an NM outage does not error the emit. Check NM history / logs for
  "Arrival/departure notify:".
- **C2 Live:** a perimeter person alert on a camera with a live recognized face
  carries " Identified: <Name>." in the message; the alert's severity equals
  the severity the same alert would carry with no name (compare against a
  no-face alert of the same house-state); a stale-latch camera does NOT annotate.
- **C3 Live:** a recognized face at a door contributes to the HVAC pre-arrival
  decision (`camera_face` accepted, not filtered); no change for operators with
  a custom source list.
- **C4 Live:** the tile renders with no `unavailable` rows against
  `sensor.universal_room_automation_persons_in_house` /
  `..._persons_entered_today`; `egress_identity_last_attach` fields populate.
- **Measurement (gates Wave 2):** record the observed 24h
  `egress_identity_attach_rate_24h` — a sparse producer caps every consumer's
  value and may argue for producer work before more consumers.

## Notes / non-goals
- Wave-2 consumers (guest gate, unexpected-person suppressor, security verdict
  — the ≥0.9 security-decision surfaces) are **out of scope** here; they wait on
  the Wave-1 attach-rate measurement.
- Pre-existing suite-isolation fragility (cross-test `const`-stub poisoning
  causing `unknown location` import errors in a single-process full-suite run)
  is unrelated to this cycle — every touched test file passes in isolation
  (22 cycle tests + 219 sibling tests green).

---

## Validated 2026-09-06 (post-restart, HA core-2026.9.1, v5.98.0 live)

| Criterion | Result | Observed evidence |
|---|---|---|
| Clean module load (C1/C2/C3) | **PASS** | `error_log` structured scan of `universal_room_automation` post-restart: **zero ERROR / zero traceback** from `transit_validator`, `perimeter_alert`, `hvac`. Only benign pre-existing WARNINGs (SPAN energy-sensor unavailable, Bermuda polling fallback, HVAC boot-settle timeout, camera platforms unavailable). |
| No new regression class | **PASS** | The 55× `async_write_ha_state from a thread` warning is **pre-existing** (first_seen 13:42:16, hours before the ~17:4x v5.98.0 deploy; tracked as EC-SUBSWITCH-ASYNC-WRITE-THREAD-1) — not introduced by this cycle. |
| C4 tile — entity + attrs exist, correct types | **PASS** | `sensor.universal_room_automation_persons_in_house` live; `egress_identity_last_attach is mapping = True` (dict → the card's `.get()` calls resolve); `egress_identities_stamped`=0, `egress_face_ids_active`=0, `ble_legs_produced_count`=0, `frigate_face_*`=0 all present (0 = monotonic counters reset at restart, as documented). `face_producer_health="live"`. |
| C4 tile — entity ids correct | **PASS** | The `sensor.universal_room_automation_*` slug resolves; the old `sensor.ura_*` slug returns ENTITY_NOT_FOUND (the CRIT the review caught, now fixed). |
| Config validity | **PASS** | `ha_get_system_health(config_check)` → `result: valid, is_valid: true, errors: []`. |
| **C1 arrival/departure notify** | **Deferred-organic** | Event-driven — fires on the next resolved crossing. Proven in-suite (7 tests, RED-on-neuter incl. the `_safe_notify` swallow). Loaded clean; awaits a real arrival/departure. Discriminator: an `"Arrival/departure notify:"` entry in core logs + NM history. |
| **C2 named perimeter alert** | **Deferred-organic** | Event-driven — fires on the next exterior person alert with a live recognized face. Proven in-suite (8 tests; **severity-never-changes invariant independently mutation-verified by the orchestrator** — injecting a severity change turns the named-face tests RED). Loaded clean. Discriminator: a perimeter alert message containing `" Identified: <Name>."` with severity == the no-face baseline. |
| **C3 HVAC camera_face pre-arrival** | **Deferred-organic** | Event-driven — contributes on the next face-at-door pre-arrival. Proven in-suite (7 tests, RED-on-neuter at both `hvac.py:529` + `hvac_const.py:345`). `camera_face` already a valid options-flow selector; the default now includes it. |
| **Wave-2 gate measurement** | **Baseline captured** | `egress_identity_attach_rate_24h`=0 immediately post-restart (24h window reset). The organic disposition (see card `--revisit`) queries this rate once a day of crossings has accrued — it gates whether Wave 2 (guest gate / unexpected-person / security verdict) is worth building or whether producer work comes first. |

**Boot-only transients dismissed:** all counters at 0 (monotonic-from-restart, by design); `egress_identity_last_attach={}` (no crossing since boot). Both expected, not defects.

**Why three consumers are in-suite rather than live:** C1/C2/C3 are event-reactive on rare real-world events (a resolved crossing, an exterior alert with a recognized face, a face-at-door pre-arrival). Forcing them live would require staging those events; each is mutation-anchored in-suite (RED-on-neuter) and confirmed to load without error, and each carries a binary organic discriminator (above) for VALIDATE→DISPOSE at cycle close.

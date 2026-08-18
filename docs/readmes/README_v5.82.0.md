# URA v5.82.0 — Two census features become device switches, and turn on by default

Part of the census/guest/presence-identity program (see
`README_GROUP_census_guest_presence_identity.md`). This promotes two buried Camera-Census
options into one-tap **device switches**, wires them so toggling does **not** reload the
integration, and flips the relevant defaults **ON**.

## What shipped

**Two new device switches** (on the URA integration device):
- **`switch.ura_presence_face_matching`** ← `CONF_FACE_RECOGNITION_ENABLED` — URA uses face
  matches from your cameras to confirm who a person is during room presence and transitions.
- **`switch.ura_name_people_at_doors`** ← `CONF_EGRESS_IDENTITY_ENABLED` — people entering/leaving
  through door cameras are labeled with their name (v5.81.0 egress identity).

Both reuse the existing `DomainCoordinatorsSwitch` pattern and write to the integration entry's
options. **`Smart People Counting` (`enhanced_census`) intentionally stays in the options dialog**
— it's read at setup for a structural branch and can't be refreshed live without a reload; parked
until `__init__.py:2253` is re-runnable in place.

**No reload on toggle (the load-bearing safety property).** A naive options write would fire the
update-listener and reload the parent integration entry — the documented ~5-minute watchdog-outage
hazard (real 2026-06-03 / 2026-08-07, mitigated 2026-08-15). Instead both keys are added to
`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`, and a new dispatcher signal
`SIGNAL_URA_FACE_RECOGNITION_CHANGED` refreshes the two boot-cached consumers
(`transit_validator`, `presence`) live. `egress_identity` is a fresh-read per call — allowlist
entry only, no signal. Result: toggling either switch takes effect in seconds, zero outage.

**Defaults flipped ON** (operator decision — "turn them on, a flip is then unlikely; if it fails
we turn it off"): `DEFAULT_FACE_RECOGNITION_ENABLED` True (new), `DEFAULT_EGRESS_IDENTITY_ENABLED`
False→True. **Because these options are unset on the live install, both features activate at the
first tick after this deploy.** The switches are the live kill path.

## Controls

| Switch / knob | Backs | Default | Reload on change? |
|---|---|---|---|
| `switch.ura_presence_face_matching` | `face_recognition_enabled` | **ON** | No (signal refresh) |
| `switch.ura_name_people_at_doors` | `egress_identity_enabled` | **ON** | No (fresh-read) |
| Smart People Counting (options dialog) | `enhanced_census` | ON | Yes (stays in options) |

## Non-goals

- No new sensors, no new sensor attributes (+2 switches / +1 signal / +0 sensors).
- No third switch (`enhanced_census` stays in options).
- No behavior change to what the flags *do* — pure control-surface relocation + default flip.

## Review

Tier 2-DB: plan → two plan reviews (first found the reload hazard the naive design would have
re-triggered) → build → three framing-disjoint reviews (A correctness/INV-1 SHIP, B
reload-suppress/signal-chain SHIP, C surfaces/test-authority DO-NOT-SHIP) → fix-up (honest strings
+ behavioral signal-refresh tests replacing hollow ones). Orchestrator independently re-ran the
load-bearing mutation drill: neutering the real `async_dispatcher_connect` makes
`test_d2_transit_validator_flips_cached_flag_on_signal_without_reload` FAIL, restored → 35/35 green.

**INV-1 (falsifiable):** for each key, `switch.is_on` ⇔ `entry.options[KEY]` ⇔ every consumer's
read — immediately after toggle (via signal for the cached one) and across restart, WITHOUT a
parent reload.

## Acceptance criteria — live

- **L1:** boot clean, zero URA ERROR; both switches present on the integration device and `on`
  (defaults flipped); `enhanced_census` has NO switch.
- **L2 (no-reload):** toggling `switch.ura_presence_face_matching` flips
  `transit_validator._face_recognition_enabled` within seconds with **no integration reload** (no
  sibling-entity `last_changed` churn, no watchdog restart).
- **L3 (default-on is live):** with people home (Wed), face-attributed transit + `person_id` on
  egress crossings appear by default; specifically an EXIT creates **no phantom guest**.
- **L4:** flip either switch off → the corresponding feature goes dormant in seconds (kill path).

## Live Validation

### Validated 2026-08-18 (~09:35 CT, post-restart) — house EMPTY

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA ERROR | **PASS** | system_log ERROR count for universal_room_automation: 0 |
| L1 | Both switches present + ON; enhanced_census switch-less | **PASS** | `switch.ura_presence_face_matching` = on, `switch.ura_name_people_at_doors` = on (both default-flipped); `switch.ura_smart_people_counting` → 404 ENTITY_NOT_FOUND (correctly not exposed) |
| L2 | Toggle → NO integration reload | **PASS** | Toggled `presence_face_matching` off (09:34:57) then on (09:35:11); the UNtoggled sibling `name_people_at_doors` kept `last_changed=09:33:53` (boot) across BOTH toggles — not recreated, so no reload. Zero ERROR during. |
| L4 | Kill path works instantly | **PASS** | turn_off → state `off` verified immediately; turn_on → `on` restored. One tap, no outage. |
| L3 | Default-on live: real crossings named, no phantom guest on exit | **ORGANIC-PENDING** | Needs occupancy (Wed). Watch: face-attributed transit + `person_id` on egress; specifically an EXIT creates no phantom guest. Shared with v5.81.0 L2/L3. |

**Cycle stays open until L3 lands on occupancy (Wed).** L1/L2/L4 proven now — the headline
no-reload / instant-kill-path property is confirmed live.

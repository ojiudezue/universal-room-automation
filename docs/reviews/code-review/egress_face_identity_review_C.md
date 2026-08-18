# Review C — Lifecycle + Restart Resilience + Test-Fixture Authority

**Cycle:** EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 (egress-face identity stamp
+ census union fuse)
**Branch reviewed:** `feature/egress-face-identity-d1` @ `fa5b57c52`
**Base:** `develop` (three-dot diff)
**Framing (C):** lifecycle of new mutable state, timer/listener cleanup,
boot/restart ordering, D2 fence integrity, test-fixture authority + test
isolation.
**Verdict:** **SHIP with C-MED-1 fixed pre-deploy.** No CRITICAL/HIGH.
Lifecycle is clean; D2 fence held; behavioral tests drive production
code paths and the C-CRIT-1 discriminator is genuine.

---

## Scope reviewed

- `custom_components/universal_room_automation/camera_census.py`
  — new `_egress_face_ids` register, `_normalize_person_name`,
  `_normalize_name_set`, `register_egress_face`,
  `_get_egress_face_ids_fresh`; two fuse sites (`:1867-1878` raw union,
  `:3495-3510` enhanced house recompute).
- `custom_components/universal_room_automation/transit_validator.py`
  — `_resolve_egress_face_identity` helper (`:1056-1144`), emit-time
  `person_id` stamp on `ura_person_egress_event` and DB row
  (`:1207-1237`), best-effort census registration.
- `custom_components/universal_room_automation/const.py`
  — `FACE_MATCH_WINDOW_S = 60`, `EGRESS_FACE_UNION_TTL_S = 300`
  (module-rung per §7).
- `quality/tests/test_egress_face_identity_d1.py` — 15 tests, all PASS
  (`pytest ... test_egress_face_identity_d1.py -v` → 15 passed in 0.05s).

## D2 fence — HELD

Grep confirms zero touches to:
`config_flow.py`, `options_flow.py`, `PROTECT_CORROBORATION_ENABLED`,
`ura_kp_face_probe_received`, `CROSS_NVR_*`, `corroboration`.

## Lifecycle audit — clean

- **No new async task, listener, callback, or scheduled tick** added by
  this cycle. `register_egress_face` and `_get_egress_face_ids_fresh`
  execute inline on the existing coroutine hot paths (`_resolve_direction`
  for register, the census tick for readers). Nothing to cancel on
  unload — the state dies with the `PersonCensus` instance.
- **Boot ordering safe:** `transit_validator._resolve_direction` reads
  `self.hass.data.get(DOMAIN, {}).get("census")` and guards `is None`
  before calling `register_egress_face`. `_resolve_egress_face_identity`
  applies the same guard. A census-not-yet-constructed race just yields
  `person_id=None` (matches the pre-cycle behavior) — safe.
- **Restart resilience:** `_egress_face_ids` is a plain instance dict,
  populated only by `register_egress_face`. On HA restart it starts empty
  by design. No `RestoreEntity` involvement, no `.storage` write, no
  boot-poisoning surface (Bug Class: RestoreEntity → OFF-poisoning). The
  first post-restart crossing repopulates it in the normal path;
  `identified_count` degrades gracefully by one until then. Matches the
  plan's live criterion ("no crash, no spurious identities on empty
  house"). Verified by reading the constructor (`:1075`) — no restore
  hook.
- **Concurrency:** all mutation + read happen on the event loop; no
  thread hand-off. Correct today (see C-LOW-2 for a docstring gap).

## Test-fixture authority — genuine

- **`_house_apply` drives real production.** The C-CRIT-1 discriminator
  test `test_house_fuse_egress_only_moves_house_count` calls
  `census._apply_enhanced_house_census(raw, ble_persons, now)` — the
  real production method — with `ble_persons=[]` and
  `face_recognized_slugs=[]`, and asserts `identified_count == 1` after
  a lone `register_egress_face("ziri", …)`. If the `:3495-3510` fuse
  were reverted (`recognized_set = set(ble_persons) | set(face_recognized)`
  without the `egress_face_ids` union), this test would fail with
  `identified_count == 0`. The discriminator is **routed through the
  load-bearing site**, not a fixture-only assertion.
- **Behavioral emit test uses an injected clock**, not `time.sleep`.
  `test_behavioral_egress_event_carries_person_id_then_expires` advances
  the crossing timestamp by `FACE_MATCH_WINDOW_S + 1` via a
  `timedelta` argument to `_resolve_direction`. No wall-clock coupling
  (Bug Class #64: wall-clock-coupled tests).
- **Oracles independently authored.** Discriminator values (`"Oji"`,
  `"Oji_Udezue"`, `"oji_udezue"`, `"ziri"`) are hard-coded in the
  test body — not imported from production. Freshness bounds come from
  `ura_const.FACE_MATCH_WINDOW_S` / `EGRESS_FACE_UNION_TTL_S`, which is
  legitimate (these are the numeric-knob contract, not the behavior
  under test). No Bug Class #64 oracle-echo.
- **Suite baseline:** cycle-file run cleanly (15/15). Full-suite baseline
  diff is the validator's job; not run here per instructions.

---

## Findings

### C-MED-1 — Test module pollutes `sys.modules` without restore

**File:** `quality/tests/test_egress_face_identity_d1.py:30-45`
**Bug class:** Test pollution via unrestored `sys.modules` mutation
(same shape as `feedback_unrestored_mutation_drill_poisons_evidence.md`).
**Severity:** MEDIUM (test-suite integrity, not shipped behavior).
**Scenario:** At import time this module unconditionally installs stubs
into `sys.modules["homeassistant.helpers.area_registry"]` and
`sys.modules["homeassistant.helpers.event"]` (guarded only by
"if not present"). It never removes them. If `test_egress_face_identity_d1.py`
imports first in a session, EVERY subsequent test in the process
inherits these stubs — including tests that may need a differently-stubbed
`async_track_state_change_event` or `async_track_time_interval`. This is
exactly the pollution pattern the operator's "unrestored drill" memo
flagged.
**Fix:** Move the `sys.modules` installs into an `autouse` pytest fixture
scoped to this module that snapshots the pre-existing entries (or their
absence) and restores/deletes them in teardown. Alternatively, use
`monkeypatch.setitem(sys.modules, ...)` inside a fixture — pytest's
`monkeypatch` restores automatically.

### C-LOW-1 — Lazy-only TTL prune; register-time backstop missing

**File:** `custom_components/universal_room_automation/camera_census.py:2790-2809`
**Bug class:** Untracked mutable growth (weak form).
**Severity:** LOW (practical exposure small — both fuse sites are on the
census hot path, so readers fire routinely; `_egress_face_ids` is bounded
by the household member count in normal operation).
**Scenario:** `_get_egress_face_ids_fresh` prunes only on read. If a
future refactor disables the enhanced census path or gates a reader
behind a feature flag while leaving `register_egress_face` firing, the
dict grows unbounded across days. Today's blast radius is negligible.
**Fix (nice-to-have):** on `register_egress_face`, opportunistically
prune when `len(self._egress_face_ids) > N` (e.g. 32 — comfortably above
household size), or run the prune loop at register time. O(1) amortized;
removes the "readers must fire" invisible dependency.

### C-LOW-2 — Thread-safety contract undocumented

**File:** `custom_components/universal_room_automation/camera_census.py:2767-2789`
**Bug class:** Latent concurrency assumption (informational).
**Severity:** LOW.
**Scenario:** `register_egress_face` and `_get_egress_face_ids_fresh`
are safe today because both callers execute on the event loop; a future
off-loop caller (executor job, thread) would race the dict. No such
caller exists today.
**Fix:** Add a one-line docstring note: "Must be called from the event
loop; dict access is not thread-safe."

### C-LOW-3 — Freshness sign-asymmetry between resolver and register

**File:** `custom_components/universal_room_automation/transit_validator.py:1116`
vs `camera_census.py:2801-2804`
**Bug class:** Inconsistent boundary handling.
**Severity:** LOW (only matters under clock skew / future-dated
timestamps).
**Scenario:** `_resolve_egress_face_identity` uses
`abs((timestamp - last_changed).total_seconds())`, so a future-dated
face is accepted. `_get_egress_face_ids_fresh` treats `age < 0` as
stale. Both correct in the happy path; the asymmetry could produce
subtly different behavior on NTP steps.
**Fix (nice-to-have):** pick one convention (recommend: treat negative
age as stale in both — real evidence should not be future-dated;
matches the census register's stance).

### Observed-safe (not a finding)

- **Empty-house restart** is intentionally covered by the
  `_egress_face_ids = {}` initializer. First post-restart crossing
  repopulates via the normal path. Matches plan §D1 live criterion.

---

## Summary table

| ID | Severity | Bug class | File | Status |
|---|---|---|---|---|
| C-MED-1 | MEDIUM | Test pollution / unrestored sys.modules | `quality/tests/test_egress_face_identity_d1.py:30-45` | Fix pre-deploy |
| C-LOW-1 | LOW | Untracked mutable growth (weak) | `camera_census.py:2790-2809` | At discretion |
| C-LOW-2 | LOW | Undocumented thread-safety contract | `camera_census.py:2767-2789` | At discretion |
| C-LOW-3 | LOW | Sign-asymmetric freshness | `transit_validator.py:1116` vs `camera_census.py:2801` | At discretion |

**No CRITICAL, no HIGH.** Fix C-MED-1 before deploy (test-suite
integrity); C-LOWs are reviewer-discretion.

## Verdict

**SHIP** after C-MED-1 is addressed. Lifecycle is clean (no listener /
task / scheduled callback added, no RestoreEntity surface, boot ordering
guarded, empty-on-restart is intentional and safe). D2 fence held.
Behavioral tests genuinely route through production; the C-CRIT-1
discriminator would fail on `:3495-3510` reversion. Injected clock,
no wall-clock coupling.

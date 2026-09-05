# v5.95.1 — Face-producer health gate self-heals the boot race

**Card:** IDENTITY-FACE-HEALTH-BOOTCACHE-1 (fast-follow to v5.95.0 identity fusion).
**Tier:** 2 (touches the D4 fail-safe primitive) — 2 framing-disjoint reviews (A local-correctness+FS-1, B lifecycle/perf) both SHIP + orchestrator independent mutation-verify (RED-on-neuter confirmed).

## Problem
The face-producer health gate resolves its Frigate status entity (`sensor.frigate_status_2`) via the entity registry once and cached the result **unconditionally** — including when it resolved to `None`. If URA's first census tick runs before `sensor.frigate_status_2` has acquired a state (a boot-ordering race — observed live 2026-09-05: census ran 08:00:24, the status sensor came up 08:00:45, a 21s lag), the gate cached `None` for the **whole HA session** and reported `frigate_status_missing_configured` (fail-CLOSED) forever, suppressing all face identity even though Frigate was running. It failed **safe** (never mis-named), but left face corroboration inert until a lucky restart.

## Fix
`_resolve_face_producer_health_entity` now latches its cache **only when resolution succeeded** (`resolved is not None`). While unresolved it re-runs the cheap registry+state lookup each census tick, so the moment `sensor.frigate_status_2` appears the gate self-heals to `live` on the next tick — no restart. Once a real id is latched, behaviour is unchanged (state-based up/down thereafter). FS-1 (configured-but-absent → fail-closed) and the `inert_no_frigate` one-time-WARNING path are byte-equivalent while unresolved.

## Reviews
- **A (correctness + FS-1):** SHIP — truth table over every `_is_face_producer_live` branch; verified no new under-suppress path (never reports live while Frigate down/absent), FS-1 fail-closed byte-equivalent, no re-resolve after successful latch, drill/strict untouched.
- **B (lifecycle/perf):** SHIP — bounded ≤8 dict-lookups/gate-call while unresolved, no listener/timer/await added, one-time WARNING not re-armed, reload resets flags, self-heals on the FIRST tick after the entity appears.
- **Orchestrator mutation-verify:** neutered the guard (`if True:`) → `test_bootcache_selfheal_when_frigate_status_appears_late` goes RED; restored → 24 fusion tests GREEN.

### Acceptance criteria
- **Verify:** at boot with `frigate_status_2` lagging the first census tick, the gate is fail-closed on tick 1, then flips to `live` on the first tick after the entity appears — no restart.
- **Test:** `test_bootcache_selfheal_when_frigate_status_appears_late` (RED on neuter).
- **Live:** after restart, `sensor.*_persons_in_house` `face_producer_health` reports `live` (not `frigate_status_missing_configured`) once Frigate is up.

## Non-goals
The `face_confirmed`/`face_persons` attribute rename (deferred), D1 sub_label bridge (root-cause priority, separate cycle), the flapping-veto (parked pending D1).

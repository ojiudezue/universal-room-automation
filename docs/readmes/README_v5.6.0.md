# URA v5.6.0 — Bathroom-Exhaust Intelligence + Humidity-Fan Unification (Tier 3)

Humidity/exhaust fans become **self-contained in rooms**. Previously two divergent paths owned them — the HVAC coordinator (`hvac_fans.py`, no sleep handling) for HVAC-coordinated rooms, and `automation.py` for the rest — which left an **orphan bug**: an HVAC-coordinated room with comfort-fan-control OFF had its humidity fans owned by *nobody*. This cycle removes the humidity path from `hvac_fans.py` entirely so `automation.py` is the **single owner** (invariant I1: exactly-one-owner), and layers on bathroom-grade intelligence: spike detection, usage-proportional purge, a wet-room flag, and a comfort-range scoring fix. Bundles the parked cover log-spam rate-limit fix.

## What ships (Tier 3)
- **D1 — decouple (invariant I1).** Humidity-fan discovery, `_evaluate_humidity_fan`, the max-runtime cap, and the humidity `RoomFanState` fields are deleted from `hvac_fans.py`. `automation.py::handle_humidity_based_fan_control` is the sole owner across the full toggle × house-state cross-product.
- **D2 — EMA humidity-spike detection.** Rate-of-rise catch (EMA baseline + Δ, default +10% over a ~45-min time-constant, OR an absolute 60% floor) so a high absolute threshold still trips on a shower spike. EMA constant + Δ are operator-tunable in a collapsed config section. (`window_min` baseline mode also available.)
- **D3 — presence/usage-proportional post-vacancy runtime.** Wet-room only: after vacancy the exhaust runs `min(base + per_min × occupied_minutes, cap)` seconds — longer visit → longer purge (the operator's Guest-Toilet pattern).
- **D4 — Wet Room flag (`CONF_WET_ROOM`).** Auto-true when `room_type == bathroom`; exempts the exhaust from the comfort-fan sleep-off so a 3 a.m. toilet still vents.
- **D5/D6 — surfaces.** New `Climate & Fans` config step with three toggles (HVAC-fan coordination / comfort fan control / **humidity fan control**), the Wet Room flag, spike + presence-runtime knobs in a collapsed `humidity_fan_advanced` section, and the climate entity + temps demoted into a `climate_backstop` section. New room-device entities: comfort/humidity fan-control switches, `Humidity Fan Should Run` + `Humidity Fan Active` binary sensors. Comfort-scope renames (`Comfort Fans On`, `Comfort Fan Should Run`) — slugs unchanged.
- **D8 — comfort-range scoring.** The per-room temps are reframed as a desired **comfort range**; `ComfortScoreSensor` + `EnergyEfficiencyScoreSensor` now score BOTH bounds (closes a Bug Class #53 where only the cool bound was read). `CONF_CLIMATE_ENTITY` + temps are KEPT (demoted, not removed) because `aggregation.py`'s zone-thermostat fallback depends on them.
- **The load-bearing decision — Option 2 (operator).** **Venting** (turn-on, off-threshold, EMA spike, presence-runtime, sleep-policy) requires the room's master automation **and** the humidity-fan toggle ON — ManualMode/master-off **suppresses** it. **The max-runtime safety cap fires universally**, independent of every toggle — URA's first explicit "ungated safety bound vs gated automation" split. The decision boolean lives in a pure, importable `_humidity_gate.py` so it's regression-tested.
- **Bundled:** cover log-spam rate-limit (`_get_available_covers` now logs unavailable covers on-change only, not every op — it flooded ~9.5k lines during a Hunter-Douglas gateway outage).

## Review — Tier 3 (4 framing-disjoint + 2 focused re-passes)
A (local correctness) · B (integration/state-machine + the I1 migration) · C (test authority via real per-site source mutation) · D (adversarial completeness, diff-blind). Round 1 = all FIX-FIRST. The fix-up resolved them but its structural changes **exposed two deeper gate leaks** (humidity trapped one gate up under master-automation; reload-seed below the cap so it couldn't fire on a boot-with-toggle-off fan) — caught by the focused C+D re-pass. A third pass closed an orchestrator-found gap: the coordinator gate boolean could regress `and`→`or` untested → extracted to `_humidity_gate.humidity_venting_enabled` with a truth-table test (mutating `and`→`or` now fails 2 named tests). Bug Class #53 (computed-but-not-consumed) hit **3×** in this cycle (dead D3 timer, unscored heat bound, gate-trapped call). Cycle tests 66/66; full suite at the 35-failed baseline (no new regressions); the +7 collection-order flakies the build introduced were eliminated.

---

## Shipwatch acceptance hypotheses (state oracle: HA recorder + room/CM entities)

**Immediate (post-restart — no-regression):**
- **H1 — deploy healthy + new surfaces exist.** `installed_version` = `v5.6.0`; the `Climate & Fans` config step renders; new room-device entities present (comfort + humidity fan-control switches, `Humidity Fan Should Run` / `Humidity Fan Active` binary sensors). Window: post-restart.
- **H2 — no humidity-fan regression.** Rooms with configured humidity fans still actuate on humidity; `hvac_fans.py` no longer touches humidity (comfort fans unaffected). No "owned by nobody" orphan. Window: post-restart + first humidity event.
- **H3 — no new URA errors / hoisted call clean.** The once-per-tick humidity handler runs without exceptions regardless of master-automation state; zero new URA ERROR entries at boot. Window: post-restart.

**Delayed (real bathroom use — the headline behaviors):**
- **H4 — spike + purge.** A shower with the spike enabled turns the exhaust on via EMA spike (or absolute), and in a wet room the exhaust keeps running a usage-proportional window after vacancy. Signal: `Humidity Fan Active` true through the purge; `humidity_fan_presence_runtime` log line. Window: next shower.
- **H5 — Option-2 gate boundary + universal cap.** Under ManualMode / master-off / humidity-toggle-off, venting does NOT start, but a fan already past `max_runtime` is still force-off'd by the safety cap. Largely in-suite-authoritative (gate cross-product); live-observable via the new binary sensors + `is_overridden`/toggle states.

## Live Validation — *(prospective; to be written back post-restart)*
- **L1 — deploy healthy:** `update.universal_room_automation_update` installed_version `v5.6.0`; new entities resolve; zero boot ERRORs. *(fill observed)*
- **L2 — decouple intact:** a configured humidity-fan room actuates on humidity; `hvac_fans` humidity-free. *(fill observed)*
- **L3 — gate + cap:** venting suppressed under master-off/toggle-off; cap still universal. *(in-suite-authoritative; note any live signal)*
- **L4 — behavioral (spike/purge):** deferred to a real shower window; note when observed. *(fill observed / window)*

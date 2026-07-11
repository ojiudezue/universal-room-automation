# URA v5.12.0 — Substrate re-subscribe on room add / remove / edit (Tier 2-DB)

**Restores the pre-v4.7.24 per-room-onboarding guarantee.** A newly added room is event-driven from the moment its ROOM entry loads — no restart required. This closes a 34-day regression the operator first felt on the "Master Bath Toilet" room (onboarded 2026-07-09 08:23, rode the ~34s room-coordinator poll instead of latching <3s).

## What was broken

v4.7.24 (2026-06-05, commit `e165e1cb`) centralized per-room `async_track_state_change_event` subscriptions into a single `OccupancySubstrate` built once at `PresenceCoordinator.async_setup`. That was correct as a substrate — but as an unintentional side effect it **removed the per-entry lifecycle hook** that the old per-room-coordinator subscription code provided for free at ROOM `async_setup_entry` time. Every existing ROOM entry pre-dated the substrate cycle, so the regression was invisible until the first ROOM entry was added **without** a subsequent HA restart.

Live symptom on the toilet room: median raw-motion → light latency ~11s, worst 34s (one drop). Comparable pre-fix rooms latched ~1.5s.

## What ships

- **`SIGNAL_ROOM_ENTRY_LIFECYCLE`** — a new dispatcher signal fired from ROOM `async_setup_entry`, `async_unload_entry`, and `_async_update_listener` (options edit). No config, no user-visible entity.
- **`OccupancySubstrate.refresh_subscriptions`** — atomic re-discovery + swap:
  - snapshots the pre-refresh live state map,
  - discovers the union of `CONF_MOTION_SENSORS ∪ CONF_MMWAVE_SENSORS ∪ CONF_OCCUPANCY_SENSORS` across all currently-LOADED ROOM entries via a **single shared discovery walk** (`_discover_entity_map`),
  - resets and re-seeds the per-kind buckets (`_kind_by_entity` and its motion / mmwave / occupancy siblings) from the fresh map so classification and subscription always agree,
  - installs the new listener set,
  - **then** emits synthetic edges only for entities whose live state differs from the snapshot (snapshot-delta), so a real event that arrives during the swap window is captured by the new listeners rather than lost.
- **`_refresh_lock`** guards the swap; **`_shutdown_sentinel`** (set under the lock) short-circuits any late-firing refresh during coordinator shutdown so no zombie listener leaks.
- **Cold-boot sweep** — presence coordinator does one unconditional `refresh_subscriptions` at the end of `async_setup` to absorb any lifecycle dispatches that raced construction.
- **Poll-gap canary** — a WARN emits when the substrate's subscribed set diverges from the observed poll-state entity set. Any future recurrence of the v4.7.24 pattern is now loudly visible instead of silent-slow.

**Invariant.** After any ROOM `ConfigEntry` transitions to LOADED, UNLOADED, or has its options updated, the substrate subscription set equals the union of Tier-1 sensor CONFs across LOADED ROOM entries — with no dispatch gap and no double-dispatch during swap — without an HA restart.

**No config changes.** Existing rooms behave identically; the fix is pure wiring.

## Review / gate (Tier 2-DB)

3 framing-disjoint reviews + validator + focused re-review, all green after `88c1acea`. Findings: 5 HIGH / 6 MED / 1 LOW, all fixed in-cycle. Canary tests were initially deferred by the builder as "orthogonal"; the orchestrator bounced the deferral — canary is the second half of the invariant (a recurrence must be loudly visible) and shipping without it would repeat the v4.7.24 blind spot. Two LOW backlog items filed as non-blocking (T2 canary regex brittleness; room-removal synthetic-False gap, pre-existing). Review doc: `docs/reviews/code-review/v5.12.0_substrate_resubscribe.md`. New bug-class recommendations for `QUALITY_CONTEXT.md`: **centralized subscription loses per-entry lifecycle hooks** and **test injects state production never writes**.

---

## Acceptance

```yaml
version: 5.12.0
hypotheses:
  - id: H1
    name: ura_v5120_deployed
    description: URA v5.12.0 is the running HACS-installed version and all entries load.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.12.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: substrate_no_gap_warn
    description: No substrate-gap canary WARN in steady state (post 5-minute settle).
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "substrate gap", period: 6h }
    expected: { condition: "==", value: 0 }
    window: { first_check_after: 30m, confirm_after: 6h, alert_if_violated_after: 24h }
  - id: H3
    name: no_error_storm
    description: No recurring URA error mentioning substrate / refresh_subscriptions.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "refresh_subscriptions", period: 24h, level: ERROR }
    expected: { condition: "==", value: 0 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
```

## Prospective Live Validation (to be filled in on `Validated <date>` post-restart)

| # | Criterion | Expected evidence |
|---|---|---|
| L1 | Deploy healthy | `installed_version = v5.12.0`; 40/40 loaded; zero post-boot URA errors mentioning `substrate` / `refresh_subscriptions`. |
| L2 | Rooms still event-driven post-restart | On a real walk-in to a pre-existing room (e.g. Kitchen, Master Bedroom, or the "Master Bath Toilet" room from the original repro), motion sensor → room-occupied latch is **<3s**, not the ~34s poll. Cite the entity_id of the source motion + the derived `binary_sensor.<room>_anyone_home` and the delta between their `last_changed` values. |
| L3 | **Acceptance test of record — organic** | The next NEW room onboarded **without a restart** latches <3s on first real walk-in. This is the definitive test for the cycle; nothing else proves the regression is closed. Note this explicitly in the write-back with the room name, config-entry id, and observed latch delta. |
| L4 | Canary quiet in steady state | Zero `substrate gap` WARNs in the last 6h of logs. |
| L5 | Options-edit picks up new sensor without restart | Add a sensor to an existing room's CONF list via options flow; without restart, a state change on that entity produces a room-occupied edge within one substrate cycle. Cite the entity_id added, options-flow save timestamp, and the first observed derived edge. |
| L6 | Zero errors mentioning substrate | Grep 24h post-restart logs for `ERROR.*(substrate|refresh_subscriptions)` → empty. |

A cycle is not closed until this section is rewritten as a `Validated <date>` table with observed evidence per row, per project protocol.

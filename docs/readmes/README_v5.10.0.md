# URA v5.10.0 — Music Following Hardening (Tier 2-DB)

Hardens the "music follows me" capability against the class of failures the operator flagged in July 2026: transfers during sleep, transfers into dead speakers that vanish the music without warning, transfers away from a room where someone else is still enjoying it, and per-person opt-out. Also lands cross-platform volume calibration, a faster same-platform join path, and observability so skipped transfers show a reason.

## Root causes (verified in source)

1. **No house-state gate.** `MusicFollowing` had no subscriber to `SIGNAL_HOUSE_STATE_CHANGED`. A transition at 2 AM would run the same code path as a transition at noon — including transferring music into a sleeping bedroom.
2. **Silent-actuator on target.** `_execute_transfer` checked the source `media_player`'s state but not the target's — a target in `unavailable` / `unknown` state fell through into `_transfer_media`, service calls no-op'd, verify failed silent-tail. Music disappeared from the source and never appeared at the target. Same pattern the v5.7.2 memory entry codified for lights/fans.
3. **No source-occupancy guard.** If two people were listening in the kitchen and one walked to the office, music followed the mover — dragged out of the room the other person was still in.
4. **No per-person opt-out.** All tracked persons were auto-enabled at setup with no user-facing switch.
5. **No same-platform fast path preference.** The room-media-player picker was alphabetical; a room with both a Sonos and a Linkplay could pick the cross-platform one and pay the slower `play_media` cost even when a native `join` was available.
6. **Cross-platform volume was raw-copied.** A Sonos at 0.35 handed to a Linkplay at 0.35 was frequently much louder or quieter — different platforms scale volume differently.
7. **Dead-speaker skips were invisible.** The Last Transfer sensor did not surface a reason when a transfer was blocked.

## What ships

- **D1 — Target availability pre-flight.** `_execute_transfer` now checks the target `media_player` state before any service call; records `target_unavailable`; does NOT fade source. `sensor.<room>_unavailable_entities` now also includes the room's `media_player` (extends the v5.7.2 actuator-visibility classifier).
- **D2 — House-state sleep/night gate.** Subscribes to `SIGNAL_HOUSE_STATE_CHANGED`. During `HouseState.SLEEP` with `CONF_MF_SLEEP_SUPPRESS` on → records `sleep_suppressed` and returns. `HouseState.HOME_NIGHT` has a three-way policy `CONF_MF_NIGHT_SUPPRESS_MODE`: **off** (default — allow), **block_all**, and **dwell_only** (currently behaves as block_all — see honest-limitations).
- **D3 — Source-occupancy guard.** Won't drag music out of a room where someone else is still present. Primary predicate: another tracked person whose `location` equals `from_room`. Secondary (untracked-guest coverage): `OccupancySubstrate` `occupancy` kind active on `from_room`. Motion and mmwave are **explicitly excluded** — residuals were producing false positives in review.
- **D6 — Stale-transition guard.** Under-lock check on transition timestamp age (`CONF_MF_STALE_TRANSITION_SECONDS`) — a transition that queued behind a lock and aged past the threshold is skipped and recorded, not fired stale.
- **D7 — Multiroom-platform preference in player resolution.** When resolving a room's media_player from HA Area membership, prefer the same platform family the source is already on (Sonos → Sonos, Linkplay → Linkplay), so the native `join` path wins over the generic `play_media` path.
- **D8 — Cross-platform volume scaling.** Per-room `room_media_volume_scale` (default 1.0). Applied on the cross-platform `play_media` path only; same-platform `join` unaffected.
- **D9 — Per-person "Follow Me" switches.** `switch.music_following_<person>` on the `URA: Music Following Coordinator` device. RestoreEntity round-trip; single-owner via `MusicFollowing._person_follow_prefs`. OFF blocks transfers for that person only.
- **D11 — Same-platform join verify skip.** The `join` path is instant; the post-transfer verify sleep is now skipped on that path.
- **D12 — Observability.** `MusicFollowingLastTransferSensor` now exposes `last_skip_reason` and `last_skip_from_room` attributes. `MusicFollowingHealthSensor` counters include `sleep_suppressed`, `night_suppressed`, `target_unavailable`, `source_has_others`, `stale_transition`.

## Config surfaces (where each new field lives)

- **CM → Music Following step:** `CONF_MF_SLEEP_SUPPRESS` (bool, default True), `CONF_MF_NIGHT_SUPPRESS_MODE` (select: off / block_all / dwell_only, default **off**), `CONF_MF_STALE_TRANSITION_SECONDS` (Number field, default 15).
- **Per-room → Media step:** `room_media_volume_scale` (Number field, default 1.0, range 0.25-2.0).
- **Per-person entities (auto-created on CM):** `switch.music_following_<person>` on the Music Following Coordinator device.

## Honest limitations

- **`dwell_only` night mode does not yet do dwell-based routing.** The predicate depends on a per-person "bedroom" mapping surface that URA does not yet expose. Selecting `dwell_only` today behaves as `block_all` and emits a one-shot WARNING on first hit. Kept selectable so the option exists for the follow-up cycle that lands the bedroom mapping.
- **Adding or removing a person from `CONF_TRACKED_PERSONS` requires a Coordinator Manager reload** for the corresponding `switch.music_following_<person>` to appear or disappear. No live add/remove hook today.
- **C10 — restart cooldown window.** The per-person + target cooldown map is RAM-only; teardown wipes it. A rapid restart within a few seconds of a transfer could allow one duplicate transfer inside the 8s window. Low real-world exposure; not fixed in this cycle.
- **TTS collision suppression (D10) dropped.** Depends on a producer signal (`SIGNAL_TTS_STARTING`) that does not exist in the codebase yet. Backlogged with the producer.

## Review / gate (Tier 2-DB)

3 framing-disjoint reviews (A local-correctness / B lifecycle+races / C surfaces+test-authority) + validator + focused post-fix re-review. **3 CRITICAL, 4 HIGH, 6 MEDIUM, 6 LOW found; all CRITICAL/HIGH/MEDIUM fixed except C-M1 accepted+documented (person add/remove needs CM reload).** Headline pattern: three of the CRITICALs were **"mechanism built, wire missing"** — gates that read data sources with no writer on the producing side (sleep-gate seed key, D3 substrate key, dwell mode's bedroom key). Fix-up added writer citations at every cross-coordinator read; the sleep-gate anchor test now fails on writer removal (red/green verified). Review doc: `docs/reviews/code-review/v5.10.0_music_following.md`. New bug-class recommendation filed for QUALITY_CONTEXT.md: **"cross-coordinator read without a verified writer."**

**Invariant this cycle ships:** during `HouseState.SLEEP` with `CONF_MF_SLEEP_SUPPRESS = True`, MF makes ZERO `media_player.*` service calls in ANY reachable path — including immediately after a restart into SLEEP.

---

## Acceptance

```yaml
version: 5.10.0
hypotheses:
  - id: H1
    name: ura_v5100_deployed
    description: URA v5.10.0 is the running HACS-installed version and all entries load.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.10.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: mf_sleep_suppress_active
    description: MF sleep-suppress config lands and the coordinator reports the current house state on its device.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.universal_room_automation_music_following_health, attribute: current_house_state }
    # 2026-07-13: oracle repaired — attribute now emitted (commit d004820f) and entity id corrected; was unevaluable as originally written.
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
  - id: H3
    name: no_mf_error_storm
    description: No recurring MF error after the cycle.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "music_following", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
```

## Live Validation — Validated 2026-07-10

Combined release v5.11.0 shipped both this cycle and the OC Hardening cycle. HA restarted 2026-07-10 17:32 CDT; validation window 17:40-18:05 CDT.

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L0a | **MF coordinator + observability attrs present.** | PASS | `sensor.universal_room_automation_music_following_health` state=`idle` with `sleep_suppressed_today=0`, `night_suppressed_today=0`, `source_has_others_today=0`, `stale_transition_today=0`, `target_unavailable_today=0`, `last_skip_*` attrs present; `sensor.ura_music_following_coordinator_music_following_last_transfer` exists (state=`none` pre-first-transfer). |
| L0b | **Per-person Follow-Me switches restored.** | PASS | 4 switches (`ezinne` / `jaya` / `oji_udezue` / `ziri`) all state=`on`; health sensor `active_followers` lists all 4. |
| L0c | **New CONF fields persisted through options flow.** | IN-SUITE-ONLY | New CONFs absent from CM options (operator hasn't re-submitted the options flow); code reads safe defaults (`sleep_suppress=True`, `night=off`, `stale=15s`) and behavior is correct at defaults. Form round-trip proven in-suite. |
| L0d | **Sleep-gate state post-restart (armed but not fired).** | PASS (armed-open) | `current_house_state == home_day` → gate correctly open, zero spurious suppressions observed. Restart-into-SLEEP proof deferred to L2. |
| L0e | **Dead-media_player surfaced via D1 visibility.** | PASS | `sensor.kitchen_unavailable_entities` = 1 with `unavailable_actuators=[media_player.kitchen_2]`, `roles=[room_media_player]`, `reason=entity_missing`; `master_bedroom` analog with `reason=offline_since_restart`. |
| L0f | **Zero MF-mention ERRORs since restart.** | PASS | system log ERROR search for `music_following` → 0. |
| L1 | **Sleep walk-through blocks all transfers.** House in `HouseState.SLEEP`, walk through 2+ rooms carrying phone → zero transfers, `sensor.music_following_health` attr `sleep_suppressed` counter increments per suppressed transition. | PENDING-ORGANIC | Tonight's sleep cycle. |
| L2 | **Restart during SLEEP: gate still blocks.** Restart HA while in SLEEP; first mid-sleep transition increments `sleep_suppressed` (not `success`). C-CRIT-1 regression in live form. | PENDING-ORGANIC | Next natural mid-sleep restart. |
| L3 | **Per-person switch OFF blocks that person only.** Toggle `switch.music_following_<person>` OFF; that person's transitions produce no transfer; others still transfer. | PENDING-ORGANIC | Needs a natural transfer event; `transfers_today=0` at validation time. |
| L4 | **Dead-speaker target visible.** `sensor.music_following_last_transfer.last_skip_reason == "target_unavailable"`, `last_skip_from_room` set. | PENDING-ORGANIC | Needs a natural transfer attempt into a dead target; static visibility already proven at L0e. |
| L5 | **Second person in source room blocks the drag.** `last_skip_reason == "source_has_others"`. | PENDING-ORGANIC | Needs a natural two-person listening + walkaway. |
| L6 | **Same-platform handoff feels faster.** | PENDING-ORGANIC | Needs a natural Sonos↔Sonos handoff. |
| L7 | **No URA ERROR mentions of `music_following` over 24h.** | PENDING | Due 17:32 CDT 2026-07-11. |

**Validation notes.** `media_player.kitchen_2` `entity_missing` is **pre-existing** — the entity was already emitting `unavailable_entities` WARNINGs before deploy. The new D1 classifier correctly *surfaces* the pre-existing dead actuator; it did not cause it. Boot-only transients dismissed. `transfers_today=0` at validation is expected — MF only acts on organic transitions, so L3-L6 land as PENDING-ORGANIC.

### Organic follow-up — Validated 2026-07-12 (recorder-based, read-only)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Sleep walk-through blocks all transfers | **PASS (invariant) / gate UNEXERCISED** | Only post-deploy sleep window: 2026-07-10 22:00:02 → 07-11 06:00:09. Across 55 recorder rows of `music_following_health` attrs in that window: `transfers_today=0` in every row, `last_transfer_result=ping_pong_suppressed` throughout; `music_following_last_transfer` never changed state (no `success` anywhere post-deploy). **But `sleep_suppressed_today=0` in all rows** — every overnight transition (~55, mmWave bedroom↔bathroom churn) was suppressed *upstream* by the ping-pong guard (`transitions.py:231`; suppressed transitions never reach MF per `transitions.py:624`), so the D2 gate (`music_following.py:685`, correctly ordered before cooldown/lookup/service call at :683-696) was never reached. Strong form (`sleep_suppressed` increments) remains **PENDING-ORGANIC**: needs a genuine non-ping-pong walk (e.g. bedroom→kitchen) during sleep. Night 07-11→07-12 had NO sleep window — house held `guest` 20:57→06:05 (flagged to operator). |
| — | **CORRECTION to L0d + H2 (2026-07-12)** | **L0d evidence RETRACTED** | H2's oracle attribute `sensor.music_following_health.current_house_state` **does not exist**: `get_diagnostic_data()` (`music_following.py:363-392`) never emits it; internal `_current_house_state` is DEBUG-log-only (`music_following.py:255-258`); repo-wide grep finds no writer; live sensor confirms absence. The L0d row's "`current_house_state == home_day`" could not have been read from this sensor — L0d stands as PASS only on its *zero-spurious-suppressions* half. **Follow-up filed:** add `current_house_state` to `get_diagnostic_data()` and re-point/repair H2 (as written, H2 can never be evaluated by Shipwatch). |

---

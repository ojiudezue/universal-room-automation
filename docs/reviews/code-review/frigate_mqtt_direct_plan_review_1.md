# Plan review 1: PLANNING_frigate_mqtt_direct_2026_11.md (PERIMETER-FRIGATE-MQTT-DIRECT-1)

Reviewed: commit b3c83b3e (rev 1). Mode: one adversarial plan review, Tier 2-DB (operator-elevated).
Code base checked: `develop` @ c84fb384. Frigate integration: `/Users/okosisi/ha-config/custom_components/frigate/` v5.15.6, read-only.
HVAC/presence state-of-play docs: not applicable (no HVAC or presence-sensor surface touched; perimeter/Frigate ingress only).

**Verdict: FIX-PLAN-FIRST.** Fixes applied in the plan as rev 2 (same file). After rev 2 the plan is BUILD.

## What held up (verified, not trusted)

| Claim | Result | Evidence |
|---|---|---|
| Census soft-subscribe pattern | Verified | `camera_census.py:5243-5278` lazy import, try/except, idempotent teardown; `__init__.py:2952-2995` `async_when_setup(hass,"mqtt")` with `is not census` liveness guard and the no-`after_dependencies` comment. |
| Census prefix resolver is broken (F1) | Verified | `camera_census.py:5280-5299` reads `topic_prefix`/`mqtt_topic_prefix`/`mqtt_topic` from entry options/data, falls back to literal `frigate` (:5258). The Frigate integration never stores those keys there. |
| `topic_prefix` lives at `hass.data["frigate"][entry_id]["config"]["mqtt"]["topic_prefix"]` | Verified | frigate `__init__.py:353` `config = await client.async_get_config()`; :372 `config["mqtt"]["topic_prefix"]`; :378-385 `hass.data[DOMAIN][entry.entry_id] = {..., ATTR_CONFIG: config, ...}`; `const.py:34` `ATTR_CONFIG = "config"`. Caveat: populated only after a successful setup (:355 `ConfigEntryNotReady` path leaves it absent) and popped on unload (:618). See H3. |
| Consumer enumeration | Verified complete | `git grep` on develop: `frigate_events` listeners only at `perimeter_alert.py:971` and `exterior_track_linker.py:272`; only MQTT subscribe is `camera_census.py:5261`. No HA-side automation/script consumes `frigate_events` (grep of `/Users/okosisi/ha-config/*.yaml`: only the producer, plus a recorder exclude at `configuration.yaml:41`). Frigate's own `WSEventProxy` (`ws_proxy.py:107`) subscribes `<prefix>/events` for its websocket API; it fires no bus event, so it is not a consumer and not a collision. |
| Bridge mapping | Verified | `automations.yaml:6578-6595`: triggers `frigate/events` + `frigate2/events`; `event_data` keys before/after/type with `default({})`/`default('')`; `mode: queued`, `max: 25`. The plan's normaliser matches this key-for-key. |
| F2 (`(id,type)` dedup is wrong) | Agreed | Many `update` messages share `(id,"update")`. |
| Line anchors | Minor drift | Linker construction is `__init__.py:3550`, not :3567; linker listen is :272, not :266. Fixed in rev 2. |

## Findings

### H1 (HIGH): "id-less messages are harmless, consumers ignore them" is false
Perimeter `_on_frigate_event` (`perimeter_alert.py:967` on develop c84fb384) calls `self._note_frigate_event(cam_key, msg_type, after)` **before** it looks at `event_id`, so an id-less person message on a known camera updates the D2 cache and appends to `_frigate_bus_times`. The linker `_on_frigate` (`exterior_track_linker.py:245-266`) calls `observe(..., event_id=None, ...)`. Under rev 1 §3.3, an id-less message is dispatched from **both** sources, so each consumer sees it twice. That breaks INV-1 directly, inflates the D2 window count, and opens a second linker observation.
Frigate does not normally emit id-less events, so this is a latent path, but INV-1 says "any reachable path" and the plan asserts something untrue about the consumers.
**Fix (rev 2):** id-less messages are dispatched from one family only: MQTT when at least one MQTT subscription is live, otherwise bus. Counted as `idless`. Test added.

### H2 (HIGH): the D0 gate sizes the TTL with the wrong metric
Rev 1 sizes `FRIGATE_INGRESS_SOURCE_LATCH_TTL_S` from "max gap between consecutive messages of one event id". Walk the latch:
- Same-family messages refresh the latch, so long gaps only let the latch expire. After expiry, the next message relatches to whichever family arrives first (MQTT here) and the bus twin is dropped. Long gaps are harmless.
- What breaks INV-1 is a bus twin that arrives **after** the latch expired, because it then relatches to bus and is dispatched a second time. The bound that matters is the **maximum bus lag behind MQTT** (automation queue latency, D0 item 2), not the inter-message gap.
- The TTL is also the failover dead time: when the owning family stops, the other family's copies are dropped for up to TTL. At 600 s that means a whole short event, `end` included, can be lost. Losing `end` matters: `_frigate_ended_event_id` is not set, so SNAP-1 edge capture (v5.107.2 Fix C) could pick an ended id as current.
**Fix (rev 2):** the TTL must be larger than the D0-measured p100 bus lag with margin, and as small as possible otherwise. Provisional default 30 s; D0 reports max lag; gate: `TTL >= 3 × max observed lag` and at least 10 s. Gap measurement stays in D0 for information only.

### H3 (HIGH): reconcile-driven unsubscribe makes the TTL failover self-inflicted
On this house both sources ride the **same** HA MQTT client (the bridge is an `mqtt` trigger). Broker loss stops both at once; there is no independent-failure case where the bus outlives MQTT. The only realistic way the MQTT family stops mid-event while the bus continues is URA unsubscribing itself. Rev 1 §3.4 does exactly that: `async_reconcile` "unsubscribe[s] removed" prefixes. Frigate's `async_unload_entry` pops `hass.data["frigate"][entry_id]` (:618) and a reload, or a `ConfigEntryNotReady` retry loop, leaves it absent. A periodic reconcile landing in that gap unsubscribes `frigate2/events`. In-flight ids stay latched to MQTT, so their bus copies are dropped for TTL, and the MQTT sub returns only at the next reconcile (up to 300 s).
**Fix (rev 2):** subscriptions are add-only for the ingress lifetime. A prefix that disappears from discovery stays subscribed; a subscription to a topic nobody publishes on costs nothing. Unsubscribe happens only at ingress teardown. Test: `test_frigate_unload_gap_keeps_subscription`.

### M1 (MED): INV-3 overstates byte-identity
INV-3 says alert text, snapshot id, D2 record and linker tracks are unchanged, with "earlier arrival" as the only difference. But earlier arrival is a behavioural difference: it changes interleaving with the other inputs these consumers race against. SNAP-1 edge capture reads `_frigate_last_event_id` at the person-binary-sensor rising edge, so an id cached earlier can change which snapshot id an alert carries (probably for the better). Linker `observe` stamps `dt_util.now()`, so track-merge windows see different times. The replay test in D3 also has to exclude every arrival-time stamp: the `utcnow()` in the `_frigate_last_event_id` tuple (`perimeter_alert.py:965`), `received_at`, `_frigate_bus_times` values and linker `now`. Rev 1 only excluded `received_at`.
**Fix (rev 2):** INV-3 restated as per-consumer message-sequence identity, with arrival-time stamps excluded. Cross-input interleaving is declared an accepted, expected change. D3 exclusions enumerated.

### M2 (MED): L3's ±10% discriminator is ambiguous
MQTT recovers messages the bridge drops when its queue passes `max: 25`, so `frigate_events_24h` can rise for a legitimate reason. A +10% band would then misread a working fix as a failure.
**Fix (rev 2):** L3 uses the D0 item 3 overflow rate. Pass: ratio below 1.5 and consistent with pre-rate × (1 + overflow fraction). Double-feed shows as about 2×. L2 (`dedup_dropped ≈ bus_24h`) stays the primary discriminator, with `bus_24h` defined as bus messages **received**, before dedup.

### M3 (MED): TTL 0 as "disables dedup" is a footgun on the knob
On a house with the bridge, `0` means guaranteed double-feed. A kill-switch value should fall back to today's behaviour, not to a broken state.
**Fix (rev 2):** `FRIGATE_INGRESS_SOURCE_LATCH_TTL_S` has no disable value; values below 10 clamp to 10. The kill switch is `FRIGATE_INGRESS_MQTT_ENABLED=False` alone.

### M4 (MED, verify-in-build): MQTT entry reload and subscription survival
`async_when_setup(hass, "mqtt")` fires once. Whether a subscription made with `mqtt.async_subscribe` survives a reload of the **MQTT config entry** was not verified here. I have not read `homeassistant/components/mqtt` for this, and the census face bridge carries the same exposure. If subscriptions do not survive, the MQTT family goes silent while bus traffic also continues through the re-subscribed automation trigger. That is the H2 failover, bounded by the TTL, and with no re-subscribe ever.
**Fix (rev 2):** the builder must verify this against the installed HA core source before writing §3.4 and cite file:line. If subscriptions do not survive, periodic reconcile also re-subscribes whenever the MQTT family has been silent for more than `FRIGATE_INGRESS_RECONCILE_S` while the bus family is active. Logged as an open question in §3.4.

### L1 (LOW): late-Frigate hook timing
`async_when_setup(hass, "frigate")` fires on component load. If the Frigate entry hits `ConfigEntryNotReady`, the prefix appears only after a later retry, and only the periodic reconcile (300 s) catches it. That is acceptable because the bus covers the gap. Documented, no change.

### L2 (LOW): D0 does not say whether it gates go/no-go or only details
The build exists for portability, an operator mandate, so D0 cannot cancel it. It can still block the build, and rev 2 now says so: the build is blocked until equality is 100% after normalisation and the TTL inequality holds.

## Checklist answers
- **Prior-art scan:** complete and accurate. Add `WSEventProxy` as a checked non-collision.
- **Consumers:** two, as claimed. No third consumer exists in URA or in the HA YAML.
- **Prefix location:** correct, with the lifetime caveat (H3).
- **Payload mapping:** matches the automation. D0 equality remains the proof for INV-3.
- **Dedup:** the latch holds for reordering and for boot (bus-first id stays on bus). It failed on id-less messages (H1), TTL sizing (H2) and self-inflicted flap (H3). A bus-only `end` inside the TTL is lost; H2+H3 shrink that window to the measured lag.
- **INV-3:** holds only as sequence identity (M1).
- **Load order:** mqtt late OK (census pattern). Frigate late OK via periodic (L1). Frigate reload broken by unsubscribe (H3), fixed. URA reload OK (double-setup guard + liveness). MQTT entry reload unverified (M4).
- **Knob ladder:** all rung 1, appropriate. TTL 0 semantics fixed (M3).
- **D0 gating:** gates details, not existence; wrong TTL metric fixed (H2, L2).

## Summary

| Severity | Found | Fixed in plan rev 2 |
|---|---|---|
| HIGH | 3 | 3 |
| MED | 4 | 4 (M4 as a mandatory verify step in the build) |
| LOW | 2 | 2 (documented) |

Bug-class tags: H1 = false consumer-behaviour assumption (Producer/Consumer asymmetry); H2 = wrong-metric gate; H3 = self-inflicted source flap / suppression without discharge; M1 = over-claimed invariant; M3 = kill switch that lands in a broken state.

# PLANNING: Frigate events direct from MQTT (PERIMETER-FRIGATE-MQTT-DIRECT-1)

Card: `PERIMETER-FRIGATE-MQTT-DIRECT-1` (kanban.data.yaml:383). Arc: perimeter-identity-arc-2026-11.
Supersedes the parked D9 in `PLANNING_perimeter_fp_build_2026_11.md:532-542`.
Operator 2026-11-08: "URA listening to Frigate MQTT is essential for portability, which is imperative."
Status: plan rev 2, not built. Tier 2-DB (see §8). Rev 2 applies plan review 1 (`docs/reviews/code-review/frigate_mqtt_direct_plan_review_1.md`: H1-H3, M1-M4, L1-L2).

---

## 0. Institutional context verified

### 0.1 Prior-art scan (code)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Soft MQTT subscribe (import inside try, no manifest dep) | **REUSE pattern** | `camera_census.py:5243-5278` `async_register_frigate_face_listener`: lazy `from homeassistant.components import mqtt`, `await mqtt.async_subscribe(...)`, inert on any exception, idempotent (tears down first). |
| Late-load re-register when mqtt loads after URA | **REUSE pattern** | `__init__.py:2952-2995`: eager register, then `homeassistant.setup.async_when_setup(hass, "mqtt", cb)` with a liveness guard (`hass.data[DOMAIN]["census"] is not census → return`, D2-MED-1) so a torn-down owner never re-subscribes. Comment at :2955-2957 already forbids `after_dependencies: ["mqtt"]`. |
| Unload teardown of an MQTT unsub | **REUSE pattern** | `__init__.py:5826-5836` + `camera_census.py:5301-5315`. |
| Topic-prefix discovery | **NEW helper; existing one is broken** | `camera_census.py:5280-5299` `_resolve_frigate_topic_prefix` reads `topic_prefix` from the Frigate **config entry data/options**. Those keys do not exist: the live Frigate entry (`01KM239Z8ZQWQTN1D9CV5JRA7V`, "Frigate 2") holds only `url/username/validate_ssl` + UI options (read from `.storage/core.config_entries`). The Frigate integration fetches the prefix from the server at setup and stores it in `hass.data["frigate"][entry_id]["config"]["mqtt"]["topic_prefix"]` (`/config/custom_components/frigate/__init__.py:372,378-381`, v5.15.6). The new helper reads that. See finding F1. |
| `frigate_events` bus listener, perimeter | **REUSE as fallback source** | develop `perimeter_alert.py:928-973` (`_on_frigate_event`, `self.hass.bus.async_listen(FRIGATE_EVENTS_BUS_EVENT, ...)`), teardown :1210-1215. |
| `frigate_events` bus listener, linker | **REUSE as fallback source** | `exterior_track_linker.py:238-275` (`_on_frigate`, listen :272), constant :53. |
| D2 cache + bus-silent WARN | **REUSE, extend counters** | develop `perimeter_alert.py:4416-4470` (`_note_frigate_event`, `_append_window`, `_note_frigate_leg_edge`); knobs `PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES`, `PERIMETER_FRIGATE_BUS_WINDOW_S` (const.py ~2514). |
| A single Frigate ingress object | **NEW** | `grep -rn "INGRESS\|frigate_ingress\|FRIGATE_MQTT" custom_components/universal_room_automation/*.py` → no hits. |
| Event dedup across sources | **NEW** | No existing Frigate event dedup; linker has per-track merge only. |
| Frigate's own `WSEventProxy` | **Checked, not a collision** | frigate `ws_proxy.py:107` subscribes `<prefix>/events` for its websocket API and fires no bus event. Not a `frigate_events` consumer. |

Greps run (develop HEAD c320c8f3, includes v5.107.1/2/3):
```
grep -rn "frigate_events\|mqtt\|MQTT" custom_components/universal_room_automation
  -> only two frigate_events bus listeners: perimeter_alert.py:971, exterior_track_linker.py:266
  -> only one MQTT subscription: camera_census.py:5261 (topic <prefix>/tracked_object_update)
manifest.json dependencies: http, frontend, logbook (no mqtt, no after_dependencies) — keep it so.
custom_components/frigate/manifest.json dependencies: http, media_source, mqtt
```
camera_census has no `frigate_events` read; its only MQTT read is the face bridge (different topic, out of scope, §7).

### 0.2 Plans, memory, docs consulted
- `PLANNING_perimeter_fp_build_2026_11.md` D2 (:258-283) and D9 (:532-542), full read of both.
- `PLANNING_frigate_face_name_bridge_2026_09.md` (source of the soft-MQTT pattern), filename/headers.
- `PLANNING_frigate_down_tripwire.md`, `AUDIT_frigate1_retirement_inventory.md` (filenames; Frigate-1 retired, `_2` permanent).
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (:143-146 prefixes `frigate`/`frigate2`, client ids split; no other MQTT doctrine). Read for this domain.
- Memory `project_frigate_mqtt_topic_collision` (resolved 2026-08-12: prefixes split, `frigate` = retired F1, `frigate2` = F2).
- Memory `project_envoy_boot_incident_2026_06_12` (Failure A: `after_dependencies` stranding cancelled all 40 entries).
- Bridge automation `/Users/okosisi/ha-config/automations.yaml:6578-6595`, read-only.

### 0.3 Config-first
No setting makes URA independent of the house automation: the bus listener is the only ingress, and nothing in options flow selects a source. Code is required. (On *this* house nothing is broken; the driver is portability.)

### 0.4 Findings from the scan
- **F1 (real, adjacent).** The census face-bridge prefix resolver can never succeed (keys absent), so it always falls back to the literal `frigate`. Frigate-1 (`frigate`) is retired; Frigate-2 publishes on `frigate2`. The face bridge is therefore very likely subscribed to a dead topic. Not verified live in this plan (the `frigate_face_msg_*` attrs were not on the census sensors I checked); D0 verifies it from the INFO line `frigate-face bridge: subscribed to %s`. The new helper in D1 is the fix. Rewiring the face bridge changes census behaviour, so it is a **separate card**, not this cycle (§7).
- **F2 (operator spec correction).** "Dedupe by event id plus event type" is wrong for Frigate: one event emits many `update` messages with the same `(id, "update")`. Keying on that pair would drop every update after the first, freeze D2's cached score/zones, and change the alert gates' inputs. That breaks the byte-identical constraint. §3.3 uses a per-event-id **source latch** instead.
- **F3.** Live: one Frigate entry, one live prefix (`frigate2`). The bridge still also listens on `frigate/events`, which is dead since Frigate-1 retired. Discovery from the loaded entries yields `{frigate2}` only.

---

## 1. Falsifiable invariants

- **INV-1 (exactly-once).** For every Frigate `events` message M, each registered consumer (perimeter `_on_frigate_event`, linker `_on_frigate`) is invoked **at most once** for M, whatever combination of sources delivers it (bus only, MQTT only, both, both with either arriving first). Broken by: any reachable path in which one consumer sees the same `(id, type, after)` twice from different sources.
- **INV-2 (no loss when one source lives).** If at least one source delivers M, each consumer is invoked for M, except when the other source has fed the same event id within `FRIGATE_INGRESS_SOURCE_LATCH_TTL_S` (the accepted cost of the latch, §3.3).
- **INV-3 (sequence-identical here; rev 2).** On this house (bridge + MQTT both live), the sequence of `{type, before, after}` mappings each consumer receives equals the sequence the bus alone delivered before this change, plus any messages the bridge queue dropped (`max: 25`). Arrival-time stamps are excluded from the comparison. **Accepted change, not a violation:** messages arrive earlier, so their interleaving with other inputs shifts. In particular SNAP-1 edge capture may see an event id cached earlier and pick a different (fresher) snapshot id, and linker `observe` timestamps shift. Alert text and snapshot ids are therefore NOT claimed unchanged.
- **INV-4 (no hard dependency).** With mqtt not installed, not loaded, or loading after URA, URA setup completes with no exception and no wait, and the bus path behaves exactly as today.

Reviewer D: falsify these, INV-1 especially, across setup/reload/late-mqtt/late-frigate orderings.

## 2. Producer and consumer checks

**Value: a Frigate `events` message.**
- *Producer, MQTT:* Frigate publishes JSON `{"type": "new"|"update"|"end", "before": {...}, "after": {...}}` on `<topic_prefix>/events`. Prefix healthy live: `frigate2` (memory, manual :143-146).
- *Producer, bus (today):* house automation `automations.yaml:6578-6595` triggers on MQTT and fires `frigate_events` with
  `before: '{{ trigger.payload_json.before | default({}) }}'`, `after: '{{ ... .after | default({}) }}'`, `type: '{{ ... .type | default('') }}'`, mode `queued`, `max: 25`.
  Dependency health: the automation's queue drops messages above 25 in flight (a busy multi-camera scene can exceed this). `default()` without `true` fires only on **undefined**, so a JSON `null` passes through as `None`. HA native template rendering returns the dict via `literal_eval(repr)`, which round-trips str/int/float/bool/None/list/dict exactly. D0 confirms equality on live data rather than trusting this reading.
- *Exact MQTT→bus mapping (D1 normaliser):*
  ```
  p = json.loads(payload)            # non-dict / invalid JSON -> drop, count "mqtt_bad_payload"
  data = {
      "before": p["before"] if "before" in p else {},
      "after":  p["after"]  if "after"  in p else {},
      "type":   p["type"]   if "type"   in p else "",
  }
  ```
  Key order matches the automation (before, after, type). No other keys; the bus event carries none.

**Consumers (all trust-decision unless noted):**
| Consumer | file:line (develop) | Reads |
|---|---|---|
| Perimeter snapshot id cache `_frigate_last_event_id` | perimeter_alert.py:965; read :2078, :3773 | `after.id/camera/label`, `type` |
| Perimeter ended-id `_frigate_ended_event_id` (v5.107.2 SNAP-1 Fix C) | perimeter_alert.py:~960 | `type == "end"`, `after.id` |
| D2 cache `_frigate_event_cache` + `_frigate_bus_times` | perimeter_alert.py:4416-4428; read :4483-4485, :4647 (D3+ gates) | `_FRIGATE_EVENT_FIELDS` of `after` |
| D2 bus-silent WARN (display/trip-wire) | perimeter_alert.py:4441-4470 | count of `_frigate_bus_times` |
| Exterior track linker `observe` | exterior_track_linker.py:243-264 | `after.label/camera/id/score/sub_label`, `type` |

## 3. Design

### 3.1 One ingress: `frigate_ingress.py` → `FrigateEventIngress`
Owned at `hass.data[DOMAIN]["frigate_ingress"]`, created in the parent entry **before** `PerimeterAlertManager` (`__init__.py:3490`) and the linker (`:3550`). API:
- `register_consumer(name, fn)` → unregister callable. `fn(data: Mapping, source: str)` is sync, `@callback`-safe.
- `_dispatch(data, source)`: dedupe (§3.3), then call each consumer in its own `try/except` so one consumer's exception cannot starve the other.
- Sources: `"bus"` (one `hass.bus.async_listen("frigate_events", ...)`) and `"mqtt:<prefix>"` (one subscription per discovered prefix).

### 3.2 Prefix discovery (no hard-coding)
`discover_frigate_topic_prefixes(hass) -> set[str]`: for each `hass.config_entries.async_entries("frigate")` in state LOADED, read `hass.data.get("frigate", {}).get(entry_id, {}).get("config", {}).get("mqtt", {}).get("topic_prefix")`; keep non-empty strings, strip trailing `/`. All access defensive (`.get`, isinstance); any exception → empty set. Empty set = MQTT path inert, bus path unchanged. No literal fallback (a literal `frigate` is exactly F1's failure).

### 3.3 Dedup and precedence: per-event-id source latch, first source wins
`_latch: dict[event_id, (source_family, last_seen_monotonic)]`, `source_family ∈ {"bus","mqtt"}`.
- Message with no `after.id` → dispatched from **one family only**: MQTT when at least one MQTT subscription is live, otherwise bus; the other family's id-less copies are dropped. Counted (`idless`). (Rev 2, H1: consumers do NOT ignore id-less messages. Perimeter calls `_note_frigate_event` before checking the id, at `perimeter_alert.py:967` (develop c84fb384), and the linker calls `observe(event_id=None)`. Dispatching from both sources would double-feed.)
- id not latched, or latch expired → latch to this family, dispatch.
- id latched to **this** family → refresh timestamp (sliding), dispatch.
- id latched to the **other** family → drop, increment `dedup_dropped[family]`.

Why this, not a content hash or `(id, type)`: same-source messages are never deduped, so the update stream stays intact (F2). Within one family the stream is ordered (MQTT per topic, the automation queue FIFO), so feeding one family per event id gives the same sequence the bus gave alone. A content hash would depend on template round-trip fidelity across every field. **Precedence:** whichever arrives first. Here that is MQTT (no automation hop), so MQTT effectively wins and the bus is the fallback, without a mode switch. If the MQTT subscription drops mid-event, the bus takes over for that id once the winning family has been silent for `FRIGATE_INGRESS_SOURCE_LATCH_TTL_S`; bus copies inside that window, `end` included, are lost (INV-2 cost).
**TTL sizing (rev 2, H2).** Long gaps within one family are harmless: the latch expires and the first-arriving family relatches. INV-1 breaks only if a bus twin arrives **after** its latch expired. So the TTL must exceed the maximum bus lag behind MQTT (D0 item 2) with margin, and otherwise be as small as possible, because it is also the failover dead time. Gate: `TTL >= max(10, 3 × D0 max lag)`.
**Shared client caveat (rev 2, H3).** Here both sources ride the same HA MQTT client (the bridge is an `mqtt` trigger), so broker loss silences both together. The only realistic one-sided MQTT stop is URA unsubscribing itself, which §3.4 now forbids at runtime.
Bound: prune expired entries on each insert; hard cap `FRIGATE_INGRESS_LATCH_MAX` (oldest evicted).

### 3.4 No hard mqtt dependency; load-order handling
- manifest.json unchanged; no `after_dependencies`.
- `async_reconcile()`: compute prefixes; if non-empty, lazily import `homeassistant.components.mqtt` (inside try); subscribe any prefix not yet subscribed. **Add-only (rev 2, H3):** a prefix that disappears from discovery stays subscribed. Frigate's unload pops `hass.data["frigate"][entry_id]` (frigate `__init__.py:618`), and a `ConfigEntryNotReady` retry leaves it absent; unsubscribing in that gap would strand in-flight MQTT-latched ids. A dead-topic subscription is free. Unsubscribe only at ingress teardown. (`await mqtt.async_subscribe(hass, f"{p}/events", cb)`); every failure leaves that prefix inert and logs DEBUG. Idempotent.
- Triggered: (a) at ingress setup; (b) `async_when_setup(hass, "mqtt", ...)`; (c) `async_when_setup(hass, "frigate", ...)`, because the prefix exists only after Frigate's setup has fetched its server config; (d) a periodic reconcile every `FRIGATE_INGRESS_RECONCILE_S` to catch a Frigate entry added or reloaded later (`async_when_setup` fires once). Late Frigate after `ConfigEntryNotReady` is caught only by (d), up to `FRIGATE_INGRESS_RECONCILE_S`, and the bus covers that gap (L1).
- **Open, verify in build (M4):** whether an `mqtt.async_subscribe` subscription survives a reload of the MQTT config entry. The builder reads the installed HA core `homeassistant/components/mqtt` source and cites file:line before writing this section. If it does not survive, reconcile (d) also re-subscribes when the MQTT family has been silent for more than `FRIGATE_INGRESS_RECONCILE_S` while the bus family is active. The census face bridge shares this exposure; note the outcome on `FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1`.
- Every hook callback starts with the liveness guard `hass.data[DOMAIN].get("frigate_ingress") is self` (copy of D2-MED-1 at `__init__.py:2974-2978`).
- The MQTT callback is `@callback`, sync, and must not block: parse, normalise, `_dispatch`.

**Build resolutions (2026-11-09, verified in source):**
- **M4 answered: subscriptions survive an MQTT entry reload.** HA core 2026.2.3 `mqtt/__init__.py:643-646` saves the client's remaining subscriptions at unload, and `:433-438` restores them on the new client (`client.py:809-815`). No silence-triggered re-subscribe is needed. Side effect: an unsub callable taken before the reload may not reach the restored subscription, so an orphan can outlive URA's teardown. The events callback checks `_torn_down` and does nothing; topic handlers are cleared at teardown. The census face bridge rides the ingress and gets the same protection.
- **Retained messages are ignored.** A subscribe replays the broker's retained message for the topic (D0: `frigate/` delivered only retained `state`/`snapshot`/`available` messages). A retained `<prefix>/events` message is a stale event, so the ingress skips it and counts `frigate_ingress_mqtt_retained_skipped`. A retained face message would latch an old name stamped `now`, so the census face bridge skips it too (`frigate_face_msg_retained_count`). Both read `ReceiveMessage.retain` (`mqtt/models.py:84-92`).
- **`async_when_setup("frigate")` can fire too early.** HA adds the component to `hass.config.components` (`setup.py:465`) before its entries are set up (`:467-482`), and `async_when_setup` fires at once when the component is listed (`:627-631`). So the hook can run before Frigate stored its config. The ingress therefore also reconciles once on `EVENT_HOMEASSISTANT_STARTED` (boot), and the periodic reconcile (d) covers a later Frigate (re)load.
- **Discovery does not gate on entry state.** It reads runtime data per Frigate entry id. The data exists from Frigate setup (frigate `__init__.py:378`) until unload pops it (`:618`), and `LOADED` is set later than the data, which is the race above.
- **The face bridge rides the ingress.** Operator 2026-11-09 folded FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1 into this cycle (§7 non-goal superseded). `register_topic_handler("tracked_object_update", ...)` subscribes `<prefix>/tracked_object_update` for every discovered prefix through the same reconcile, late-load and teardown machinery. If the ingress is absent, the bridge subscribes directly to each discovered prefix. There is no literal fallback in either path. The kill switch `FRIGATE_INGRESS_MQTT_ENABLED` covers `<prefix>/events` only; the face topic stays subscribed.
- **The §4 build gate is a behavioural test, not a grep** (Bug Class #62): with the ingress present, registering both consumers leaves exactly one `frigate_events` bus listener (`test_single_frigate_events_listener_site`).

### 3.5 Lifecycle
- Setup: B-M1-style double-setup guard (`__init__.py:3536-3545` pattern): pop and tear down any prior ingress before creating a new one.
- Consumers register in their own `async_setup` and unregister in `async_teardown`. Perimeter's `_unsub_frigate_events` and linker's `_unsub_frigate` now hold the **unregister** callables, so their existing teardown sites (perimeter :1210-1215, linker teardown) stay unchanged in shape.
- Unload: tear down the ingress **after** both consumers (bus unsub, every MQTT unsub, reconcile timer, `async_when_setup` callbacks guarded by liveness). Reload = unload + setup; the guard prevents orphan subscriptions.
- If the ingress fails to construct, consumers fall back to registering their own bus listener directly (today's code path, kept as `_legacy_bus_listen`), so alerting never loses Frigate events because of the new module.

## 4. Emission / decision-site enumeration
Every site that listens to, or would need to listen to, Frigate events (independently re-greppable):
1. `perimeter_alert.py:971` bus listen → becomes `ingress.register_consumer("perimeter", ...)`.
2. `exterior_track_linker.py:266` bus listen → becomes `ingress.register_consumer("linker", ...)`.
3. `camera_census.py:5261` MQTT `tracked_object_update`: different topic and payload. **Not migrated** (§7).
4. No other `frigate_events` / `<prefix>/events` reader exists (grep in §0.1).
Build gate: after the build, `grep -rn 'async_listen(.*FRIGATE_EVENTS_BUS_EVENT' custom_components/` must return exactly one hit, in `frigate_ingress.py`, plus the guarded legacy fallbacks. A test asserts this.

## 5. Deliverables

### D0. Probe + fixture (measure before build; go/no-go)
Read-only and one-shot. For 30-60 min of real traffic, capture side by side: (a) raw `frigate2/events` MQTT payloads (the HA `mqtt.dump` service on `frigate2/events`, or `mosquitto_sub` in the broker add-on); (b) `frigate_events` bus events (websocket `subscribe_events`). Report:
1. Pairing rate by `(id, type, after.frame_time)`, and **dict equality** of each MQTT-normalised message against its bus twin (expect 100%).
2. MQTT→bus latency distribution (p50/p95/**max**). Max sizes the TTL (§3.3).
3. Messages present on MQTT but missing from the bus (automation queue overflow, `max: 25`).
4. Max gap between consecutive messages of one event id (information only; it does not size the TTL, per rev 2 H2).
6. Count of id-less messages (expect 0).
5. F1: the face-bridge subscribe topic from the INFO log.
Commit a 10-20-message slice (new/update/end, at least one person on a zoned camera) as `quality/tests/fixtures/frigate_events_mqtt_live.json` with its bus twins.
**Gate (rev 2, L2):** D0 does not decide whether the cycle happens (portability is an operator mandate). It blocks the build until (a) normalised equality is 100%, or the normaliser accounts for every difference, and (b) the TTL default satisfies `TTL >= max(10, 3 × max lag)`.
- **Verify:** report appended to this doc (§10).
- **Live:** n/a (offline).

### D1. `FrigateEventIngress` + prefix discovery
§3.1-3.4.
- **Verify:** with frigate hass.data stubbed `{eid: {"config": {"mqtt": {"topic_prefix": "frigate2"}}}}`, discovery returns `{"frigate2"}`; entry data/options are never read; missing keys → `set()`.
- **Verify:** the normaliser applied to the D0 MQTT fixture yields dicts `==` the captured bus twins.
- **Verify:** mqtt import raising, or `async_subscribe` raising → ingress up, bus path live, no exception escapes.
- **Test:** `test_prefix_discovery_reads_frigate_runtime_config`, `test_prefix_discovery_empty_when_frigate_absent`, `test_normalise_matches_live_bus_fixture`, `test_mqtt_absent_bus_only_unchanged`, `test_mqtt_subscribe_raises_inert`.

### D2. Dedup source latch
§3.3.
- **Verify (discriminating):** fixture stream N messages for one id, delivered via both sources interleaved (MQTT first, bus copies 50 ms later) → each consumer called exactly N times, in MQTT order. Under the rejected `(id, type)` key the same test yields 2 calls (new + one update), so it discriminates against F2.
- **Verify:** MQTT delivers new + update, then goes silent; bus continues. Before TTL: bus copies dropped. After TTL: bus copies dispatched.
- **Verify:** an id-less message delivered by both sources reaches each consumer exactly once (MQTT copy when MQTT is subscribed; bus copy when it is not).
- **Verify:** latch never exceeds `FRIGATE_INGRESS_LATCH_MAX`.
- **Verify:** a bus twin delayed by less than the TTL is dropped even after a long same-family gap, and the TTL clamps to at least 10.
- **Test:** `test_dual_source_exactly_once_preserves_updates`, `test_latch_failover_after_ttl`, `test_bus_first_then_mqtt_drops_mqtt`, `test_latch_bounded`, `test_idless_single_family`, `test_ttl_floor_clamp`.

### D3. Migrate both consumers; lifecycle wiring
Bodies of `_on_frigate_event` and linker `_on_frigate` unchanged except they read `data` instead of `event.data`, and gain an unused `source` argument. Wire per §3.4-3.5 in `__init__.py`.
- **Verify (byte-identical):** replay the D0 bus fixture through (a) the old code path and (b) the ingress with both sources fed. Snapshot of `_frigate_last_event_id`, `_frigate_ended_event_id`, `_frigate_event_cache` (minus `received_at`), linker tracks, and the dispatched alert payload are equal, after excluding arrival-time stamps: the `utcnow()` in the `_frigate_last_event_id` tuple, `received_at`, `_frigate_bus_times` values and linker `now` (rev 2, M1).
- **Verify:** load orders mqtt-before-URA, mqtt-after-URA, frigate-after-URA, and mqtt-never all end with the correct subscription set (0 or 1 per prefix, never 2).
- **Verify:** unload → zero MQTT subs, zero bus listeners, reconcile timer cancelled. A late `async_when_setup` callback after unload does nothing (liveness guard).
- **Verify:** reload twice → exactly one subscription per prefix.
- **Verify:** the Frigate entry unloaded (hass.data popped) while reconcile runs → the `frigate2/events` subscription is kept (add-only).
- **Verify:** ingress construction failure → consumers use the legacy bus listener.
- **Test:** `test_replay_byte_identical_dual_source`, `test_load_order_matrix`, `test_unload_drains_all_subs`, `test_late_when_setup_after_unload_noop`, `test_reload_no_orphan_subscription`, `test_frigate_unload_gap_keeps_subscription`, `test_ingress_failure_legacy_fallback`, `test_single_frigate_events_listener_site`.

### D4. D2 trip-wire and diagnostics follow the ingress
`_frigate_bus_times` counts ingress-dispatched messages (either source), so the silent WARN fires only when **both** sources are silent. Reword: "...with ZERO Frigate event messages (MQTT `<prefixes>` and frigate_events bus)". On the diagnostic sensor add (display only): `frigate_ingress_prefixes`, `frigate_ingress_mqtt_24h`, `frigate_ingress_bus_24h`, `frigate_ingress_dedup_dropped`, `frigate_ingress_mqtt_bad_payload`, `frigate_ingress_idless`. `bus_24h` and `mqtt_24h` count messages **received** per source, before dedup. The existing `frigate_events_24h` keeps its meaning (messages delivered to consumers).
- **Verify (discriminating):** bridge removed, MQTT live → no WARN, `mqtt_24h > 0`, `bus_24h == 0`. Both silent with edges ≥ threshold → WARN. Under the old bus-only counter the first case would WARN, which is what discriminates.
- **Test:** `test_silent_warn_needs_both_sources_silent`, `test_ingress_diag_attrs`.

### D5. README + live validation write-back
`docs/readmes/README_v<assigned>.md` with the Live table filled post-restart.

### Live criteria (post-restart)
- **Live L1:** INFO log `FrigateEventIngress: subscribed frigate2/events` once per boot; no `frigate/events` subscription.
- **Live L2:** within an hour, the diagnostic sensor shows `frigate_ingress_mqtt_24h > 0` **and** `frigate_ingress_dedup_dropped > 0`, with `dedup_dropped ≈ bus_24h`. This proves both sources ran and the bus copies were deduped. `dedup_dropped == 0` while `bus_24h > 0` means double-feed (INV-1 broken).
- **Live L3 (rev 2, M2):** `frigate_events_24h` for back_yard divided by the pre-deploy snapshot is below 1.5 and consistent with 1 + the D0 item 3 overflow fraction. MQTT recovers messages the bridge queue dropped, so a modest rise is expected; about 2× means double-feed.
- **Live L4 (portability drill, reversible):** disable the bridge automation for 15 min. Perimeter alerts still carry Frigate snapshots, D2 records keep updating, `bus_24h` stops rising, no WARN. Re-enable the automation afterwards.
- **Live L5:** grep the log for 1 h → zero `FrigateEventIngress` exceptions; 40/40 entries loaded.

## 6. Knobs (all rung 1, module constants in const.py; protocol/plumbing numbers, not operator policy)
| Knob | Default | Why / kill switch |
|---|---|---|
| `FRIGATE_INGRESS_MQTT_ENABLED` | `True` | Kill switch: `False` = no MQTT subscription, bus-only, today's behaviour. |
| `FRIGATE_INGRESS_SOURCE_LATCH_TTL_S` | `30` provisional; final = `max(10, 3 × D0 max lag)` | Sliding silence window before the other source may take over an event id; also the failover dead time. No disable value: values below 10 clamp to 10 (rev 2, M3). The kill switch is `FRIGATE_INGRESS_MQTT_ENABLED` alone. |
| `FRIGATE_INGRESS_LATCH_MAX` | `2000` | Memory bound on the latch. |
| `FRIGATE_INGRESS_RECONCILE_S` | `300` | Periodic prefix re-discovery (add-only). `0` disables (setup + when_setup only). |
Reused unchanged: `PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES`, `PERIMETER_FRIGATE_BUS_WINDOW_S`.
No options-flow field (parsimonious config): discovery has no knob to turn.

## 7. Non-goals
- Rewiring the census face bridge (`tracked_object_update`) onto the new prefix helper. F1 is a real defect, but fixing it changes census identity behaviour. **Card it** (`FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1`, KEEP+WIRE onto `discover_frigate_topic_prefixes`), gated on D0 item 5.
- Removing or editing the house bridge automation. The operator may retire it after L4; that is not URA's call.
- An options-flow prefix override. Parked; revive when an install has Frigate MQTT but not the Frigate HA integration.
- Subscribing to `<prefix>/reviews` or other Frigate topics.
- Any change to alert gating, snapshot tiers, or linker logic.
- Any change to manifest.json.

## 8. Tier
**Tier 2-DB (operator-elevated, no DB trigger).** The change sits on a cross-module ingress shared by alerting, snapshot capture and the linker; the failure modes are silent (double-feed, frozen D2 records, orphan subscriptions); and byte-identity must hold on the live house. Not Tier 3: no cost or safety actuation, and the kill switch restores today's path. Three framing-disjoint code reviews: **A** normaliser + dedup correctness against the live fixture; **B** lifecycle/async (load-order matrix, reload, unload, late callbacks, `@callback`); **C** test authority by per-site mutation (latch drop branch, liveness guard, consumer unregister, normaliser key mapping). Then live validation L1-L5 and the README write-back.

## 9. Marginal-benefit note
Simplest version considered: MQTT-only, drop the bus listener. It is rejected because an install with no MQTT (or an addon that fires `frigate_events`) would lose everything. Keeping the bus costs one latch. The latch is the minimum machinery that keeps both sources without double-feeding.

## 10. D0 probe report
**GO** (2026-11-09 08:00-10:00 CST capture; full report `AUDIT_frigate_mqtt_d0_day_2026_11_09.md`, supersedes the overnight NO-GO).
- Gate (a): normalised equality 1881/1881 = 100%, 0 unpaired either side.
- Gate (b): max bus lag behind MQTT 44.3 ms, so `max(10, 3 × 0.044) = 10`. The 30 s default is kept for the unmeasured burst case: the automation queue (`max: 25`) was not stressed (peak 8 msg/s).
- Payload shapes the consumers already handle: `sub_label` is null or a `[name, score]` list, `end_time` is set only on `end`, 0 id-less messages.
- F1 confirmed by topic and config (the log line itself was not readable): `frigate/` carries retained messages only, and face traffic is on `frigate2/tracked_object_update`.
- Fixture: `quality/tests/fixtures/frigate_events_mqtt_live.json` (16 MQTT/bus pairs, 3 complete events; develop cd533bb6).

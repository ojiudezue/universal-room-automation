"""PERIMETER-FRIGATE-MQTT-DIRECT-1: one ingress for Frigate events.

Plan: docs/planning/PLANNING_frigate_mqtt_direct_2026_11.md (rev 2).

Two sources feed the same consumers (perimeter alert manager, exterior track
linker):

* ``"bus"``: the ``frigate_events`` HA bus event, fired by a house
  automation that bridges ``<prefix>/events`` (optional, install-specific);
* ``"mqtt:<prefix>"``: a direct MQTT subscription to ``<prefix>/events`` for
  every Frigate topic prefix discovered from the RUNNING Frigate integration
  (no literal prefix, no manifest dependency on mqtt).

A per-event-id source latch (first family wins, sliding TTL) keeps each
consumer at most once per message (INV-1) without deduping the ``update``
stream of one family (plan F2).

The ingress also owns the census face-bridge subscription
(``<prefix>/tracked_object_update``) through ``register_topic_handler``, so
prefix discovery, late-load handling and teardown exist once
(FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1).

Retained messages: an MQTT subscribe replays the broker's retained message
for the topic. On ``<prefix>/events`` a retained message is a stale event, so
the ingress skips it (``mqtt_retained_skipped``). Topic handlers receive the
raw message and apply their own policy (the census face bridge skips
retained too).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback

from . import const as _c
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

FRIGATE_EVENTS_BUS_EVENT = "frigate_events"
FRIGATE_INGRESS_HASS_KEY = "frigate_ingress"
FRIGATE_DOMAIN = "frigate"
EVENTS_TOPIC_SUFFIX = "events"
FACE_TOPIC_SUFFIX = "tracked_object_update"

FAMILY_BUS = "bus"
FAMILY_MQTT = "mqtt"

# Received-message counters are kept in one-minute buckets over this window
# (display only; reuses the D2 window so both diagnostics share a horizon).
_BUCKET_S = 60


# ---------------------------------------------------------------------------
# Prefix discovery (shared with the census face bridge)
# ---------------------------------------------------------------------------
def discover_frigate_topic_prefixes(hass: HomeAssistant) -> set[str]:
    """Return the MQTT topic prefixes of every running Frigate entry.

    The Frigate integration fetches its server config at entry setup and
    stores it at ``hass.data["frigate"][entry_id]["config"]`` (frigate
    ``__init__.py:378-381``, v5.15.6); the prefix is
    ``config["mqtt"]["topic_prefix"]`` (used the same way by frigate's own
    ``WSEventProxy`` at ``:372``). The config ENTRY never holds it.

    An entry counts when its runtime data is present (set during setup,
    popped on unload at frigate ``:618``); entry state is not consulted,
    because HA marks the component loaded before its entries finish setup
    (``homeassistant/setup.py:465`` vs ``:467-482``). Defensive throughout:
    any error yields an empty set. No literal fallback.
    """
    out: set[str] = set()
    try:
        runtime = hass.data.get(FRIGATE_DOMAIN)
        if not isinstance(runtime, Mapping):
            return out
        entries = hass.config_entries.async_entries(FRIGATE_DOMAIN) or []
        for entry in entries:
            ent = runtime.get(getattr(entry, "entry_id", None))
            if not isinstance(ent, Mapping):
                continue
            cfg = ent.get("config")
            if not isinstance(cfg, Mapping):
                continue
            mq = cfg.get("mqtt")
            if not isinstance(mq, Mapping):
                continue
            prefix = mq.get("topic_prefix")
            if not isinstance(prefix, str):
                continue
            prefix = prefix.strip().rstrip("/")
            if prefix:
                out.add(prefix)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Frigate topic-prefix discovery failed", exc_info=True)
        return set()
    return out


# ---------------------------------------------------------------------------
# Normaliser: MQTT payload -> the dict the bridge automation puts on the bus
# ---------------------------------------------------------------------------
def normalise_frigate_event_payload(payload: Any) -> dict[str, Any] | None:
    """Map a raw ``<prefix>/events`` payload to the ``frigate_events`` data.

    Mirrors the bridge automation (``before``/``after`` default ``{}``,
    ``type`` default ``""``; ``default()`` fires on undefined only, so a JSON
    ``null`` passes through). Key order matches the automation. Returns None
    for undecodable / non-object payloads. D0: 1881/1881 dict-equal.
    """
    try:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            p = json.loads(payload)
        elif isinstance(payload, Mapping):
            p = payload
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(p, Mapping):
        return None
    return {
        "before": p["before"] if "before" in p else {},
        "after": p["after"] if "after" in p else {},
        "type": p["type"] if "type" in p else "",
    }


def effective_latch_ttl_s() -> float:
    """TTL with the rev-2 M3 floor applied (no disable value)."""
    try:
        ttl = float(_c.FRIGATE_INGRESS_SOURCE_LATCH_TTL_S)
    except Exception:  # noqa: BLE001
        ttl = 0.0
    return max(float(_c.FRIGATE_INGRESS_SOURCE_LATCH_TTL_FLOOR_S), ttl)


class FrigateEventIngress:
    """Owns every Frigate event source and every Frigate MQTT subscription."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._consumers: dict[str, Callable[[Mapping[str, Any], str], None]] = {}
        self._topic_handlers: dict[str, dict[str, Callable[[Any], None]]] = {}
        # (prefix, suffix) -> unsubscribe callable. Add-only until teardown.
        self._mqtt_subs: dict[tuple[str, str], Callable[[], None]] = {}
        # event id -> (family, last_seen_monotonic); ordered by last refresh.
        self._latch: OrderedDict[str, tuple[str, float]] = OrderedDict()
        # Latch clock (monotonic; injectable so tests never patch the
        # process-wide time.monotonic the event loop also reads).
        self._clock: Callable[[], float] = time.monotonic
        self._unsub_bus: Callable[[], None] | None = None
        self._unsub_timer: Callable[[], None] | None = None
        self._unsub_started: Callable[[], None] | None = None
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self._torn_down = False
        # Diagnostics (display only).
        self._received: dict[str, dict[int, int]] = {FAMILY_BUS: {}, FAMILY_MQTT: {}}
        self.dedup_dropped: dict[str, int] = {FAMILY_BUS: 0, FAMILY_MQTT: 0}
        self.mqtt_bad_payload = 0
        self.mqtt_retained_skipped = 0
        self.idless = 0

    # ---- registration ---------------------------------------------------
    def register_consumer(
        self, name: str, fn: Callable[[Mapping[str, Any], str], None],
    ) -> Callable[[], None]:
        """Register an events consumer ``fn(data, source)``; returns unregister."""
        self._consumers[name] = fn

        def _unregister() -> None:
            if self._consumers.get(name) is fn:
                self._consumers.pop(name, None)

        return _unregister

    def register_topic_handler(
        self, suffix: str, name: str, fn: Callable[[Any], None],
    ) -> Callable[[], None]:
        """Route raw MQTT messages of ``<prefix>/<suffix>`` to ``fn(msg)``.

        Subscribes on every discovered prefix (now and on later reconciles).
        Returns an unregister callable; the subscription itself stays until
        ingress teardown (add-only, plan §3.4).
        """
        self._topic_handlers.setdefault(suffix, {})[name] = fn
        self._schedule_reconcile()

        def _unregister() -> None:
            handlers = self._topic_handlers.get(suffix) or {}
            if handlers.get(name) is fn:
                handlers.pop(name, None)

        return _unregister

    # ---- lifecycle ------------------------------------------------------
    def _is_live(self) -> bool:
        if self._torn_down:
            return False
        try:
            return self.hass.data.get(DOMAIN, {}).get(FRIGATE_INGRESS_HASS_KEY) is self
        except Exception:  # noqa: BLE001
            return False

    async def async_setup(self) -> None:
        """Bus listener, first reconcile, late-load hooks, periodic timer.

        The caller stores the ingress at ``hass.data[DOMAIN]["frigate_ingress"]``
        BEFORE calling this, so the hook liveness guards see it.
        """
        self._unsub_bus = self.hass.bus.async_listen(
            FRIGATE_EVENTS_BUS_EVENT, self._on_bus,
        )
        await self.async_reconcile()
        try:
            from homeassistant.setup import async_when_setup

            async def _late(_hass: HomeAssistant, _component: str) -> None:
                # D2-MED-1 pattern: a torn-down ingress never re-subscribes.
                if not self._is_live():
                    return
                await self.async_reconcile()

            async_when_setup(self.hass, "mqtt", _late)
            async_when_setup(self.hass, FRIGATE_DOMAIN, _late)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("FrigateEventIngress: async_when_setup failed", exc_info=True)
        # `async_when_setup(frigate)` can fire before Frigate's entry has
        # stored its config (component marked loaded first), so reconcile
        # once more when HA has started.
        try:
            if not getattr(self.hass, "is_running", True):
                from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

                @callback
                def _on_started(_event: Event) -> None:
                    self._unsub_started = None
                    if self._is_live():
                        self._schedule_reconcile()

                self._unsub_started = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, _on_started,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("FrigateEventIngress: started hook failed", exc_info=True)
        interval_s = int(_c.FRIGATE_INGRESS_RECONCILE_S or 0)
        if interval_s > 0:
            try:
                from datetime import timedelta

                from homeassistant.helpers.event import async_track_time_interval

                @callback
                def _tick(_now: Any) -> None:
                    if self._is_live():
                        self._schedule_reconcile()

                self._unsub_timer = async_track_time_interval(
                    self.hass, _tick, timedelta(seconds=interval_s),
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("FrigateEventIngress: timer failed", exc_info=True)

    def async_teardown(self) -> None:
        """Drop every listener, subscription, timer and pending task."""
        self._torn_down = True
        for attr in ("_unsub_bus", "_unsub_timer", "_unsub_started"):
            unsub = getattr(self, attr)
            setattr(self, attr, None)
            if unsub is not None:
                try:
                    unsub()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("FrigateEventIngress: %s raised", attr, exc_info=True)
        subs = list(self._mqtt_subs.values())
        self._mqtt_subs.clear()
        for unsub in subs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("FrigateEventIngress: mqtt unsub raised", exc_info=True)
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self._consumers.clear()
        self._topic_handlers.clear()

    def _schedule_reconcile(self) -> None:
        if self._torn_down:
            return
        try:
            task = self.hass.async_create_task(self.async_reconcile())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("FrigateEventIngress: schedule failed", exc_info=True)
            return
        if isinstance(task, asyncio.Task):
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _wanted_suffixes(self) -> list[str]:
        out: list[str] = []
        if _c.FRIGATE_INGRESS_MQTT_ENABLED:
            out.append(EVENTS_TOPIC_SUFFIX)
        for suffix, handlers in self._topic_handlers.items():
            if handlers and suffix not in out:
                out.append(suffix)
        return out

    async def async_reconcile(self) -> None:
        """Subscribe every (prefix, suffix) not yet subscribed. Add-only."""
        if self._torn_down:
            return
        suffixes = self._wanted_suffixes()
        if not suffixes:
            return
        prefixes = discover_frigate_topic_prefixes(self.hass)
        if not prefixes:
            return
        if all((p, s) in self._mqtt_subs for p in prefixes for s in suffixes):
            return
        try:
            from homeassistant.components import mqtt as _mqtt
        except Exception:  # noqa: BLE001
            _LOGGER.debug("FrigateEventIngress: mqtt import failed", exc_info=True)
            return
        async with self._lock:
            for prefix in sorted(prefixes):
                for suffix in suffixes:
                    key = (prefix, suffix)
                    if self._torn_down:
                        return
                    if key in self._mqtt_subs:
                        continue
                    topic = f"{prefix}/{suffix}"
                    try:
                        unsub = await _mqtt.async_subscribe(
                            self.hass, topic, self._make_mqtt_cb(prefix, suffix),
                        )
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "FrigateEventIngress: subscribe %s failed (inert)",
                            topic, exc_info=True,
                        )
                        continue
                    if self._torn_down:
                        try:
                            unsub()
                        except Exception:  # noqa: BLE001
                            pass
                        return
                    self._mqtt_subs[key] = unsub
                    _LOGGER.info("FrigateEventIngress: subscribed %s", topic)

    def _make_mqtt_cb(self, prefix: str, suffix: str) -> Callable[[Any], None]:
        if suffix == EVENTS_TOPIC_SUFFIX:
            source = f"{FAMILY_MQTT}:{prefix}"

            @callback
            def _events_cb(msg: Any) -> None:
                self._on_mqtt_events(msg, source)

            return _events_cb

        @callback
        def _topic_cb(msg: Any) -> None:
            # Teardown clears _topic_handlers, so an orphan (restored after
            # an MQTT entry reload) finds no handler and does nothing.
            for name, fn in list((self._topic_handlers.get(suffix) or {}).items()):
                try:
                    fn(msg)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "FrigateEventIngress: topic handler %s raised", name,
                        exc_info=True,
                    )

        return _topic_cb

    # ---- sources --------------------------------------------------------
    def _note_received(self, family: str) -> None:
        now = time.time()
        bucket = int(now // _BUCKET_S)
        store = self._received[family]
        store[bucket] = store.get(bucket, 0) + 1
        horizon = bucket - int(_c.PERIMETER_FRIGATE_BUS_WINDOW_S // _BUCKET_S)
        if len(store) > 1:
            for b in [b for b in store if b <= horizon]:
                store.pop(b, None)

    @callback
    def _on_bus(self, event: Event) -> None:
        # No torn-down guard needed: teardown unsubscribes this listener.
        self._note_received(FAMILY_BUS)
        data = event.data
        if not isinstance(data, Mapping):
            return
        self._dispatch(data, FAMILY_BUS, FAMILY_BUS)

    def _on_mqtt_events(self, msg: Any, source: str) -> None:
        if self._torn_down:
            return
        if getattr(msg, "retain", False) is True:
            self.mqtt_retained_skipped += 1
            return
        self._note_received(FAMILY_MQTT)
        data = normalise_frigate_event_payload(getattr(msg, "payload", None))
        if data is None:
            self.mqtt_bad_payload += 1
            return
        self._dispatch(data, FAMILY_MQTT, source)

    def _mqtt_events_live(self) -> bool:
        return any(s == EVENTS_TOPIC_SUFFIX for (_p, s) in self._mqtt_subs)

    def _dispatch(self, data: Mapping[str, Any], family: str, source: str) -> None:
        """Latch then fan out (plan §3.3)."""
        after = data.get("after")
        event_id = after.get("id") if isinstance(after, Mapping) else None
        if not event_id:
            self.idless += 1
            owner = FAMILY_MQTT if self._mqtt_events_live() else FAMILY_BUS
            if family != owner:
                self.dedup_dropped[family] += 1
                return
        else:
            key = str(event_id)
            now = self._clock()
            ttl = effective_latch_ttl_s()
            held = self._latch.get(key)
            if held is not None and held[0] != family and (now - held[1]) < ttl:
                self.dedup_dropped[family] += 1
                return
            self._latch[key] = (family, now)
            self._latch.move_to_end(key)
            while self._latch:
                _oldest, (_fam, seen) = next(iter(self._latch.items()))
                if now - seen >= ttl:
                    self._latch.popitem(last=False)
                else:
                    break
            cap = int(_c.FRIGATE_INGRESS_LATCH_MAX)
            while cap > 0 and len(self._latch) > cap:
                self._latch.popitem(last=False)
        for name, fn in list(self._consumers.items()):
            try:
                fn(data, source)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "FrigateEventIngress: consumer %s raised", name, exc_info=True,
                )

    # ---- diagnostics ----------------------------------------------------
    def _count_24h(self, family: str) -> int:
        horizon = int(time.time() // _BUCKET_S) - int(
            _c.PERIMETER_FRIGATE_BUS_WINDOW_S // _BUCKET_S
        )
        return sum(c for b, c in self._received[family].items() if b > horizon)

    def subscribed_prefixes(self) -> list[str]:
        return sorted({p for (p, s) in self._mqtt_subs if s == EVENTS_TOPIC_SUFFIX})

    def diag_stats(self) -> dict[str, Any]:
        """Display-only attributes (plan D4)."""
        return {
            "frigate_ingress_prefixes": self.subscribed_prefixes(),
            "frigate_ingress_mqtt_24h": self._count_24h(FAMILY_MQTT),
            "frigate_ingress_bus_24h": self._count_24h(FAMILY_BUS),
            "frigate_ingress_dedup_dropped": sum(self.dedup_dropped.values()),
            "frigate_ingress_mqtt_bad_payload": self.mqtt_bad_payload,
            "frigate_ingress_mqtt_retained_skipped": self.mqtt_retained_skipped,
            "frigate_ingress_idless": self.idless,
        }


async def async_setup_frigate_ingress(hass: HomeAssistant) -> None:
    """Create + register the ingress (called from the integration entry
    setup, before the census, perimeter and linker).

    B-M1 double-setup guard: a prior instance (partial reload) is popped and
    torn down first, so a reload never leaves an orphan subscription. The
    ingress is stored in hass.data BEFORE async_setup so its late-load hook
    liveness guards see it. Any failure leaves the key absent (consumers
    fall back to their own bus listener).
    """
    async_teardown_frigate_ingress(hass)
    try:
        ingress = FrigateEventIngress(hass)
        hass.data[DOMAIN][FRIGATE_INGRESS_HASS_KEY] = ingress
        await ingress.async_setup()
    except Exception:  # noqa: BLE001
        _LOGGER.error(
            "FrigateEventIngress setup failed; Frigate consumers use the "
            "frigate_events bus directly", exc_info=True,
        )
        async_teardown_frigate_ingress(hass)


def async_teardown_frigate_ingress(hass: HomeAssistant) -> None:
    """Pop and tear down the ingress (safe if absent). Called from the
    integration entry unload AFTER its consumers."""
    try:
        ingress = hass.data.get(DOMAIN, {}).pop(FRIGATE_INGRESS_HASS_KEY, None)
    except Exception:  # noqa: BLE001
        return
    if ingress is None:
        return
    try:
        ingress.async_teardown()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("FrigateEventIngress teardown raised", exc_info=True)


def get_frigate_ingress(hass: HomeAssistant) -> FrigateEventIngress | None:
    try:
        ing = hass.data.get(DOMAIN, {}).get(FRIGATE_INGRESS_HASS_KEY)
    except Exception:  # noqa: BLE001
        return None
    return ing if isinstance(ing, FrigateEventIngress) else None


def register_frigate_consumer(
    hass: HomeAssistant,
    name: str,
    fn: Callable[[Mapping[str, Any], str], None],
) -> Callable[[], None]:
    """Register ``fn(data, source)`` on the ingress, or fall back to a
    direct ``frigate_events`` bus listener (today's path) when the ingress
    is absent (construction failed, or a harness without one)."""
    ingress = get_frigate_ingress(hass)
    if ingress is not None:
        try:
            return ingress.register_consumer(name, fn)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("FrigateEventIngress: register %s failed", name, exc_info=True)

    @callback
    def _legacy_bus_listen(event: Event) -> None:
        fn(event.data, FAMILY_BUS)

    return hass.bus.async_listen(FRIGATE_EVENTS_BUS_EVENT, _legacy_bus_listen)

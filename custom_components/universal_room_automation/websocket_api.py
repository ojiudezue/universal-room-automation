"""v5.17.0 — URA Observability WebSocket surface.

Three read-only WebSocket commands feeding the PWA M4 alerts + activity
feeds:

* ``ura/logs/anomalies`` — paginated anomaly_log query.
* ``ura/logs/activity``  — paginated ura_activity_log query.
* ``ura/logs/subscribe`` — live push driven by SIGNAL_ACTIVITY_LOGGED
  (dispatcher-bridged; no polling, no per-event DB re-query, no writes).

Falsifiable load-bearing invariant (planning doc §1):
    The WS surface performs ZERO writes to the URA database, and no single
    command invocation can return more than ``WS_MAX_PAGE_SIZE`` rows
    (default 200) regardless of arguments or crafted input.

The DAO layer (``database.query_anomalies`` / ``query_activities``) is the
sole SQL surface. Both DAOs go through ``_db_read()`` which sets
``PRAGMA query_only=ON`` — a hard-fail safety net for any accidental
write. No handler here touches ``_db()`` (write queue).

Registration is process-global (HA websocket_api requires unique command
names). Guarded by ``_WS_REGISTERED`` so multiple entries can call
``async_register_ws_commands`` idempotently. See planning doc §5.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    DOMAIN,
    WS_ACTIVITY_IMPORTANCE_VALUES,
    WS_ANOMALY_SEVERITY_NAME_TO_NUMBER,
    WS_ANOMALY_SEVERITY_NUMBERS,
    WS_COMMAND_ACTIVITY,
    WS_COMMAND_ANOMALIES,
    WS_COMMAND_SUBSCRIBE,
    WS_MAX_PAGE_SIZE,
)

# v5.17.0 review fix B-H2: subscribe channel filters on `importance`, not
# `severity` — the sole emit site (activity_logger.py:120-129) puts
# ``importance`` on the payload; ``severity`` is never populated. Ordinal
# comparison map is explicit here so the semantics are self-documenting.
_IMPORTANCE_ORDINAL: dict[str, int] = {
    "debug": 0,
    "info": 1,
    "notable": 2,
    "warning": 3,
    "critical": 4,
}
from .domain_coordinators.signals import SIGNAL_ACTIVITY_LOGGED

_LOGGER = logging.getLogger(__name__)

# Process-global registration guard. HA's ``async_register_command`` raises
# on double-registration, and URA has multiple config entries whose
# ``async_setup_entry`` runs per-entry. See planning doc §5.
_WS_REGISTERED: bool = False


def _get_database(hass: HomeAssistant):
    """Return the URA database instance, or None if not yet ready."""
    try:
        return hass.data.get(DOMAIN, {}).get("database")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Voluptuous schemas
# ---------------------------------------------------------------------------

# severity accepts BOTH numeric strings ('0'..'4') and human name aliases
# (mapped at the DAO boundary). See B0 probe finding #4 in planning doc.
_SEVERITY_INPUTS = tuple(WS_ANOMALY_SEVERITY_NUMBERS) + tuple(
    WS_ANOMALY_SEVERITY_NAME_TO_NUMBER.keys()
)

_ANOMALIES_SCHEMA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend({
    vol.Required("type"): WS_COMMAND_ANOMALIES,
    vol.Optional("since"): str,
    vol.Optional("until"): str,
    vol.Optional("coordinator_id"): str,
    vol.Optional("severity"): vol.In(_SEVERITY_INPUTS),
    vol.Optional("anomaly_type"): str,
    vol.Optional("resolved"): bool,
    vol.Optional("cursor"): vol.All(int, vol.Range(min=0)),
    vol.Optional("limit"): vol.All(int, vol.Range(min=1, max=WS_MAX_PAGE_SIZE)),
    vol.Optional("columns"): vol.All(list, [str]),
})

_ACTIVITY_SCHEMA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend({
    vol.Required("type"): WS_COMMAND_ACTIVITY,
    vol.Optional("since"): str,
    vol.Optional("until"): str,
    vol.Optional("coordinator"): str,
    vol.Optional("room"): str,
    vol.Optional("zone"): str,
    vol.Optional("importance"): vol.In(WS_ACTIVITY_IMPORTANCE_VALUES),
    vol.Optional("cursor"): vol.All(int, vol.Range(min=0)),
    vol.Optional("limit"): vol.All(int, vol.Range(min=1, max=WS_MAX_PAGE_SIZE)),
    vol.Optional("columns"): vol.All(list, [str]),
})

_SUBSCRIBE_SCHEMA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend({
    vol.Required("type"): WS_COMMAND_SUBSCRIBE,
    vol.Optional("streams"): vol.All(list, [vol.In(("anomalies", "activity"))]),
    vol.Optional("coordinator"): str,
    # v5.17.0 review fix B-H2: the payload emitted through
    # SIGNAL_ACTIVITY_LOGGED carries ``importance`` (name-valued), not
    # ``severity``. Filter param renamed to ``min_importance`` for
    # surface honesty. Live anomaly-severity filtering is NOT available on
    # this channel today (see docs — future work note).
    vol.Optional("min_importance"): vol.In(tuple(_IMPORTANCE_ORDINAL.keys())),
})


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@websocket_api.websocket_command(_ANOMALIES_SCHEMA)
@websocket_api.async_response
async def _handle_anomalies(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return a page of anomaly_log rows. Read-only, cap-enforced."""
    database = _get_database(hass)
    if database is None:
        connection.send_error(msg["id"], "not_ready", "URA database not ready")
        return
    try:
        result = await database.query_anomalies(
            since=msg.get("since"),
            until=msg.get("until"),
            coordinator_id=msg.get("coordinator_id"),
            severity=msg.get("severity"),
            anomaly_type=msg.get("anomaly_type"),
            resolved=msg.get("resolved"),
            cursor=msg.get("cursor"),
            # Handler passes user-supplied limit unchanged; DAO clamps it
            # server-side. Cap is enforced there — never trust the client.
            limit=msg.get("limit", 50),
            columns=msg.get("columns"),
        )
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_format", str(exc))
        return
    except Exception as exc:  # pragma: no cover
        # v5.17.0 review fix A5: do not leak exception str to the client.
        # Full traceback stays in the server log via _LOGGER.exception.
        _LOGGER.exception("ura/logs/anomalies handler failed: %s", exc)
        connection.send_error(msg["id"], "unknown_error", "internal error")
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(_ACTIVITY_SCHEMA)
@websocket_api.async_response
async def _handle_activity(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return a page of ura_activity_log rows. Read-only, cap-enforced."""
    database = _get_database(hass)
    if database is None:
        connection.send_error(msg["id"], "not_ready", "URA database not ready")
        return
    try:
        result = await database.query_activities(
            since=msg.get("since"),
            until=msg.get("until"),
            coordinator=msg.get("coordinator"),
            room=msg.get("room"),
            zone=msg.get("zone"),
            importance=msg.get("importance"),
            cursor=msg.get("cursor"),
            limit=msg.get("limit", 50),
            columns=msg.get("columns"),
        )
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_format", str(exc))
        return
    except Exception as exc:  # pragma: no cover
        # v5.17.0 review fix A5: do not leak exception str to the client.
        _LOGGER.exception("ura/logs/activity handler failed: %s", exc)
        connection.send_error(msg["id"], "unknown_error", "internal error")
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(_SUBSCRIBE_SCHEMA)
@callback
def _handle_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Live push on new activity/anomaly rows.

    Bridges the existing ``SIGNAL_ACTIVITY_LOGGED`` dispatcher signal (fired
    on every activity-log write, see ``activity_logger.py:120``) into the
    client's WS connection. NO polling, NO DB re-query per event, NO
    writes — planning doc §D3 invariant. The event payload is the small
    dict the dispatcher already sends.
    """
    streams = set(msg.get("streams") or ("anomalies", "activity"))
    coord_filter = msg.get("coordinator")
    # v5.17.0 review fix B-H2: filter on importance ordinal, not severity.
    min_importance = msg.get("min_importance")
    min_importance_ord: int | None = (
        _IMPORTANCE_ORDINAL[min_importance] if min_importance is not None else None
    )

    msg_id = msg["id"]

    # v5.17.0 review fix B-L2: first push failure per subscription is a
    # WARNING (so it surfaces); subsequent failures downgrade to debug so a
    # broken client doesn't spam the log.
    push_failed_once: dict[str, bool] = {"seen": False}

    def _send_on_loop(payload: Any) -> None:
        # Loop-affine: connection.send_message MUST be called on the event
        # loop. See websocket precedent at sensor.py:12660 (v4.6.3.2 fix).
        try:
            connection.send_message(
                websocket_api.event_message(msg_id, {"event": payload})
            )
        except Exception as exc:  # pragma: no cover
            if not push_failed_once["seen"]:
                push_failed_once["seen"] = True
                _LOGGER.warning(
                    "ura/logs/subscribe push failed (first, msg_id=%s): %s",
                    msg_id, exc,
                )
            else:
                _LOGGER.debug("ura/logs/subscribe push failed: %s", exc)

    def _on_activity(payload: Any) -> None:
        # Dispatcher callbacks can fire on a sync worker thread (see
        # activity_logger emit path + sensor.py:12648-12665 precedent).
        # send_message is loop-affine → marshal via hass.add_job which is
        # thread-safe from either the loop or a worker thread.
        try:
            if not isinstance(payload, dict):
                return
            # v5.17.0 review fix B-H3: discriminate the two streams. The
            # emit site tags anomaly rows with ``action == "anomaly"``
            # (activity_logger callers set it); everything else is activity.
            is_anomaly = payload.get("action") == "anomaly"
            if is_anomaly and "anomalies" not in streams:
                return
            if (not is_anomaly) and "activity" not in streams:
                return
            if coord_filter is not None:
                coord = payload.get("coordinator") or payload.get("coordinator_id")
                if coord != coord_filter:
                    return
            if min_importance_ord is not None:
                imp = payload.get("importance")
                imp_ord = _IMPORTANCE_ORDINAL.get(imp) if isinstance(imp, str) else None
                # Unknown / missing importance is treated as below floor —
                # keeps the filter honest rather than defaulting to pass.
                if imp_ord is None or imp_ord < min_importance_ord:
                    return
            hass.add_job(_send_on_loop, payload)
        except Exception as exc:  # pragma: no cover
            if not push_failed_once["seen"]:
                push_failed_once["seen"] = True
                _LOGGER.warning(
                    "ura/logs/subscribe filter failed (first): %s", exc
                )
            else:
                _LOGGER.debug("ura/logs/subscribe filter failed: %s", exc)

    unsub = async_dispatcher_connect(hass, SIGNAL_ACTIVITY_LOGGED, _on_activity)

    # HA framework invokes this unsub when the client disconnects (or sends
    # unsubscribe). Registering it via ``subscriptions`` is the standard
    # pattern; no manual disconnect handling required.
    connection.subscriptions[msg_id] = unsub
    connection.send_result(msg_id)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def async_register_ws_commands(hass: HomeAssistant) -> None:
    """Register the URA observability WS commands, once per process.

    Idempotent: subsequent calls are no-ops. HA's
    ``async_register_command`` is process-global; registering the same
    command name twice raises. URA has multiple config entries whose
    ``async_setup_entry`` runs per-entry — this guard prevents the second
    entry from crashing on setup.
    """
    global _WS_REGISTERED
    if _WS_REGISTERED:
        return
    # v5.17.0 review fix B-M1: register per-command with idempotent skip so
    # a mid-sequence failure on a retry doesn't blow up on
    # already-registered names. _WS_REGISTERED only latches on full success
    # so a partial-failure state is recoverable by a subsequent call.
    for handler in (_handle_anomalies, _handle_activity, _handle_subscribe):
        try:
            websocket_api.async_register_command(hass, handler)
        except ValueError as exc:
            # HA raises ValueError on duplicate registration. Treat as
            # already-registered and continue — the target end-state is
            # "all three present"; a duplicate means we already have it.
            _LOGGER.debug(
                "WS command %s already registered (skipping): %s",
                getattr(handler, "__name__", handler), exc,
            )
    _WS_REGISTERED = True
    _LOGGER.info(
        "URA observability WS commands registered: %s, %s, %s",
        WS_COMMAND_ANOMALIES, WS_COMMAND_ACTIVITY, WS_COMMAND_SUBSCRIBE,
    )

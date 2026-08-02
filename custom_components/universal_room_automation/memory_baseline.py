"""Memory baseline writer — Stage 1 MVP.

Folds current room samples into ``metric_baselines`` (with our
`coordinator_id='memory'` scope prefix) once per 5-min strategy cycle.
Welford update; count clamp = MEMORY_BASELINE_SAMPLE_CAP.

Quality gate (arch §5): a room's sample is SKIPPED for this cycle when
the room currently has:
  * mmwave_fan_demoted latch active (D2 latch), or
  * fan_transition_suppressed activity in the current window.

Gated by MEMORY_BASELINE_WRITER_ENABLED + MEMORY_BASELINE_ALLOWLIST
(Study-A plus 4 siblings on ship; go house-wide only after a full-day
live write-volume check — write-flood postmortem).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    MEMORY_BASELINE_ALLOWLIST,
    MEMORY_BASELINE_SAMPLE_CAP,
    MEMORY_BASELINE_WRITER_ENABLED,
)
from .memory_facade import (
    build_metric_key,
    house_state_to_family,
    utc_to_local_hour_bin,
)

_LOGGER = logging.getLogger(__name__)

_TRACKED_SIGNALS = ("occupied", "temperature", "humidity")

# Writer stats surfaced by sensor.ura_memory_status.
_STATS_KEY = "memory_baseline_stats"


def _stats(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(DOMAIN, {}).setdefault(
        _STATS_KEY,
        {
            "last_fold": None,
            "rows_written_last_cycle": 0,
            "cycles_run": 0,
        },
    )


def _is_room_suppressed(
    hass: HomeAssistant, room_slug: str,
) -> bool:
    """Quality gate: exclude this room's sample if a D2 demotion latch or
    a fan-transition suppression is active in the current window.

    Reads coordinator attrs defensively — never blocks the writer.
    """
    try:
        managers = hass.data.get(DOMAIN, {})
        for key, val in managers.items():
            if not isinstance(val, dict):
                continue
            coord = val.get("coordinator") or val.get("room_coordinator")
            if coord is None:
                continue
            title = getattr(coord, "room_name", None) or getattr(
                coord, "_room_name", None,
            )
            if not title:
                continue
            slug = title.lower().replace(" ", "_").replace("-", "_")
            if slug != room_slug:
                continue
            if getattr(coord, "_mmwave_demoted_latch", False):
                return True
            if getattr(coord, "_mmwave_fan_demoted_last_tick", False):
                return True
            # Cheap window check: any suppression this cycle window.
            count = int(
                getattr(coord, "_fan_transition_suppressed_count", 0) or 0
            )
            prev = coord.__dict__.get(
                "_memory_baseline_prev_suppressed_count", 0
            )
            coord.__dict__[
                "_memory_baseline_prev_suppressed_count"
            ] = count
            if count > prev:
                return True
    except Exception:  # noqa: BLE001 — never fail the writer
        pass
    return False


def _get_house_family(hass: HomeAssistant) -> str:
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        presence = (
            getattr(manager, "coordinators", {}).get("presence")
            if manager is not None else None
        )
        if presence is not None:
            state = getattr(presence, "house_state", None)
            if state:
                return house_state_to_family(state)
    except Exception:  # noqa: BLE001
        pass
    return "home"


def _room_samples(hass: HomeAssistant, room_slug: str) -> dict[str, Any]:
    """Collect the room's current samples.

    Look up the room's occupied binary_sensor + climate/temp/humidity
    sensors from hass.states. Returns a signal->value dict.
    """
    samples: dict[str, Any] = {}
    try:
        occ = hass.states.get(f"binary_sensor.{room_slug}_occupied")
        if occ is not None and occ.state in ("on", "off"):
            samples["occupied"] = 1.0 if occ.state == "on" else 0.0
        temp = hass.states.get(f"sensor.{room_slug}_temperature")
        if temp is not None:
            try:
                samples["temperature"] = float(temp.state)
            except (TypeError, ValueError):
                pass
        hum = hass.states.get(f"sensor.{room_slug}_humidity")
        if hum is not None:
            try:
                samples["humidity"] = float(hum.state)
            except (TypeError, ValueError):
                pass
    except Exception:  # noqa: BLE001
        pass
    return samples


async def async_fold_samples(hass: HomeAssistant) -> int:
    """Fold current samples for all allowlisted rooms. Returns row count.

    Called from the 5-min strategy cycle. No-op when the writer is
    disabled or the allowlist is empty.
    """
    if not MEMORY_BASELINE_WRITER_ENABLED:
        return 0
    if not MEMORY_BASELINE_ALLOWLIST:
        return 0
    db = hass.data.get(DOMAIN, {}).get("database")
    if db is None:
        return 0
    family = _get_house_family(hass)
    hour_bin = utc_to_local_hour_bin(datetime.now(timezone.utc))
    stats = _stats(hass)
    rows_written = 0
    for room_slug in MEMORY_BASELINE_ALLOWLIST:
        if _is_room_suppressed(hass, room_slug):
            _LOGGER.debug(
                "memory_baseline: skipping %s (D2/fan-gate suppression)",
                room_slug,
            )
            continue
        samples = _room_samples(hass, room_slug)
        if not samples:
            continue
        node_id = f"room:{room_slug}"
        for signal, value in samples.items():
            metric = build_metric_key(signal, hour_bin, family)
            try:
                await db.upsert_memory_baseline(
                    node_id, metric, float(value),
                    MEMORY_BASELINE_SAMPLE_CAP,
                )
                rows_written += 1
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug(
                    "memory_baseline upsert failed (%s/%s): %s",
                    node_id, metric, e,
                )
    stats["last_fold"] = datetime.now(timezone.utc).isoformat()
    stats["rows_written_last_cycle"] = rows_written
    stats["cycles_run"] = int(stats.get("cycles_run", 0)) + 1
    # Pre-compute unusual_today per allowlisted room so
    # OccupiedBinarySensor.extra_state_attributes can read a cached value
    # without a facade round-trip.
    try:
        facade = hass.data.get(DOMAIN, {}).get("memory_facade")
        if facade is not None:
            for room_slug in MEMORY_BASELINE_ALLOWLIST:
                try:
                    ans = await facade.unusual(f"room:{room_slug}")
                    if ans.verdict == "ok" and ans.value:
                        top = ans.value[0]
                        summary = (
                            f"{top.get('metric_name', '?')}"
                            f" (sd={((top.get('variance') or 0.0) ** 0.5):.2f},"
                            f" n={top.get('sample_count', 0)})"
                        )
                    else:
                        summary = "none"
                    # Cache on the room coordinator, best-effort.
                    for _key, val in list(
                        hass.data.get(DOMAIN, {}).items(),
                    ):
                        if not isinstance(val, dict):
                            continue
                        coord = val.get("coordinator") or val.get(
                            "room_coordinator",
                        )
                        if coord is None:
                            continue
                        title = getattr(coord, "room_name", None) or (
                            getattr(coord, "_room_name", None)
                        )
                        if not title:
                            continue
                        slug = title.lower().replace(
                            " ", "_",
                        ).replace("-", "_")
                        if slug == room_slug:
                            coord.__dict__[
                                "_memory_unusual_today_cached"
                            ] = summary
                            break
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        pass
    if rows_written:
        _LOGGER.info(
            "memory_baseline fold: %d rows across %d rooms "
            "(bin=h%02d family=%s)",
            rows_written, len(MEMORY_BASELINE_ALLOWLIST),
            hour_bin, family,
        )
    return rows_written

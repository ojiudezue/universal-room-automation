"""CONSOL-1 (v-next) — universal llmvision enrichment adapter.

Contract (planning doc §D3, rev-2):

- `enrich_dispatched_alert(hass, snapshot_path, camera_entity_id) -> str | None`
- Runs BETWEEN snapshot resolution and NM dispatch on the caller side.
- Fires the `llmvision.image_analyzer` service (verified D0.1 return
  shape: `{"response_text": "<str>"}`) with pinned defaults
  `gpt-4o-mini` + `max_tokens=1500` — overridable via config-flow
  fields at rung 2.
- Wraps the service call in `asyncio.wait_for(..., timeout=...)` where
  `timeout` comes from the rung-3 Number entity
  `perimeter_enrichment_timeout_s` (default 4.0s).

Falsifiable invariants pinned here (INV-ENRICH-*):

- **INV-ENRICH-NEVER-SILENCES**: for each of the three failure classes
  (exception, timeout, empty), the adapter returns None cleanly and
  the caller MUST fall through to a base-message NM dispatch. No
  exception ever escapes this function to the caller.
- **INV-ENRICH-NON-EMPTY**: `None`, `""`, or whitespace-only
  `response_text` counts as a FAILURE. The adapter returns None; the
  caller uses the base message and stamps
  `route_reason = NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH`.
- **INV-ENRICH-BUDGETED (cancel-immediately)**: on timeout,
  `asyncio.wait_for` cancels the underlying task via native
  coroutine cancellation. The provider MAY still bill for the
  cancelled call. A cancelled task cannot late-deliver into the
  alert path — the caller has already advanced past `nm.async_notify`.

Kill switches (rung 1 module const → rung 2 config → rung 3 entity):

1. `LLMVISION_ENRICHMENT_KILL = True` → adapter no-ops on entry.
2. `CONF_PERIMETER_ENRICHMENT_ENABLED = False` (default OFF at ship)
   or `CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS = []` → adapter no-ops.
3. `perimeter_enrichment_timeout_s` clamped [MIN, MAX] via the
   Number-entity persistence machinery.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from .const import (
    CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS,
    CONF_PERIMETER_ENRICHMENT_ENABLED,
    CONF_PERIMETER_ENRICHMENT_MAX_TOKENS,
    CONF_PERIMETER_ENRICHMENT_MODEL,
    CONF_PERIMETER_ENRICHMENT_PROVIDER,
    CONF_PERIMETER_ENRICHMENT_PROVIDER_ID,
    CONF_ENTRY_TYPE,
    DEFAULT_PERIMETER_ENRICHMENT_ENABLED,
    DEFAULT_PERIMETER_ENRICHMENT_MAX_TOKENS,
    DEFAULT_PERIMETER_ENRICHMENT_MODEL,
    DEFAULT_PERIMETER_ENRICHMENT_PROVIDER,
    DEFAULT_PERIMETER_ENRICHMENT_TIMEOUT_S,
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    LLMVISION_ENRICHMENT_KILL,
    MAX_PERIMETER_ENRICHMENT_TIMEOUT_S,
    MIN_PERIMETER_ENRICHMENT_TIMEOUT_S,
)

_LOGGER = logging.getLogger(__name__)

# The default prompt mirrors the operator's live doorbell automation so
# side-by-side P2 parity has a fair comparison. Kept short (<255 chars)
# to avoid gpt-5-mini reasoning-token blowout; effect on gpt-4o-mini
# is negligible.
_DEFAULT_PROMPT = (
    "Describe what you see in this image. What type of detection is "
    "this (person, vehicle, or animal)? Provide a brief, clear "
    "description."
)

_LLMVISION_DOMAIN = "llmvision"
_LLMVISION_SERVICE = "image_analyzer"


def _get_integration_config(hass: Any) -> dict[str, Any]:
    """Read merged data+options from the integration config entry."""
    try:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                return {**entry.data, **entry.options}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _get_timeout_s(hass: Any) -> float:
    """Read the rung-3 timeout Number entity, fall back to default."""
    try:
        state = hass.states.get(
            f"number.{DOMAIN}_perimeter_enrichment_timeout_s"
        )
        if state is not None:
            raw = float(state.state)
            if raw < MIN_PERIMETER_ENRICHMENT_TIMEOUT_S:
                return MIN_PERIMETER_ENRICHMENT_TIMEOUT_S
            if raw > MAX_PERIMETER_ENRICHMENT_TIMEOUT_S:
                return MAX_PERIMETER_ENRICHMENT_TIMEOUT_S
            return raw
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_PERIMETER_ENRICHMENT_TIMEOUT_S


def _is_enabled_for_camera(cfg: dict[str, Any], camera_entity_id: str) -> bool:
    """Rung 1 + 2 gate. True iff enrichment should fire for this camera."""
    if LLMVISION_ENRICHMENT_KILL:
        return False
    if not bool(cfg.get(
        CONF_PERIMETER_ENRICHMENT_ENABLED,
        DEFAULT_PERIMETER_ENRICHMENT_ENABLED,
    )):
        return False
    allowlist = cfg.get(CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS) or []
    if not allowlist:
        return False
    return camera_entity_id in allowlist


async def enrich_dispatched_alert(
    hass: Any,
    snapshot_path: str | None,
    camera_entity_id: str,
    *,
    prompt: str | None = None,
) -> str | None:
    """Return enriched description or None (three failure classes fall through).

    Return contract:
      - str (non-empty, stripped)  -> success  -> caller sets
        route_reason = NM_ROUTE_REASON_ENRICHED.
      - None                       -> any failure class OR gated off ->
        caller uses base message. If gated off, caller preserves the
        pre-cycle route_reason path; if enabled+allowlisted but the
        adapter still returned None, caller sets
        route_reason = NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH.

    Never raises. INV-ENRICH-NEVER-SILENCES is enforced here.
    """
    # --- Rung 1 (kill switch) + rung 2 (config gate) — cheap early return.
    cfg = _get_integration_config(hass)
    if not _is_enabled_for_camera(cfg, camera_entity_id):
        _LOGGER.debug(
            "enrich_dispatched_alert: gated off for camera=%s (kill=%s, "
            "enabled=%s, cams=%s)",
            camera_entity_id,
            LLMVISION_ENRICHMENT_KILL,
            cfg.get(CONF_PERIMETER_ENRICHMENT_ENABLED),
            cfg.get(CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS),
        )
        return None

    # --- Empty-snapshot early return (rev-2 L1).
    if not snapshot_path:
        _LOGGER.debug(
            "enrich_dispatched_alert: no snapshot_path for %s — skipping",
            camera_entity_id,
        )
        return None
    try:
        if not os.path.exists(snapshot_path):
            _LOGGER.debug(
                "enrich_dispatched_alert: snapshot_path missing on disk (%s)",
                snapshot_path,
            )
            return None
    except Exception:  # noqa: BLE001
        # Filesystem quirk (e.g. permission) — treat as missing, fall through.
        return None

    provider = cfg.get(
        CONF_PERIMETER_ENRICHMENT_PROVIDER,
        DEFAULT_PERIMETER_ENRICHMENT_PROVIDER,
    )
    model = cfg.get(
        CONF_PERIMETER_ENRICHMENT_MODEL,
        DEFAULT_PERIMETER_ENRICHMENT_MODEL,
    )
    max_tokens = cfg.get(
        CONF_PERIMETER_ENRICHMENT_MAX_TOKENS,
        DEFAULT_PERIMETER_ENRICHMENT_MAX_TOKENS,
    )
    provider_id = cfg.get(CONF_PERIMETER_ENRICHMENT_PROVIDER_ID) or None
    timeout_s = _get_timeout_s(hass)

    # Currently only "llmvision" is wired; a future provider abstraction
    # would dispatch here.
    if provider != "llmvision":
        _LOGGER.warning(
            "enrich_dispatched_alert: provider=%s not implemented — "
            "falling through", provider,
        )
        return None

    service_data: dict[str, Any] = {
        "message": prompt or _DEFAULT_PROMPT,
        "image_file": snapshot_path,
        "max_tokens": int(max_tokens),
        "model": model,
    }
    if provider_id:
        service_data["provider"] = provider_id

    async def _call() -> Any:
        # `return_response=True` per D0.1 — the service returns
        # `{"response_text": "..."}` in that path.
        return await hass.services.async_call(
            _LLMVISION_DOMAIN,
            _LLMVISION_SERVICE,
            service_data,
            blocking=True,
            return_response=True,
        )

    # --- INV-ENRICH-BUDGETED + INV-ENRICH-NEVER-SILENCES.
    try:
        result = await asyncio.wait_for(_call(), timeout=timeout_s)
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "enrich_dispatched_alert: timeout after %.2fs for %s — "
            "falling through", timeout_s, camera_entity_id,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "enrich_dispatched_alert: exception for %s: %s — "
            "falling through", camera_entity_id, exc,
        )
        return None

    # --- INV-ENRICH-NON-EMPTY.
    # Verified D0.1 return shape is the FLAT top-level dict
    # `{"response_text": "..."}`. Any other envelope (nested
    # `service_response`, list wrapper, string body, None) is treated
    # as a FAILURE class — the caller falls through with the base
    # message and the FAILED_FALL_THROUGH route_reason. This is
    # intentional: silently accepting alternate shapes would mask a
    # provider-API change we haven't verified.
    try:
        if isinstance(result, dict) and "response_text" in result:
            text = str(result.get("response_text") or "").strip()
        else:
            text = ""
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        _LOGGER.info(
            "enrich_dispatched_alert: empty response_text for %s — "
            "falling through (INV-ENRICH-NON-EMPTY)", camera_entity_id,
        )
        return None
    return text

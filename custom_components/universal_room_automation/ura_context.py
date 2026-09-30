"""URA-wide write mark (ROOM-LIGHTING-SETUP-REDESIGN-1 Slice C, v5.103.28).

Every URA light write passes ``context=ura_write_context()`` to
``hass.services.async_call``. The D2 manual-change listener
(``ActuatorReconciler._note_manual_light_change``) calls
``is_ura_context(event.context)`` and never books a URA write as a
person's change.

HA Context API — verified against the installed homeassistant 2026.2.3
(.venv-ha), not from memory:

* ``homeassistant/core.py:1208-1224`` — ``Context(user_id, parent_id, id)``;
  ``id`` defaults to a fresh ULID (``ulid_now()``).
* ``homeassistant/core.py:2712-2737`` — ``ServiceRegistry.async_call(...,
  context=None, ...)``; ``context = context or Context()``; the
  ``ServiceCall`` carries that same object.
* ``homeassistant/helpers/service.py:838, 868, 888`` —
  ``entity.async_set_context(call.context)`` before the entity method runs.
* ``homeassistant/helpers/entity.py:82, 932-935, 1235-1248`` — the entity
  keeps the context for ``CONTEXT_RECENT_TIME_SECONDS`` (5 s) and writes
  it onto the state it sets, so the ``state_changed`` event carries it.
  A device echo that lands more than 5 s after the call gets a fresh
  context (a known residual, see the README).
* Recorder stores ``context.id`` / ``context.parent_id`` through
  ``ulid_to_bytes_or_none`` (``components/recorder/db_schema.py:319-323``).

Why the mark rides ``parent_id`` and not ``id`` (plan R2-1 said
``Context(id=URA_WRITE_CONTEXT_ID + tag)``): a non-ULID ``id`` is stored as
NULL by the recorder and ONE shared ``id`` would merge every URA write into
one logbook context. A fresh ULID ``id`` with a fixed, valid-ULID
``parent_id`` keeps each write distinct and still marks it as URA's.
"""

from __future__ import annotations

from typing import Any, Final

try:  # pragma: no cover - exercised implicitly
    from homeassistant.core import Context as _HAContext
except Exception:  # noqa: BLE001 — unit-test stubs without Context
    _HAContext = None  # type: ignore[assignment]


# Fixed, valid 26-char Crockford ULID (``ulid_to_bytes_or_none`` accepts it).
# Module constant (rung 1): it is a protocol mark, not a policy knob.
URA_WRITE_CONTEXT_PARENT_ID: Final = "01K6RAWR1TE0000000000000A1"


class _FallbackContext:
    """Minimal stand-in used only when HA's Context is not importable."""

    __slots__ = ("id", "parent_id", "user_id")

    def __init__(self, user_id=None, parent_id=None, id=None):  # noqa: A002
        import uuid

        self.id = id or uuid.uuid4().hex
        self.user_id = user_id
        self.parent_id = parent_id


def ura_write_context() -> Any:
    """Return a fresh Context marked as a URA write."""
    cls = _HAContext if _HAContext is not None else _FallbackContext
    return cls(parent_id=URA_WRITE_CONTEXT_PARENT_ID)


# Room lights are ``light.*`` or ``switch.*`` (CONF_LIGHTS picker allows both,
# config_flow.py:1777). Only writes to these domains carry the mark, so every
# other URA write (climate, cover, fan, lock, number ...) stays byte-identical.
URA_LIGHT_WRITE_DOMAINS: Final = frozenset({"light", "switch"})


def ura_ctx_kwargs(domain: str) -> dict:
    """``{"context": ura_write_context()}`` for a light-capable domain, else ``{}``."""
    if domain in URA_LIGHT_WRITE_DOMAINS:
        return {"context": ura_write_context()}
    return {}


def is_ura_context(context: Any) -> bool:
    """True when ``context`` was minted by :func:`ura_write_context`."""
    if context is None:
        return False
    try:
        return getattr(context, "parent_id", None) == URA_WRITE_CONTEXT_PARENT_ID
    except Exception:  # noqa: BLE001
        return False

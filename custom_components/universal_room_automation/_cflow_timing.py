"""Config-flow timing instrumentation (CONFIG-FLOW-SLOW-ONBOARDING-1).

Diagnostic-only. Wraps every ``async_step_*`` handler on the URA
ConfigFlow and OptionsFlow classes to log entry/exit with monotonic +
wall-clock timestamps and elapsed ms. Also wraps the sync auto-detect
helpers ``_get_area_entities`` and ``_rank_area_candidates`` so we can
distinguish handler-time from event-loop-stall (large wall-clock gap
between one step's EXIT and the next step's ENTRY = loop was blocked
elsewhere; suspect the CM/parent reload storm).

Log format (WARNING so visible without raising global log level):

    CFLOW-TIMING: ENTER  <class>.<step>            mono=<s.ms> wall=<ISO>
    CFLOW-TIMING: EXIT   <class>.<step>  elapsed_ms=<N>  mono=<s.ms> wall=<ISO>
                     [autodetect_calls=<N> autodetect_ms=<M>]

How to read the output:
    * elapsed_ms is the time INSIDE the async_step handler (including
      awaits it made). A large elapsed_ms means the step itself is slow
      (schema build, entity/area registry walks, io).
    * wall-clock gap between step N EXIT and step N+1 ENTER is USER
      THINK TIME + any event-loop stall. If the user reports submitting
      immediately but the gap is 30-60s, the loop was blocked. Correlate
      that window with CM/parent config-entry reload logs.
    * autodetect_* are the aggregate calls/ms into _get_area_entities +
      _rank_area_candidates during the step; the hot path was measured
      sub-second in isolation, so a large number here would be new news.

HA dispatch safety: HA looks up steps via ``getattr(flow, method)`` at
homeassistant/data_entry_flow.py:483 (and ``hasattr`` at :568). We wrap
by replacing the class attribute in-place with a ``functools.wraps``
wrapper of the SAME NAME, so both hasattr and getattr resolve exactly
as before. The wrapper is an ``async def`` coroutine function — the
awaited-value contract is unchanged.
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)

# Master gate. Set False to disable all instrumentation with zero
# runtime cost beyond the one-shot class decoration at import.
CONFIG_FLOW_TIMING: bool = True

_STEP_PREFIX = "async_step_"
_AUTODETECT_HELPERS = ("_get_area_entities", "_rank_area_candidates")


def _now_wall() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _reset_autodetect(flow) -> None:
    flow._cflow_autodetect_ms = 0.0
    flow._cflow_autodetect_calls = 0


def _wrap_step(cls_name: str, method):
    """Wrap one async_step_* method with entry/exit timing."""

    @functools.wraps(method)
    async def wrapper(self, user_input=None):
        _reset_autodetect(self)
        t0 = time.monotonic()
        _LOGGER.warning(
            "CFLOW-TIMING: ENTER  %s.%s  mono=%.3f wall=%s user_input=%s",
            cls_name,
            method.__name__,
            t0,
            _now_wall(),
            "yes" if user_input is not None else "no",
        )
        try:
            return await method(self, user_input)
        finally:
            t1 = time.monotonic()
            ad_ms = getattr(self, "_cflow_autodetect_ms", 0.0)
            ad_calls = getattr(self, "_cflow_autodetect_calls", 0)
            _LOGGER.warning(
                "CFLOW-TIMING: EXIT   %s.%s  elapsed_ms=%.1f  mono=%.3f wall=%s"
                "  autodetect_calls=%d autodetect_ms=%.1f",
                cls_name,
                method.__name__,
                (t1 - t0) * 1000.0,
                t1,
                _now_wall(),
                ad_calls,
                ad_ms,
            )

    return wrapper


def _wrap_autodetect(method):
    """Wrap a sync auto-detect helper to accumulate per-step totals."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        t0 = time.monotonic()
        try:
            return method(self, *args, **kwargs)
        finally:
            dt_ms = (time.monotonic() - t0) * 1000.0
            # Guard: self may not yet have the counters if the helper is
            # called outside a wrapped step (e.g. from __init__ paths).
            self._cflow_autodetect_ms = (
                getattr(self, "_cflow_autodetect_ms", 0.0) + dt_ms
            )
            self._cflow_autodetect_calls = (
                getattr(self, "_cflow_autodetect_calls", 0) + 1
            )

    return wrapper


def instrument_flow(cls):
    """Class decorator: wrap every async_step_* on ``cls`` with timing.

    Idempotent (marker attribute); safe to apply to both ConfigFlow and
    OptionsFlow. Also wraps the two auto-detect helpers if present.
    """
    if not CONFIG_FLOW_TIMING:
        return cls
    if getattr(cls, "_cflow_timing_instrumented", False):
        return cls

    wrapped = 0
    for name, attr in list(vars(cls).items()):
        if not name.startswith(_STEP_PREFIX):
            continue
        if not inspect.iscoroutinefunction(attr):
            continue
        setattr(cls, name, _wrap_step(cls.__name__, attr))
        wrapped += 1

    for name in _AUTODETECT_HELPERS:
        attr = vars(cls).get(name)
        if attr is not None and inspect.isfunction(attr):
            setattr(cls, name, _wrap_autodetect(attr))

    cls._cflow_timing_instrumented = True
    _LOGGER.warning(
        "CFLOW-TIMING: instrumented %s (%d step handlers)",
        cls.__name__,
        wrapped,
    )
    return cls

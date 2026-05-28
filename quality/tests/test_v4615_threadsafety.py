"""Bug Class #42: lambda + async_create_task in HA scheduler callbacks.

v4.6.15 thread-safety hotfix regression test. AST-based codebase-wide
guard against reintroducing the pattern:

    lambda _now: self.hass.async_create_task(self._async_refresh())

passed to async_track_time_interval / async_track_time_change.

HA's frame helper flags this as a thread-safety violation:
"calls async_create_task from a thread other than the event loop, which
may cause Home Assistant to crash or data to corrupt".

HA's HassJob does not recognize lambdas as coroutine functions, so the
coroutine returned by the inner async_create_task call is silently never
awaited. Scheduled work does not run. Sensors show stale data; digests
never fire. Correlated with multiple HA-core crashes on 2026-05-26.

Origin commits:
  - v3.6.29 (Notification Manager, 2 sites in notification_manager.py)
  - v4.6.13 (Coordinator Telemetry, 3 sites in sensor.py)

Fixed: v4.6.15 (Tier 2-DB scale, 3 parallel reviewers).

Prevention going forward:
  - Pass coroutine functions directly to HA scheduler APIs
    (HA's HassJob wraps them with HassJobType.Coroutinefunction).
  - For closures, use functools.partial — HA explicitly unwraps it
    before iscoroutinefunction introspection.
  - NEVER wrap in `lambda: hass.async_create_task(...)` — always wrong
    for scheduler callbacks.
"""
import ast
import pathlib


URA_ROOT = (
    pathlib.Path(__file__).parents[2]
    / "custom_components"
    / "universal_room_automation"
)


def test_no_lambda_wrapping_async_create_task():
    """Bug Class #42: no lambda body may call async_create_task.

    Pattern: lambda ...: <any_expr>.async_create_task(...)

    AST walk every .py file under custom_components/universal_room_automation/,
    inspect each Lambda node's body for an Attribute Call whose attr name is
    "async_create_task". Any match is a violation.

    This test would have caught all 5 original bug sites and permanently
    prevents reintroduction.
    """
    violations = []
    for py_file in sorted(URA_ROOT.rglob("*.py")):
        # Skip __pycache__ and any non-source artifacts.
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            # Don't fail the regression test on a pre-existing syntax error;
            # other test infrastructure will catch that.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Lambda):
                continue
            for inner in ast.walk(node.body):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "async_create_task"
                ):
                    rel = py_file.relative_to(URA_ROOT.parent.parent)
                    violations.append(
                        f"{rel}:{node.lineno} — lambda wraps async_create_task "
                        f"(Bug Class #42)"
                    )
    assert not violations, (
        "lambda + async_create_task anti-pattern found "
        f"({len(violations)} site(s)):\n" + "\n".join(violations)
    )


def test_v4615_fix_sites_use_direct_coroutine_passing():
    """Verify the 5 v4.6.15 fix sites pass coroutine functions directly to
    HA schedulers (NOT wrapped in lambdas) AND the signature changes landed.

    This complements the AST anti-pattern test by asserting the positive
    pattern at each known site.
    """
    sensor_py = URA_ROOT / "sensor.py"
    nm_py = URA_ROOT / "domain_coordinators" / "notification_manager.py"

    sensor_src = sensor_py.read_text()
    nm_src = nm_py.read_text()

    # The 3 sensor.py sites must use direct method-reference passing:
    #   async_track_time_interval(self.hass, self._async_refresh, timedelta(...))
    assert (
        "self._async_refresh,\n            timedelta(seconds=OVERRIDE_FREQUENCY_REFRESH_S)"
        in sensor_src
    ), "CoordinatorOverrideFrequencySensor timer not using direct coroutine passing"
    assert (
        "self._async_refresh,\n            timedelta(seconds=COMPLIANCE_RATE_REFRESH_S)"
        in sensor_src
    ), "CoordinatorComplianceRateSensor timer not using direct coroutine passing"
    assert (
        "self._async_refresh,\n            timedelta(seconds=DB_SIZE_REFRESH_S)"
        in sensor_src
    ), "URADBSizeSensor timer not using direct coroutine passing"

    # The 3 _async_refresh methods must accept _now=None
    refresh_with_now = sensor_src.count("async def _async_refresh(self, _now=None)")
    assert refresh_with_now >= 3, (
        f"Expected >=3 _async_refresh signatures with _now=None; found {refresh_with_now}"
    )

    # The 2 NM sites must use functools.partial
    assert "partial(self._fire_digest, person_id, person_cfg)" in nm_src, (
        "NM digest scheduling not using functools.partial closure binding"
    )
    assert "from functools import partial" in nm_src, (
        "NM missing 'from functools import partial' import"
    )

    # _fire_digest must accept _now=None as 3rd positional
    assert "async def _fire_digest(" in nm_src
    assert "_now=None," in nm_src, (
        "NM _fire_digest missing _now=None parameter"
    )


def test_handle_db_ready_uses_add_job_not_async_create_task():
    """Bug Class #42 sibling (v4.6.3.2 precedent + Reviewer A/C 2026-05-26):
    dispatcher-signal sync callbacks must use hass.add_job, not
    hass.async_create_task. SIGNAL_DATABASE_READY happens to dispatch on-loop
    today, but the URARecentAnomaliesSensor v4.6.3.1 incident proved
    dispatchers CAN fire from non-event-loop threads.

    Pin the precedent in sensor.py's two _handle_db_ready closures.
    """
    sensor_src = (URA_ROOT / "sensor.py").read_text()
    # Verify add_job is used in the two _handle_db_ready closures
    assert sensor_src.count(
        "self.hass.add_job(self._async_refresh())"
    ) >= 2, (
        "Expected >=2 _handle_db_ready closures using hass.add_job "
        "(per v4.6.3.2 precedent — Bug Class #42 sibling)"
    )

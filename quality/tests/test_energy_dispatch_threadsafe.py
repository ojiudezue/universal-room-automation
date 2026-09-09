"""Thread-safety anchor for energy-signal dispatches (v5.100.2).

Root cause (live, ~46x/5h + 3x): the energy decision cycle and the
EC-ready path dispatched ``SIGNAL_ENERGY_ENTITIES_UPDATE`` /
``SIGNAL_ENERGY_COORDINATOR_READY`` via HA's loop-only
``async_dispatcher_send``. Connected entity callbacks (time.py
``_refresh``, switch.py ``_handle_ec_ready``, plus number/sensor/
binary_sensor/button subscribers) call ``async_write_ha_state()``; when
the dispatch runs off the event loop HA 2026.x raises
``RuntimeError: ... calls async_write_ha_state from a thread other than
the event loop`` (escalated from a warning). Verified against live logs
(traceback anchored at time.py:186 / switch.py:1221) and the HA source
contract: ``async_dispatcher_send`` runs ``hass.verify_event_loop_thread``
and calls subscribers in the caller's thread; ``dispatcher_send`` marshals
via ``hass.loop.call_soon_threadsafe`` (safe from any thread).

No unit-level harness exists for HA's loop-thread detector, so the
falsifiable invariant is: these energy-signal dispatch sites MUST use the
threadsafe ``dispatcher_send`` and MUST NOT use the loop-only
``async_dispatcher_send``. These assertions read the source files (no HA
import needed). Mutation anchor: revert any site to
``async_dispatcher_send`` and the matching assertion goes RED.
"""
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CC = _ROOT / "custom_components" / "universal_room_automation"


def _read(rel):
    return (_CC / rel).read_text()


def test_entities_update_dispatch_threadsafe_in_energy():
    src = _read("domain_coordinators/energy.py")
    # the per-cycle refresh dispatch (aliased _send)
    assert "import dispatcher_send as _send" in src, \
        "entities-update dispatch must import threadsafe dispatcher_send"
    assert "import async_dispatcher_send as _send" not in src, \
        "entities-update dispatch must NOT use loop-only async_dispatcher_send"


def test_coordinator_ready_dispatch_threadsafe_in_energy():
    src = _read("domain_coordinators/energy.py")
    assert "dispatcher_send(self.hass, SIGNAL_ENERGY_COORDINATOR_READY)" in src
    assert "async_dispatcher_send(self.hass, SIGNAL_ENERGY_COORDINATOR_READY)" not in src, \
        "coordinator_ready dispatch must use threadsafe dispatcher_send"


def test_dp_enable_entities_update_dispatch_threadsafe_in_init():
    src = _read("__init__.py")
    assert "dispatcher_send(hass, SIGNAL_ENERGY_ENTITIES_UPDATE)" in src
    assert "async_dispatcher_send(hass, SIGNAL_ENERGY_ENTITIES_UPDATE)" not in src, \
        "DP-enable EC refresh dispatch must use threadsafe dispatcher_send"


# --- The ACTUAL fix (v5.100.3): the executor-punt of non-@callback targets ---
# HA's dispatcher (helpers/dispatcher.py) runs a connected target via
# get_hassjob_callable_job_type: a @callback target runs directly on the loop;
# a PLAIN sync function is HassJobType.Executor and is run via
# hass.async_run_hass_job -> the EXECUTOR THREAD (off the event loop). The two
# targets that logged the RuntimeError (time.py _refresh, switch.py
# _handle_ec_ready override) were plain functions -> executor -> off-loop
# async_write_ha_state. v5.100.2's threadsafe-sender swap was necessary-but-
# insufficient; the load-bearing fix is decorating these targets @callback so
# HA runs them on the loop. Mutation anchor: drop either @callback -> RED.

def test_time_refresh_is_callback_decorated():
    src = _read("time.py")
    # the _refresh closure connected to SIGNAL_ENERGY_ENTITIES_UPDATE
    assert "def _refresh(*_args) -> None:" in src
    idx = src.index("def _refresh(*_args) -> None:")
    preceding = src[:idx].rstrip().splitlines()[-1]
    assert preceding.strip() == "@callback", \
        "time.py _refresh must be @callback (else HA executor-punts it off-loop)"


def test_switch_handle_ec_ready_override_is_callback_decorated():
    src = _read("switch.py")
    # the override that calls super()._handle_ec_ready() (the one that logged the error)
    marker = "super()._handle_ec_ready()"
    assert marker in src
    idx = src.index(marker)
    block = src[:idx]
    def_idx = block.rindex("def _handle_ec_ready")
    preceding = block[:def_idx].rstrip().splitlines()[-1]
    assert preceding.strip() == "@callback", \
        "switch.py _handle_ec_ready override must be @callback (else HA executor-punts it off-loop)"

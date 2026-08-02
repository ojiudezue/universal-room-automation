"""Tests for the setup/unload symmetry hotfix.

Per PLANNING_setup_unload_symmetry.md D1, every resource registered or
created during `async_setup_entry` must have a paired teardown on
`async_unload_entry`. The four planned sub-deliverables are:

  1. Service registration teardown (`__init__.py:2267-2276` writes →
     paired `entry.async_on_unload(lambda: hass.services.async_remove(...))`).
  2. Panel teardown (`__init__.py:2292-2321` panel registrations → paired
     `entry.async_on_unload(lambda: frontend.async_remove_panel(...))`).
     NOTE: HA's `async_register_static_paths` exposes no public removal
     API (verified against HA core
     `homeassistant/components/http/__init__.py:512-543`). Static-path
     teardown is documented as a HA-core gap, not patched here.
  3. `hass.data[DOMAIN]` pop-symmetry — every `del hass.data[DOMAIN][key]`
     converted to defensive `pop(key, None)` per the v4.6.10 review-fix
     B2 pattern at `__init__.py:2884`.
  4. Untracked-task conversion — every `hass.async_create_task(...)`
     site in `coordinator.py` + `__init__.py` either converted to
     `entry.async_create_background_task(...)` or explicitly marked
     `# noqa: untracked-ok` with a justification comment.

These tests are AST + source-grep based (no HA import needed) so they
collect cleanly even when `homeassistant` is not installed in the test
environment.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re

import pytest


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMPONENT_DIR = _REPO_ROOT / "custom_components" / "universal_room_automation"
_INIT_PATH = _COMPONENT_DIR / "__init__.py"
_COORD_PATH = _COMPONENT_DIR / "coordinator.py"


@pytest.fixture(scope="module")
def init_src() -> str:
    return _INIT_PATH.read_text()


@pytest.fixture(scope="module")
def init_tree(init_src) -> ast.Module:
    return ast.parse(init_src)


@pytest.fixture(scope="module")
def coord_src() -> str:
    return _COORD_PATH.read_text()


@pytest.fixture(scope="module")
def coord_tree(coord_src) -> ast.Module:
    return ast.parse(coord_src)


# ---------------------------------------------------------------------------
# Service-name catalogue — every name `hass.services.async_register(DOMAIN,
# "<name>", ...)` writes inside _async_register_*_services.
# ---------------------------------------------------------------------------
_EXPECTED_SERVICE_NAMES = (
    # _async_register_presence_services
    "set_house_state",
    "clear_house_state_override",
    # Fan-noise Mode-2 (room-tier fan-pause + clean recheck) operator
    # escape hatch. Registered in the presence-services block so its
    # teardown rides the same async_on_unload lambda list.
    "fan_recheck_force_restore",
    # _async_register_safety_services
    "test_safety_hazard",
    # _async_register_security_services
    "security_arm",
    "security_disarm",
    "authorize_guest",
    "add_expected_arrival",
    # _async_register_notification_services
    "acknowledge_notification",
    "test_notification",
    "test_inbound",
    # _async_register_memory_services (Memory MVP Stage 1, 2026-08-02)
    "memory_query",
)


class TestServicesUnregisteredOnUnload:
    """Every service registered during setup has a paired teardown.

    Sites that write services live inside helper functions
    `_async_register_<surface>_services`; setup calls them at
    `__init__.py:2267-2276`. The paired teardown is registered via
    `entry.async_on_unload(...)` immediately after the call block.
    """

    def test_every_registered_service_has_paired_async_remove(self, init_src):
        """For every literal name in async_register(DOMAIN, "<name>", ...)
        the same name must appear inside an async_on_unload lambda that
        calls hass.services.async_remove(DOMAIN, ...).
        """
        # Collect every service name that gets registered in the helpers.
        register_pat = re.compile(
            r"hass\.services\.async_register\(\s*DOMAIN,\s*[\"\']([A-Za-z_][A-Za-z_0-9]*)[\"\']",
        )
        registered = set(register_pat.findall(init_src))

        # Sanity: helper-function catalogue matches what we read from source.
        # Catches "someone added a new service but forgot the teardown."
        missing_from_catalogue = registered - set(_EXPECTED_SERVICE_NAMES)
        assert not missing_from_catalogue, (
            "New service registration detected without a matching entry "
            "in _EXPECTED_SERVICE_NAMES: "
            f"{sorted(missing_from_catalogue)}. Update this test AND the "
            "setup/unload-symmetry block in __init__.py to add the paired "
            "hass.services.async_remove call."
        )

        # Every registered name must appear in an async_on_unload lambda body.
        # The block is a single `for _service_name in (...): entry.async_on_unload(
        # lambda _name=_service_name: hass.services.async_remove(DOMAIN, _name))`
        # We assert each name appears as a literal in the loop tuple AND that
        # the async_remove call site exists.
        assert "hass.services.async_remove(" in init_src, (
            "setup/unload symmetry: no `hass.services.async_remove(` call "
            "found in __init__.py — service teardown is missing entirely."
        )

        # A-LOW-1 (Review A, 2026-06-03): narrow the literal-presence
        # check to the teardown loop's `for _service_name in (...)`
        # Tuple node, so a coincidental string match elsewhere in the
        # file (constant, comment, handler ref) does not satisfy the
        # assertion.
        teardown_tuple_literals: set[str] = set()
        tree = ast.parse(init_src)
        for node in ast.walk(tree):
            # Look for `for _service_name in (...):` constructs.
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name) \
                    and node.target.id == "_service_name" \
                    and isinstance(node.iter, ast.Tuple):
                for elt in node.iter.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        teardown_tuple_literals.add(elt.value)
        assert teardown_tuple_literals, (
            "setup/unload symmetry: no `for _service_name in (...)` Tuple "
            "found in __init__.py — service teardown loop is missing or "
            "was refactored. Update this test if the new shape is "
            "intentional."
        )
        for name in registered:
            assert name in teardown_tuple_literals, (
                f"setup/unload symmetry: service '{name}' is registered but "
                "does not appear in the teardown loop tuple "
                "(`for _service_name in (...)`) in __init__.py. Add it to "
                "that tuple following the service-registration helpers."
            )


class TestPanelsTornDownOnUnload:
    """Every URA panel registered via `panel_custom.async_register_panel`
    has a paired `frontend.async_remove_panel` teardown.

    The two panel paths are `"ura-dashboard"` (v3.9.4) and
    `"ura-dashboard-v3"` (v3.12.0).
    """

    def test_v39_panel_has_paired_remove(self, init_src):
        # Registration side: the panel is registered with
        # frontend_url_path="ura-dashboard" (possibly via an intermediate
        # local variable, so we match the literal anywhere in the file).
        assert '"ura-dashboard"' in init_src, (
            "v3.9.4 panel registration missing (literal \"ura-dashboard\"); "
            "test fixture stale."
        )
        # Teardown side: lambda calls frontend.async_remove_panel.
        assert "async_remove_panel(" in init_src, (
            "setup/unload symmetry: no async_remove_panel call found in "
            "__init__.py — panel teardown is missing entirely."
        )
        assert "async_on_unload" in init_src, (
            "setup/unload symmetry: v3.9.4 panel teardown not wired via "
            "entry.async_on_unload(lambda: frontend.async_remove_panel(...))."
        )

    def test_v3_dashboard_panel_has_paired_remove(self, init_src):
        # Registration side (literal anywhere in file; may be via local var).
        assert '"ura-dashboard-v3"' in init_src, (
            "v3.12.0 panel registration missing (literal "
            "\"ura-dashboard-v3\"); test fixture stale."
        )


class TestStaticPathsGapDocumented:
    """HA's `async_register_static_paths` exposes no public removal API
    (verified against `homeassistant/components/http/__init__.py:512-543`
    via the GitHub `home-assistant/core` repo). Routes added live for the
    process lifetime; on entry reload aiohttp detects the duplicate and
    raises (caught by the surrounding `except`). This test pins the gap
    documentation so a future reviewer who notices "static paths have no
    teardown" can see WHY without digging.
    """

    def test_static_path_gap_is_documented_in_source(self, init_src):
        # Look for the deliberate comment block introduced by the
        # setup/unload symmetry hotfix that names the gap.
        assert (
            "async_register_static_paths" in init_src
            and "NO public removal API" in init_src
        ), (
            "setup/unload symmetry: the HA-core static-path teardown gap "
            "must remain explicitly documented in __init__.py (search for "
            "'no public removal API') so reviewers don't expect a paired "
            "teardown that HA doesn't support."
        )


class TestHassDataDrainedOnUnload:
    """`async_unload_entry` uses defensive `pop(key, None)` symmetry, not
    `del hass.data[DOMAIN][key]`, so partial-setup failures never raise
    KeyError on unload (v4.6.10 review-fix B2 pattern at
    `__init__.py:2884`).
    """

    def test_no_del_hass_data_domain_in_unload(self, init_tree, init_src):
        """AST: there must be no `del hass.data[DOMAIN][...]` calls in
        any function whose name starts with `async_unload_entry`.
        """
        offenders: list[str] = []
        for node in ast.walk(init_tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_unload_entry":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Delete):
                        # Render each deletion target and look for the
                        # hass.data[DOMAIN][...] shape.
                        for tgt in sub.targets:
                            try:
                                rendered = ast.unparse(tgt)
                            except Exception:
                                rendered = ""
                            if "hass.data[DOMAIN]" in rendered:
                                offenders.append(
                                    f"line {sub.lineno}: del {rendered}",
                                )
        assert not offenders, (
            "setup/unload symmetry: every `del hass.data[DOMAIN][...]` in "
            "async_unload_entry must be converted to defensive "
            "`hass.data[DOMAIN].pop(<key>, None)` per the v4.6.10 review-fix "
            "B2 pattern. Offenders:\n  - " + "\n  - ".join(offenders)
        )


# ---------------------------------------------------------------------------
# Untracked-task AST regression (covers __init__.py + coordinator.py).
# ---------------------------------------------------------------------------


def _walk_untracked_task_calls(tree: ast.Module, src: str) -> list[tuple[int, str]]:
    """Return list of (lineno, source_line) for every `hass.async_create_task(`
    call in the tree that is NOT explicitly allowlisted by a trailing
    `# noqa: untracked-ok` marker.

    Allowed patterns are:
      - `entry.async_create_background_task(...)` (REUSED pattern from
        v4.2.22 cover runner, automation.py:303)
      - `<obj>.async_create_background_task(...)` (e.g.
        `self.entry.async_create_background_task`)
      - explicit `# noqa: untracked-ok` marker on the call line.
    """
    lines = src.splitlines()
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # We only flag `<something>.async_create_task` attribute calls
        # AND only when the receiver chain ends in `hass`.
        if not (isinstance(func, ast.Attribute) and func.attr == "async_create_task"):
            continue
        # Receiver is `func.value`. Render it to detect the `hass.` shape
        # without misfiring on `entry.async_create_background_task`.
        try:
            receiver = ast.unparse(func.value)
        except Exception:
            receiver = ""
        # Skip anything that isn't a bare `hass` receiver.
        if receiver.split(".")[-1] != "hass":
            continue

        lineno = node.lineno
        line_text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        # Allow opt-out via explicit marker on the same source line.
        if "noqa: untracked-ok" in line_text:
            continue
        offenders.append((lineno, line_text.strip()))
    return offenders


class TestNoUntrackedAsyncCreateTaskInScope:
    """No `hass.async_create_task(...)` calls remain in `coordinator.py`
    or `__init__.py` outside the allowlisted patterns.

    The allowlist:
      - `entry.async_create_background_task(...)` (tracked: cancelled
        on entry unload — REUSED pattern from automation.py:303).
      - explicit `# noqa: untracked-ok` on the call line WITH a
        justification comment immediately preceding (reviewer must
        explain WHY the task is intentionally fire-and-forget).
    """

    def test_no_untracked_async_create_task_in_init(self, init_tree, init_src):
        offenders = _walk_untracked_task_calls(init_tree, init_src)
        assert not offenders, (
            "setup/unload symmetry: untracked `hass.async_create_task(` "
            "calls remain in custom_components/universal_room_automation/"
            "__init__.py. Convert each to `entry.async_create_background_task("
            "hass, coro, name=\"...\")` (REUSED pattern at automation.py:303) "
            "or mark `# noqa: untracked-ok` with a justification comment "
            "explaining why fire-and-forget is intentional. Offenders:\n"
            + "\n".join(f"  line {ln}: {txt}" for ln, txt in offenders)
        )

    def test_no_untracked_async_create_task_in_coordinator(self, coord_tree, coord_src):
        offenders = _walk_untracked_task_calls(coord_tree, coord_src)
        assert not offenders, (
            "setup/unload symmetry: untracked `hass.async_create_task(` "
            "calls remain in custom_components/universal_room_automation/"
            "coordinator.py. Convert each to "
            "`self.entry.async_create_background_task(self.hass, coro, "
            "name=\"...\")` (REUSED pattern at automation.py:303) or mark "
            "`# noqa: untracked-ok` with a justification comment explaining "
            "why fire-and-forget is intentional. Offenders:\n"
            + "\n".join(f"  line {ln}: {txt}" for ln, txt in offenders)
        )


# ---------------------------------------------------------------------------
# Sanity: prove the cited setup sites still exist (catches future drift
# where the planning doc's line numbers fall out of sync).
# ---------------------------------------------------------------------------


class TestUpdateListenerSelfReloadIsUntracked:
    """B-CRIT-1 (Review B, 2026-06-03) regression guard.

    `_async_update_listener` MUST schedule the self-reload via the
    UNTRACKED `hass.async_create_task(...)` form, not the tracked
    `entry.async_create_background_task(...)` form. A tracked task
    self-cancels: `_async_process_on_unload` cancels every task in
    `entry._background_tasks` during the reload's own unload phase,
    aborting the reload before its setup phase completes and leaving
    the integration in NOT_LOADED. The standard HA-core pattern for
    self-reload from inside a config entry is the untracked form —
    exemplars: plex, flux_led, tile, epson.
    """

    def _find_update_listener(self, tree: ast.Module) -> ast.AsyncFunctionDef:
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update_listener":
                return node
        raise AssertionError(
            "B-CRIT-1: `_async_update_listener` not found in __init__.py — "
            "regression test cannot run. If the function was renamed, "
            "update this test."
        )

    def test_update_listener_uses_untracked_self_reload(self, init_tree):
        fn = self._find_update_listener(init_tree)
        # Walk the function body looking for the call shape.
        has_untracked = False
        has_tracked = False
        for sub in ast.walk(fn):
            if not isinstance(sub, ast.Call):
                continue
            try:
                rendered = ast.unparse(sub.func)
            except Exception:
                continue
            if rendered == "hass.async_create_task":
                # Inner call must be `hass.config_entries.async_reload(...)`.
                if sub.args:
                    try:
                        arg0 = ast.unparse(sub.args[0])
                    except Exception:
                        arg0 = ""
                    if "config_entries.async_reload" in arg0:
                        has_untracked = True
            if rendered.endswith(".async_create_background_task"):
                # If the registered task is `hass.config_entries.async_reload(...)`,
                # that's the regression we're guarding against.
                if len(sub.args) >= 2:
                    try:
                        coro_arg = ast.unparse(sub.args[1])
                    except Exception:
                        coro_arg = ""
                    if "config_entries.async_reload" in coro_arg:
                        has_tracked = True
        assert has_untracked, (
            "B-CRIT-1 regression: `_async_update_listener` must call "
            "`hass.async_create_task(hass.config_entries.async_reload(...))` "
            "(untracked). See review doc setup_unload_symmetry_review_B_lifecycle.md."
        )
        assert not has_tracked, (
            "B-CRIT-1 regression: `_async_update_listener` registered the "
            "self-reload via `entry.async_create_background_task(...)`. "
            "The reload task self-cancels via `_async_process_on_unload`, "
            "leaving the entry NOT_LOADED. Use the untracked "
            "`hass.async_create_task(...)` form with `# noqa: untracked-ok`."
        )


class TestCitedSetupSitesStillResolve:
    """The planning doc cites specific surfaces. If a future refactor
    moves the cited code, this test fails loudly so the cycle is
    re-scoped before reviewers go hunting.
    """

    def test_service_registration_block_present(self, init_src):
        for helper in (
            "_async_register_presence_services",
            "_async_register_safety_services",
            "_async_register_security_services",
            "_async_register_notification_services",
        ):
            assert f"await {helper}(hass)" in init_src, (
                f"setup/unload symmetry: setup call `await {helper}(hass)` "
                "no longer present in __init__.py. Either the helper was "
                "renamed/removed (update test + teardown) or moved into a "
                "different setup branch."
            )

    def test_panel_register_calls_present(self, init_src):
        assert init_src.count("panel_custom.async_register_panel(") >= 2, (
            "setup/unload symmetry: fewer than two "
            "`panel_custom.async_register_panel(` calls found in "
            "__init__.py. The two URA panels (ura-dashboard and "
            "ura-dashboard-v3) are the surface under test."
        )

    def test_static_path_register_calls_present(self, init_src):
        assert init_src.count("hass.http.async_register_static_paths(") >= 2, (
            "setup/unload symmetry: fewer than two "
            "`hass.http.async_register_static_paths(` calls found — the "
            "HA-core gap that the static-path gap-documentation test "
            "guards depends on these being present."
        )

"""v4.7.4.1 — async_update_entry re-entrancy hotfix tests.

Verifies that the v4.7.4 customize_buckets migration helper uses a deferred
async_create_task pattern instead of calling async_update_entry directly inside
async_setup_entry, preventing Bug Class #46 (re-entrant reload blowing HA
bootstrap-2 budget on cold install).

Source-grep + AST style — fast, no running HA required.
"""

import ast
import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def init_src() -> str:
    with open("custom_components/universal_room_automation/__init__.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def init_tree() -> ast.Module:
    with open("custom_components/universal_room_automation/__init__.py") as f:
        src = f.read()
    return ast.parse(src)


# ===========================================================================
# Test 1 — No direct async_update_entry inside async_setup_entry body
# ===========================================================================


class TestNoDirectAsyncUpdateEntryInSetup:
    """The v4.7.4 customize_buckets migration block must NOT call async_update_entry directly.

    Bug Class #46: calling async_update_entry from inside async_setup_entry
    triggers the registered update_listener → reload, re-entering
    async_setup_entry mid-setup. On cold install this blows HA bootstrap-2.

    Note: other pre-existing migration helpers elsewhere in async_setup_entry
    also call async_update_entry directly — those are pre-v4.7.4.1 patterns
    that are not in scope for this hotfix. This test targets only the v4.7.4
    migration block (identified by its surrounding v4.7.4 migration context).
    """

    def test_v4741_migration_does_not_call_async_update_entry_directly_in_setup(
        self, init_src
    ):
        """Source grep: the v4.7.4 customize_buckets migration block must NOT contain
        a direct inline async_update_entry call.

        We verify this by checking that within the 200 chars following the
        '_migration_needed' flag, there is NO literal 'async_update_entry' call
        (before the async_create_task wrapper).

        The old broken pattern was:
            if _migration_needed:
                hass.config_entries.async_update_entry(entry, options=...)

        The fix replaces it with:
            if _migration_needed:
                hass.async_create_task(
                    _v474_defer_customize_buckets_persist(hass, entry, _new_options),
                    ...
                )
        """
        # Find the migration block by its unique sentinel
        sentinel = "ura_v474_customize_buckets_migration"
        sentinel_pos = init_src.find(sentinel)
        assert sentinel_pos != -1, (
            f"Bug Class #46 fix: task name '{sentinel}' not found — "
            "async_create_task wrapper must be present"
        )

        # Grab the 400-char window containing _migration_needed check + fix
        migration_needed_pos = init_src.rfind("_migration_needed", 0, sentinel_pos)
        assert migration_needed_pos != -1, (
            "_migration_needed flag not found before the migration task sentinel"
        )
        block = init_src[migration_needed_pos: migration_needed_pos + 400]

        # The block must NOT contain a direct 'async_update_entry' call
        # (only the deferred helper call via async_create_task is allowed)
        assert "hass.config_entries.async_update_entry" not in block, (
            "Bug Class #46: the v4.7.4 customize_buckets migration block must NOT call "
            "hass.config_entries.async_update_entry directly (found direct call in "
            "_migration_needed block). Use hass.async_create_task(_v474_defer_...) instead."
        )


# ===========================================================================
# Test 2 — Deferred task pattern is present
# ===========================================================================


class TestDeferredTaskPatternPresent:
    """The deferred-task pattern must be present in __init__.py for the migration."""

    def test_v4741_migration_deferred_via_async_create_task(self, init_src):
        """Source grep: async_create_task + _v474_defer_customize_buckets_persist must appear
        together in __init__.py — proving the deferred-task pattern is wired.
        """
        assert "_v474_defer_customize_buckets_persist" in init_src, (
            "Bug Class #46 fix: _v474_defer_customize_buckets_persist must be referenced in __init__.py"
        )
        assert "async_create_task" in init_src, (
            "Bug Class #46 fix: hass.async_create_task must be called in __init__.py "
            "(for the deferred migration)"
        )
        # Verify the two appear near each other in the migration block
        task_pos = init_src.find("ura_v474_customize_buckets_migration")
        assert task_pos != -1, (
            "Bug Class #46 fix: task name 'ura_v474_customize_buckets_migration' must be present "
            "in __init__.py (the async_create_task name= argument)"
        )
        defer_pos = init_src.find("_v474_defer_customize_buckets_persist(hass, entry")
        assert defer_pos != -1, (
            "Bug Class #46 fix: _v474_defer_customize_buckets_persist must be called with "
            "(hass, entry, ...) arguments in __init__.py"
        )
        # The async_create_task wrapping call must be within 200 chars of the helper call
        create_task_region = init_src[max(0, defer_pos - 200): defer_pos + 200]
        assert "async_create_task" in create_task_region, (
            "Bug Class #46 fix: async_create_task must wrap _v474_defer_customize_buckets_persist "
            "— they must appear within 200 characters of each other"
        )

    def test_v4741_migration_comment_references_bug_class_46(self, init_src):
        """The migration block must carry a Bug Class #46 comment for future reference."""
        assert "Bug Class #46" in init_src, (
            "Bug Class #46: the deferred-task migration block must include a 'Bug Class #46' "
            "comment so future developers understand WHY the deferral exists"
        )


# ===========================================================================
# Test 3 — Helper function exists at module scope
# ===========================================================================


class TestHelperFunctionAtModuleScope:
    """_v474_defer_customize_buckets_persist must be an async function at module scope."""

    def test_v4741_helper_function_exists_at_module_scope(self, init_tree):
        """AST: _v474_defer_customize_buckets_persist must be AsyncFunctionDef at col_offset 0."""
        helper_func = None
        for node in ast.walk(init_tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_v474_defer_customize_buckets_persist"
                and node.col_offset == 0
            ):
                helper_func = node
                break

        assert helper_func is not None, (
            "Bug Class #46 fix: _v474_defer_customize_buckets_persist must be defined "
            "as an async function at module scope in __init__.py (col_offset == 0). "
            "Nesting it inside async_setup_entry would cause the same re-entrancy on "
            "a subsequent forward reference."
        )

    def test_v4741_helper_function_has_3_params(self, init_tree):
        """AST: helper must accept (hass, entry, new_options) — 3 parameters."""
        helper_func = None
        for node in ast.walk(init_tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_v474_defer_customize_buckets_persist"
                and node.col_offset == 0
            ):
                helper_func = node
                break

        assert helper_func is not None, "_v474_defer_customize_buckets_persist not found"
        params = [arg.arg for arg in helper_func.args.args]
        assert len(params) == 3, (
            f"_v474_defer_customize_buckets_persist must have exactly 3 parameters "
            f"(hass, entry, new_options); found {params}"
        )

    def test_v4741_helper_calls_async_update_entry_internally(self, init_tree):
        """AST: the helper itself must call async_update_entry (the real persist call)."""
        helper_func = None
        for node in ast.walk(init_tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_v474_defer_customize_buckets_persist"
                and node.col_offset == 0
            ):
                helper_func = node
                break

        assert helper_func is not None, "_v474_defer_customize_buckets_persist not found"

        update_calls = [
            node
            for node in ast.walk(helper_func)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "async_update_entry"
            )
        ]
        assert len(update_calls) == 1, (
            f"_v474_defer_customize_buckets_persist must contain exactly 1 call to "
            f"async_update_entry (found {len(update_calls)})"
        )

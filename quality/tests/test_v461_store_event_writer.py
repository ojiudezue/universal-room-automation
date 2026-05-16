"""v4.6.1 D0 — store_event() canonical writer.
v4.6.3 D7/D9 update: store_anomaly() wrapper was deleted; tests updated.

Source-grep + AST tests verify:
- store_event() exists on AnomalyDetector with correct signature
- store_event() inserts all new AnomalyEvent columns
- store_anomaly() wrapper is DELETED (v4.6.3 D7 migration complete)
- store_event() uses local import for AnomalyEvent (Bug Class #34)
"""

import ast
from pathlib import Path


def _diag_src() -> str:
    return Path(
        "custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py"
    ).read_text()


def _get_class_body(src: str, class_name: str) -> str:
    """Extract the source text of a class body."""
    idx = src.find(f"class {class_name}(")
    if idx < 0:
        idx = src.find(f"class {class_name}:")
    assert idx >= 0, f"Class {class_name} not found"
    # Find next top-level class
    next_class = src.find("\nclass ", idx + 1)
    return src[idx: next_class if next_class > 0 else None]


def test_store_event_method_exists():
    src = _diag_src()
    body = _get_class_body(src, "AnomalyDetector")
    assert "async def store_event(" in body, (
        "AnomalyDetector must have async def store_event()"
    )


def test_store_event_accepts_event_parameter():
    src = _diag_src()
    body = _get_class_body(src, "AnomalyDetector")
    # signature: store_event(self, event: "AnomalyEvent") -> Optional[int]
    assert "store_event" in body
    assert "event" in body


def test_store_event_delegates_to_db_dao():
    """v4.6.1 review fix B2/F1: store_event() must delegate to the single
    database.save_anomaly_event() DAO so the anomaly_log INSERT exists in
    exactly one place. Canary sites without an AnomalyDetector instance
    call save_anomaly_event() directly; without delegation here, the
    canonical path becomes a separate write-path (the original review bug).
    """
    src = _diag_src()
    idx = src.find("async def store_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "save_anomaly_event(event)" in block, (
        "store_event must delegate to database.save_anomaly_event(event); "
        "raw INSERT here recreates the copy-paste-INSERT anti-pattern "
        "review fix B2/F1 eliminated."
    )
    # And it must NOT contain a raw INSERT — that would mean delegation
    # was undone and we're back to the bug.
    assert "INSERT INTO anomaly_log" not in block, (
        "store_event must NOT contain INSERT INTO anomaly_log — that SQL "
        "now lives only in database.save_anomaly_event() (review fix B2/F1)."
    )


def test_save_anomaly_event_dao_exists():
    """The canonical DAO must exist in database.py and accept an AnomalyEvent."""
    src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    assert "async def save_anomaly_event(self, event)" in src, (
        "database.py must define async save_anomaly_event(self, event)"
    )


def test_save_anomaly_event_inserts_new_columns():
    """The DAO INSERT references all 6 new anomaly_log columns."""
    src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    idx = src.find("async def save_anomaly_event(self, event)")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    for col in ("event_class", "recovery_at", "correlation_id", "entity_id", "room_id", "person_id"):
        assert col in block, f"save_anomaly_event INSERT must reference column '{col}'"


def test_store_anomaly_wrapper_deleted_v463():
    """v4.6.3 D7: store_anomaly() wrapper must be deleted.

    v4.6.1 preserved store_anomaly() as a backward-compat wrapper.
    v4.6.3 D2-D6 migrated all callers to store_event(AnomalyEvent(...))
    directly, so D7 deleted the wrapper.  This test enforces the deletion
    is permanent — re-adding the wrapper would re-introduce the old
    ad-hoc payload construction pattern the migration was meant to eliminate.
    """
    src = _diag_src()
    body = _get_class_body(src, "AnomalyDetector")
    assert "async def store_anomaly(" not in body, (
        "v4.6.3 D7: store_anomaly() wrapper must be deleted — "
        "all callers migrated to store_event(AnomalyEvent(...)) in v4.6.3"
    )


def test_store_event_is_the_single_write_path():
    """v4.6.3 D7: store_event() is now the ONLY write method on AnomalyDetector.

    After D7 deletion, store_event() is no longer backed by store_anomaly().
    It is the canonical entrypoint; callers must construct AnomalyEvent directly.
    """
    src = _diag_src()
    body = _get_class_body(src, "AnomalyDetector")
    assert "async def store_event(" in body, (
        "store_event() must still exist as the canonical anomaly write path after D7"
    )
    # The delegator chain is gone — no method definition for store_anomaly
    assert "async def store_anomaly(" not in body, (
        "store_anomaly() method must not exist on AnomalyDetector — deleted in D7"
    )


def test_store_event_is_thin_delegator():
    """store_event() body is small after B2/F1 fix — it constructs no SQL,
    holds no import, just delegates to save_anomaly_event() and logs.
    """
    src = _diag_src()
    idx = src.find("async def store_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    # Sanity: must NOT carry json import or large SQL chunks anymore.
    assert "import json" not in block, (
        "store_event no longer constructs JSON — that's done inside the DAO. "
        "The previous local `import json` was part of the bypassed copy-paste."
    )
    assert "VALUES (?, ?, ?" not in block, (
        "store_event must not contain raw INSERT VALUES; delegation only."
    )


def test_store_event_no_module_level_anomaly_event_import():
    """Bug Class #34: coordinator_diagnostics must not module-level import anomaly_event.

    v4.6.1: original test verified store_anomaly() used local import.
    v4.6.3 D7/D9: store_anomaly() is deleted. store_event() accepts a duck-typed
    AnomalyEvent — it doesn't need to import the class at all (the caller imports it).
    The critical constraint is that coordinator_diagnostics must NOT import anomaly_event
    at module level to avoid circular import risk.
    """
    src = _diag_src()
    lines = src.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        # Module-level import = line starts at column 0 (no indent) and imports anomaly_event
        if ("from .anomaly_event import" in stripped or "import anomaly_event" in stripped):
            indent = len(line) - len(stripped)
            assert indent > 0, (
                f"Bug Class #34: coordinator_diagnostics.py line {i+1} imports anomaly_event "
                "at module level — must be function-local to prevent circular import"
            )


def test_save_anomaly_event_severity_stored_as_int():
    """Severity stored as int(event.severity) by the DAO — AnomalySeverity is IntEnum."""
    src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    idx = src.find("async def save_anomaly_event(self, event)")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "int(event.severity)" in block, (
        "save_anomaly_event must store int(event.severity) — AnomalySeverity is IntEnum"
    )


def test_store_event_logs_info_on_success():
    """store_event() must log at INFO on successful insert (significant state change)."""
    src = _diag_src()
    idx = src.find("async def store_event(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_LOGGER.info(" in block, (
        "store_event must _LOGGER.info() on successful persist "
        "(significant state change per coding standards)"
    )


def test_save_anomaly_event_warning_on_exception():
    """Failures in the canonical DAO log at WARNING with coordinator/type
    context (so canary writes that go directly through the DAO without
    their own try/except still produce traceable log lines).
    """
    src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    idx = src.find("async def save_anomaly_event(self, event)")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 3000]
    assert "_LOGGER.warning(" in block, (
        "save_anomaly_event failure must log at WARNING level"
    )
    assert "coordinator=" in block, (
        "save_anomaly_event WARNING must include coordinator context "
        "for traceability without per-caller try/except wrappers"
    )


def test_severity_mapping_now_callers_responsibility():
    """v4.6.3 D7/D9: severity mapping is now each caller's responsibility.

    v4.6.1: store_anomaly() wrapper handled NOMINAL→INFO severity mapping.
    v4.6.3 D7: wrapper deleted; callers construct AnomalyEvent with the
    correct AnomalySeverity directly (INFO/WARNING/CRITICAL).  The wrapper's
    severity mapping is no longer needed — it was the source of ambiguity.

    This test verifies the wrapper is gone (so its old mapping code can't
    accidentally re-map severities from correctly-constructed AnomalyEvent calls).
    """
    src = _diag_src()
    # Wrapper is gone — no _severity_map in AnomalyDetector body anymore
    body = _get_class_body(src, "AnomalyDetector")
    assert "async def store_anomaly(" not in body, (
        "v4.6.3 D7: store_anomaly() wrapper (and its severity mapping) must be deleted"
    )


# ===========================================================================
# v4.6.1.1 hotfix — NOT NULL constraint handling
# ===========================================================================


def test_save_anomaly_event_legacy_payload_fallback_preserved():
    """v4.6.7 supersedes v4.6.1.1: anomaly_log schema relaxed the 5 metric
    columns to NULL-able, so the DAO no longer needs to synthesize 0.0/0
    sentinels. BUT the legacy fallback chain (dataclass field → payload
    top-level → payload['extra']) must remain for legacy callers that
    bury values in payload — that path was the original v4.6.3 B1 fix
    and protects against shape drift during future migrations.

    Asserts:
      - The simplified `_resolve_metric` helper exists in save_anomaly_event
      - It uses `payload_dict.get(field_name)` (variable-driven) for fallback
      - INSERT VALUES references the resolved locals (not raw None)
      - The pre-v4.6.7 hardcoded ` or 0.0)` sentinel chain is GONE
    """
    src = Path(
        "custom_components/universal_room_automation/database.py"
    ).read_text()
    idx = src.find("async def save_anomaly_event(self, event)")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 4000]

    # v4.6.7: the simplified helper must exist
    assert "_resolve_metric" in block, (
        "v4.6.7: save_anomaly_event must define a `_resolve_metric` helper "
        "that returns None for missing fields (no longer synthesizes sentinels)"
    )
    # v4.6.7: payload-fallback chain still in place (via the helper)
    assert "payload_dict.get(field_name)" in block, (
        "v4.6.7: _resolve_metric must keep the legacy payload-top-level "
        "fallback for callers that bury values in event.payload"
    )
    assert '_payload_extra.get(field_name)' in block, (
        "v4.6.7: _resolve_metric must keep the legacy payload['extra'] "
        "fallback for the intermediate-migration shape"
    )
    # v4.6.7: pre-v4.6.7 sentinel synthesis chain must be GONE
    assert " or 0.0)" not in block, (
        "v4.6.7: the legacy ` or 0.0)` sentinel chain must be removed. "
        "NULL now passes through honestly; the schema was relaxed to allow it."
    )
    assert " or 0)" not in block, (
        "v4.6.7: same for sample_size — ` or 0)` sentinel chain removed"
    )
    # INSERT VALUES still references the resolved locals (not literal None)
    assert "                        observed_value," in block, (
        "v4.6.7: INSERT VALUES tuple must pass the resolved `observed_value` "
        "local (which may be None now — schema permits it)"
    )
    assert "                        sample_size," in block, (
        "v4.6.7: INSERT VALUES tuple must pass `sample_size` local"
    )

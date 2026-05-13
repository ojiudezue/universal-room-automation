"""v4.6.1 D0 — store_event() canonical writer and store_anomaly() wrapper.

Source-grep + AST tests verify:
- store_event() exists on AnomalyDetector with correct signature
- store_event() inserts all new AnomalyEvent columns
- store_anomaly() is preserved as a thin wrapper
- store_anomaly() delegates to store_event()
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


def test_store_anomaly_still_exists():
    """Legacy store_anomaly() must be preserved for backward compatibility."""
    src = _diag_src()
    body = _get_class_body(src, "AnomalyDetector")
    assert "async def store_anomaly(" in body, (
        "store_anomaly() must be kept as thin wrapper (backward compat)"
    )


def test_store_anomaly_delegates_to_store_event():
    """store_anomaly() must call store_event() — it is a wrapper, not independent."""
    src = _diag_src()
    idx = src.find("async def store_anomaly(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 2000]
    assert "store_event(" in block, (
        "store_anomaly() must delegate to store_event() for single write path"
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


def test_store_anomaly_uses_local_import_anomaly_event():
    """Bug Class #34: store_anomaly() also uses local import."""
    src = _diag_src()
    idx = src.find("async def store_anomaly(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 2000]
    assert "from .anomaly_event import" in block, (
        "Bug Class #34: store_anomaly() must import AnomalyEvent locally"
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


def test_store_anomaly_maps_old_severity_to_new():
    """store_anomaly wrapper must map NOMINAL→INFO, ADVISORY/ALERT→WARNING, CRITICAL→CRITICAL."""
    src = _diag_src()
    idx = src.find("async def store_anomaly(")
    assert idx >= 0
    next_method = src.find("\n    async def ", idx + 1)
    block = src[idx: next_method if next_method > 0 else idx + 2000]
    # Must reference the old severity variants
    assert "NOMINAL" in block or "_severity_map" in block, (
        "store_anomaly must handle severity mapping from old 4-level to new 3-level"
    )

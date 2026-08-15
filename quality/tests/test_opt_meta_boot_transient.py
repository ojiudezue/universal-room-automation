"""Tests for OPT-META-BOOT-TRANSIENT-1 (2026-08-15, Tier-1 hotfix).

Kanban card: docs/planning/kanban.data.yaml (OPT-META-BOOT-TRANSIENT-1).

Failure the fix closes: `optimization_llm.py::_assemble_corpus` reads
`_last_findings` (RAM, empty after restart) while the meta pass compares
against the durable `_open_findings_count` — producing a false HIGH
"LLM cannot see problems" every restart.

Fix (per card adjudication): the coordinator pre-fetches the DB rows
into `_boot_findings_seed` during async_setup (piggybacking on the
existing rate-cap DB read at optimization.py:659, so no extra
round-trip). Corpus assembly stays SYNC — when the RAM cache is empty
it falls back to `_boot_findings_seed`.

Style: reuses the coordinator + tier constructors + `_make_hass`
scaffolding proven at `test_optimization_coordinator.py:1828-1854`
(explicit — imports from that module).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from test_optimization_coordinator import _make_hass  # noqa: E402


def _fake_db_row(target_id="kitchen", dim="comfort", sev="medium",
                 ts="2026-08-15T10:00:00+00:00", created_by="tier1_rule"):
    return {
        "id": 1,
        "timestamp": ts,
        "level": "room",
        "target_id": target_id,
        "dimension": dim,
        "severity": sev,
        "confidence": 0.8,
        "score": 0.0,
        "description": "boot-seed row",
        "proposed_action_json": None,
        "action_class": None,
        "applied_action_id": None,
        "applied_outcome": None,
        "predicted_effect_json": None,
        "observed_effect_json": None,
        "payload_json": None,
        "created_by": created_by,
    }


@pytest.mark.asyncio
async def test_empty_ram_cache_falls_back_to_db_seed():
    """Empty `_last_findings` (post-restart) + DB rows → corpus.findings_recent
    is populated from the boot seed. Confirms the meta pass no longer sees
    `findings_recent=[]` alongside nonzero `_open_findings_count`."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (  # noqa: E402
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (  # noqa: E402
        OptimizationLLMTier,
    )

    hass, _cm = _make_hass()
    db = hass.data["universal_room_automation"]["database"]
    rows = [_fake_db_row(target_id=f"room_{i}") for i in range(5)]
    db.get_recent_optimization_findings = AsyncMock(return_value=rows)
    # Async_setup elsewhere reads other DAOs — stub minimally to avoid
    # unrelated AttributeErrors.
    db.get_recent_shadow_samples = AsyncMock(return_value=[])

    coord = OptimizationCoordinator(hass)
    # Simulate post-restart state: RAM cache is empty (default).
    assert coord._last_findings == []
    await coord.async_setup()

    # Boot seed populated from the piggybacked rate-cap DB read.
    assert coord._boot_findings_seed, (
        "async_setup must populate _boot_findings_seed from the DB read"
    )
    assert len(coord._boot_findings_seed) == 5

    tier = OptimizationLLMTier(hass, coord)
    corpus = tier._assemble_corpus(tier1_findings=[])

    # Card AC: findings_recent non-empty when RAM cache empty + rows in DB.
    assert corpus.findings_recent, (
        "expected corpus.findings_recent to be populated from boot seed"
    )
    # Field-shape sanity: DB columns projected into corpus dicts.
    first = corpus.findings_recent[0]
    assert first["target_id"] == "room_0"
    assert first["dimension"] == "comfort"

    await coord.async_teardown()


@pytest.mark.asyncio
async def test_ram_cache_preferred_over_boot_seed_after_first_cycle():
    """Once the first post-boot cycle populates `_last_findings`, the RAM
    cache wins — the boot seed is ignored (avoids serving stale rows the
    RAM cache has since superseded)."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (  # noqa: E402
        OptimizationCoordinator,
        OptimizationFinding,
        OptimizationDimension,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (  # noqa: E402
        OptimizationLLMTier,
    )
    from datetime import datetime

    hass, _cm = _make_hass()
    db = hass.data["universal_room_automation"]["database"]
    db.get_recent_optimization_findings = AsyncMock(
        return_value=[_fake_db_row(target_id="stale_from_boot")],
    )
    db.get_recent_shadow_samples = AsyncMock(return_value=[])

    coord = OptimizationCoordinator(hass)
    await coord.async_setup()
    # Simulate the first cycle populating _last_findings.
    coord._last_findings = [OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="room", target_id="fresh_from_cycle",
        dimension=OptimizationDimension.COMFORT,
        severity="medium", confidence=0.8, score=0.0,
        description="cycle finding",
        dedup_key=("comfort", "fresh_from_cycle", "x"),
    )]

    tier = OptimizationLLMTier(hass, coord)
    corpus = tier._assemble_corpus(tier1_findings=[])

    # RAM cache wins — no `stale_from_boot` row in the output.
    ids = [r.get("target_id") for r in corpus.findings_recent]
    assert "fresh_from_cycle" in ids
    assert "stale_from_boot" not in ids

    await coord.async_teardown()


@pytest.mark.asyncio
async def test_boot_seed_absent_when_db_returns_empty():
    """Regression guard for the pre-fix behavior on a clean DB: empty DB
    → empty boot seed → empty `findings_recent`. No crash, no synthesized
    rows — just the current-cycle Tier-1 fanout below."""
    from custom_components.universal_room_automation.domain_coordinators.optimization import (  # noqa: E402
        OptimizationCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.optimization_llm import (  # noqa: E402
        OptimizationLLMTier,
    )

    hass, _cm = _make_hass()
    db = hass.data["universal_room_automation"]["database"]
    db.get_recent_optimization_findings = AsyncMock(return_value=[])
    db.get_recent_shadow_samples = AsyncMock(return_value=[])

    coord = OptimizationCoordinator(hass)
    await coord.async_setup()

    assert coord._boot_findings_seed == []
    tier = OptimizationLLMTier(hass, coord)
    corpus = tier._assemble_corpus(tier1_findings=[])
    assert corpus.findings_recent == []
    # Meta-pass invariant: open_findings_count must still be readable.
    assert isinstance(corpus.house.get("open_findings_count"), int)

    await coord.async_teardown()

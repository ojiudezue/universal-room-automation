"""Owner-registry golden oracle test (Phase 1).

Replays the committed golden capture at
`quality/tests/golden/owner_registry_v1.jsonl.gz` against the live
(current) `EVChargerController` + `SmartPlugController` and asserts
byte-identical output on all five surfaces the invariant in the
planning doc §0 protects:

    (a) determine_actions action list
    (b) post-tick owner-set memberships
    (c) `_save_evse_state` KV payload shape
    (d) `get_status()` owner slice
    (e) dispatch-ownership bookkeeping

On `build/owner-set-registry` at the baseline commit this passes
trivially — it is self-consistent because the golden was captured
from the same code path. Its purpose is to hold DURING the
phase-2 registry migration: any diff on any tuple = FAIL, with
enough context in the failure message to bisect to the offending
call site.

See also `quality/tools/regen_owner_golden.py` for the generator +
determinism discipline; header inside the gzip records the source
commit + pinned time anchors.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

# Import the generator machinery so the test invokes the SAME per-tuple
# driver used to capture the golden — replay is not a re-implementation.
import sys
_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import regen_owner_golden as gen  # noqa: E402


_GOLDEN = (
    Path(__file__).resolve().parent
    / "golden" / "owner_registry_v1.jsonl.gz"
)


def _load_golden() -> tuple[dict, list[dict]]:
    with gzip.open(_GOLDEN, "rt", encoding="utf-8") as fh:
        header = json.loads(fh.readline())["__header__"]
        rows = [json.loads(line) for line in fh if line.strip()]
    return header, rows


def _driver_for(row: dict):
    """Map a golden row back to the generator function that produced it."""
    event = row["event"]
    tier = row["tier"]
    if event == "merged_get_status":
        return gen._run_merged_status
    if event.startswith("prune_removed"):
        return gen._run_ev_prune if tier == "evse" else gen._run_plug_prune
    if event == "stronger_peer_holds":
        return gen._run_ev_peer_holds
    # tick events
    return gen._run_ev_tuple if tier == "evse" else gen._run_plug_tuple


def _rebuild_class_seed(class_name: str, tier: str) -> dict:
    """Look up the original class seed dict from the generator."""
    pool = (
        gen._evse_owner_classes() if tier == "evse"
        else gen._plug_owner_classes()
    )
    for cls in pool:
        if cls["__name__"] == class_name:
            return cls
    raise KeyError(f"Unknown class seed {class_name!r} for tier {tier!r}")


@pytest.fixture(scope="module")
def golden_payload():
    assert _GOLDEN.exists(), (
        f"Golden capture missing at {_GOLDEN}. Run "
        "`python3 quality/tools/regen_owner_golden.py` to regenerate."
    )
    return _load_golden()


def test_golden_header_schema(golden_payload):
    header, rows = golden_payload
    assert header["schema_version"] == gen.GOLDEN_SCHEMA_VERSION
    assert header["row_count"] == len(rows)
    assert header["pinned_utc"] == gen.PINNED_UTC.isoformat()


def test_golden_content_hash_matches_committed_header(golden_payload):
    """C-MED-1: recompute the SHA-256 of the row payload and compare
    against the committed header. A silent regen (bytes change without
    a code change) fails this loudly — the oracle cannot be
    tautologized by re-baselining it.
    """
    import hashlib, json as _json
    header, rows = golden_payload
    hasher = hashlib.sha256()
    for row in rows:
        hasher.update(_json.dumps(row, sort_keys=True, default=str).encode())
    assert hasher.hexdigest() == header["content_hash_sha256"], (
        "Golden content hash mismatch — either the golden was silently "
        "regenerated (bytes moved without a header refresh) or the row "
        "serialization drifted. Regenerate with `python3 "
        "quality/tools/regen_owner_golden.py` if the drift is intentional."
    )


def test_golden_source_commit_pinned():
    """C-MED-1: the source_commit field is populated (not 'unknown') so
    a `git bisect` starting point exists when the oracle diverges.
    """
    header, _ = _load_golden()
    assert header["source_commit"] != "unknown"
    assert len(header["source_commit"]) == 40  # full git sha1


def test_golden_byte_identical_replay(golden_payload):
    """Replay every tuple; any diff on any of the 5 surfaces fails.

    The failure message names the tuple identity + first differing
    surface so bisecting is straightforward during phase-2 migration.
    """
    _, rows = golden_payload

    with gen._monkeypatch_ctx() as mp:
        for idx, expected in enumerate(rows):
            tier = expected["tier"]
            event = expected["event"]
            if event == "merged_get_status":
                ev_cls = _rebuild_class_seed(expected["ev_class"], "evse")
                plug_cls = _rebuild_class_seed(expected["plug_class"], "plug")
                observed = gen._run_merged_status(
                    ev_cls, plug_cls, expected["tou"], mp,
                )
            elif event.startswith("prune_removed") or event == "stronger_peer_holds":
                class_seed = _rebuild_class_seed(expected["class"], tier)
                driver = _driver_for(expected)
                observed = driver(class_seed, mp)
            else:
                class_seed = _rebuild_class_seed(expected["class"], tier)
                driver = _driver_for(expected)
                observed = driver(
                    class_seed,
                    expected["tou"],
                    expected["soc"],
                    event,
                    mp,
                )

            # sort_keys=True normalization applied to both sides so
            # dict ordering differences don't create phantom diffs.
            exp_json = json.dumps(expected, sort_keys=True, default=str)
            obs_json = json.dumps(observed, sort_keys=True, default=str)
            if exp_json != obs_json:
                # Identify first differing top-level surface for the
                # failure message.
                diffing_keys = [
                    k for k in expected
                    if json.dumps(expected.get(k), sort_keys=True, default=str)
                    != json.dumps(observed.get(k), sort_keys=True, default=str)
                ]
                # C-LOW-1: merged rows use `ev_class`/`plug_class` keys,
                # not `class`. Use `.get(...)` for diagnostics so the
                # failure message doesn't raise KeyError on merged rows.
                _cls_label = (
                    expected.get("class")
                    or f"ev={expected.get('ev_class')!r} "
                       f"plug={expected.get('plug_class')!r}"
                )
                pytest.fail(
                    "Owner-registry golden diverged at row "
                    f"{idx} tier={tier} class={_cls_label} "
                    f"tou={expected.get('tou')!r} soc={expected.get('soc')!r} "
                    f"event={event!r}\n"
                    f"  first differing surfaces: {diffing_keys}\n"
                    f"  expected: {exp_json[:400]}...\n"
                    f"  observed: {obs_json[:400]}...",
                )

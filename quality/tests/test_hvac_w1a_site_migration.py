"""HVAC-W1-A Stage A — per-site migration behavioural anchors.

For each of the 7 migrated set_hvac_mode sites (B1..B7), the test locates
the enclosing production function and asserts:

  1. That function's source contains an ``emit_set_hvac_mode`` call.
  2. That function's source contains the required kwargs
     (``site=``, ``zone_id=``, ``reason=``, ``blocking=``).
  3. The site tag matches the expected name from the plan (D3 table).
  4. That function's source does NOT contain a raw
     ``services.async_call("climate", "set_hvac_mode", ...)`` — this is
     the per-site "neuter drill": if a builder reverts the site to the
     original raw call, this test goes RED for that specific site.

Also verifies the S6/S7/SA required-kwarg discriminators (F3): the plan
adds ``site``/``zone_id``/``reason`` to sites that previously omitted
them; each site's source now names those kwargs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DC = ROOT / "custom_components" / "universal_room_automation" / "domain_coordinators"


def _funcs_by_name(path: Path):
    """Return {qualname: source_text} for every function/method in file."""
    src = path.read_text()
    tree = ast.parse(src, filename=str(path))
    out: dict[str, str] = {}
    src_lines = src.splitlines()

    def walk(node, prefix=""):
        for child in getattr(node, "body", []) or []:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{prefix}{child.name}" if prefix else child.name
                start = child.lineno - 1
                end = getattr(child, "end_lineno", None)
                body = "\n".join(src_lines[start:end])
                out[qname] = body
                walk(child, prefix=f"{qname}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix=f"{child.name}.")
    walk(tree)
    return out


def _find_site(funcs: dict[str, str], site_tag: str) -> str | None:
    """Return the FIRST function source containing the given site tag."""
    for _q, body in funcs.items():
        if f'site="{site_tag}"' in body or f"site='{site_tag}'" in body:
            return body
    return None


SITES = [
    # (file, site_tag, verb, expected_blocking_literal)
    ("hvac.py",           "B1_heat_cool_enforcer",         "emit_set_hvac_mode", "True"),
    ("hvac_egress.py",    "B2_egress_pause",               "emit_set_hvac_mode", "True"),
    ("hvac_egress.py",    "B3_egress_resume",              "emit_set_hvac_mode", "True"),
    ("hvac_override.py",  "B4_override_revert_heat_cool",  "emit_set_hvac_mode", "False"),
    ("hvac_override.py",  "B5_ac_reset_off",               "emit_set_hvac_mode", "True"),
    ("hvac_override.py",  "B6_ac_reset_restore",           "emit_set_hvac_mode", "True"),
    ("hvac_override.py",  "B7_ac_reset_restore_retry",     "emit_set_hvac_mode", "True"),
]


@pytest.mark.parametrize("filename,site_tag,verb,blocking_literal", SITES)
def test_migrated_site_uses_funnel_with_required_kwargs(
    filename, site_tag, verb, blocking_literal,
):
    """Per-site behavioural anchor + neuter drill (D3 + D5).

    * Locates the enclosing function via a source-scan for ``site=<tag>``.
    * Asserts the funnel call is present with required kwargs.
    * Asserts NO raw climate service call remains in the enclosing
      function (neuter drill: reverting the site to the pre-migration
      raw call goes RED here).
    """
    path = DC / filename
    funcs = _funcs_by_name(path)
    body = _find_site(funcs, site_tag)
    assert body is not None, (
        f"site tag '{site_tag}' not found in any function in {filename}"
    )
    # (1) funnel is called.
    assert verb in body, (
        f"site '{site_tag}' does not call {verb}"
    )
    # (2) required kwargs.
    for kwarg in ("site=", "zone_id=", "reason=", "blocking="):
        assert kwarg in body, (
            f"site '{site_tag}' missing required kwarg {kwarg}"
        )
    # (3) blocking literal preserved.
    assert re.search(rf"blocking=\s*{blocking_literal}", body), (
        f"site '{site_tag}' expected blocking={blocking_literal}"
    )
    # (4) neuter drill: no raw climate services call inside this fn.
    raw_pat = re.compile(
        r'services\.async_call\(\s*[\'"]climate[\'"]', re.MULTILINE,
    )
    assert not raw_pat.search(body), (
        f"site '{site_tag}' still contains a raw climate services call"
    )


def test_S6_nudge_restore_setpoint_has_required_kwargs():
    """F3 discriminator: S6 previously called emit_set_temperature with
    NO site/zone_id/reason; the migration added them."""
    body = _find_site(
        _funcs_by_name(DC / "hvac_override.py"),
        "S6_nudge_restore_setpoint",
    )
    assert body is not None, "S6_nudge_restore_setpoint site missing"
    assert "emit_set_temperature" in body
    for kw in ("site=", "zone_id=", "reason="):
        assert kw in body


def test_S7_nudge_restore_preset_has_required_kwargs():
    body = _find_site(
        _funcs_by_name(DC / "hvac_override.py"),
        "S7_nudge_restore_preset",
    )
    assert body is not None, "S7_nudge_restore_preset site missing"
    assert "emit_set_preset_mode" in body
    for kw in ("site=", "zone_id=", "reason="):
        assert kw in body


def test_startup_audit_nudge_preset_restore_has_required_kwargs():
    body = _find_site(
        _funcs_by_name(DC / "hvac_excursion.py"),
        "startup_audit_nudge_preset_restore",
    )
    assert body is not None, "startup_audit site missing"
    assert "emit_set_preset_mode" in body
    for kw in ("site=", "zone_id=", "reason="):
        assert kw in body


def test_ai_rule_refusal_blocks_all_climate_domain():
    """D5-b: coordinator.py must refuse ALL `climate` services from
    AI-rules, not just the three verbs (INV-A extended)."""
    src = (
        ROOT / "custom_components" / "universal_room_automation"
        / "coordinator.py"
    ).read_text()
    # The block is now on the whole climate domain — a set-membership
    # check against three verbs would fail this assertion.
    assert re.search(
        r'if\s+domain\s*==\s*[\'"]climate[\'"]\s*:', src,
    ), "AI-rule climate refusal must gate on domain == 'climate'"


def test_hvac_setpoint_exports_emit_set_hvac_mode():
    """D1: the third funnel exists."""
    src = (DC / "hvac_setpoint.py").read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "emit_set_hvac_mode":
            return
    raise AssertionError("emit_set_hvac_mode not defined in hvac_setpoint.py")


def test_dynamic_domain_allowlist_carries_optimization_reason():
    src = (DC / "hvac_const.py").read_text()
    assert "DYNAMIC_DOMAIN_ALLOWLIST" in src
    assert "optimization.py" in src
    assert "CLIMATE_WRITE_LOG_IMPORTANCE" in src

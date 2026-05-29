"""v4.7.5 D3 — Lazy Canonical Resolution: iter_canonical_hvac_zones is
runtime-only.

Per PLANNING_v4.7.5 §D3 and QUALITY_CONTEXT.md "Lazy Canonical Resolution",
`iter_canonical_hvac_zones` is allowed ONLY in:
  - `custom_components/universal_room_automation/domain_coordinators/`
    (coordinator runtime + per-tick evaluation)
  - per-zone platform setup in `button.py`, `number.py`, `sensor.py`
    (Bug Class #36 thermostat-keyed dedup)
  - `quality/tests/`

`config_flow.py` MUST NOT reference it — the picker shows RAW house zones
and the runtime side resolves canonical lazily. This locks the v4.7.5
contract against future regressions.
"""

import ast
import os


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_COMPONENT_DIR = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation"
)


def _file_has_real_canonical_reference(path):
    """Return True iff the file contains an actual import/call/attribute
    reference to iter_canonical_hvac_zones (NOT just a docstring mention).
    """
    try:
        with open(path) as f:
            src = f.read()
    except (OSError, UnicodeDecodeError):
        return False
    if "iter_canonical_hvac_zones" not in src:
        return False
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # Conservative: if we can't parse, treat the textual hit as real
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "iter_canonical_hvac_zones":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "iter_canonical_hvac_zones":
            return True
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "iter_canonical_hvac_zones":
                    return True
        if isinstance(node, ast.FunctionDef) and node.name == "iter_canonical_hvac_zones":
            return True
    return False


def _collect_callers():
    """Walk the component tree; return relative-path hits for the symbol."""
    hits = []
    for root, _dirs, files in os.walk(_COMPONENT_DIR):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(root, fn)
            if _file_has_real_canonical_reference(full):
                rel = os.path.relpath(full, _COMPONENT_DIR)
                hits.append(rel)
    return hits


def test_v475_d3_no_canonical_in_config_flow():
    """config_flow.py must not import or call iter_canonical_hvac_zones.

    Docstring/comment MENTIONS of the symbol are fine (we document the rule
    in-source). The AST check rejects real import/call references.
    """
    cf_path = os.path.join(_COMPONENT_DIR, "config_flow.py")
    assert not _file_has_real_canonical_reference(cf_path), (
        "v4.7.5 D3: config_flow.py contains an AST reference (Name, Attribute, "
        "or ImportFrom) to iter_canonical_hvac_zones. The picker / options-flow "
        "handlers MUST NOT call the canonical merge — derive raw zones from "
        "entry.options. See QUALITY_CONTEXT.md 'Lazy Canonical Resolution'."
    )


def test_v475_d3_canonical_callers_all_in_allowlist():
    """Every file that references iter_canonical_hvac_zones must be on the allowlist."""
    allowlist_prefixes = (
        "domain_coordinators/",     # coordinator runtime
        "button.py",                 # per-zone platform setup
        "number.py",                 # per-zone platform setup
        "sensor.py",                 # per-zone platform setup
    )
    hits = _collect_callers()
    violations = [
        h for h in hits
        if not any(
            h == prefix or h.startswith(prefix) for prefix in allowlist_prefixes
        )
    ]
    assert not violations, (
        "v4.7.5 D3: unexpected iter_canonical_hvac_zones references outside "
        f"the runtime allowlist: {violations}. Add to the allowlist after "
        "verifying the new caller is a runtime path, OR refactor it to read "
        "raw zones from entry.options."
    )


def test_v475_d3_hvac_zones_caller_inventory_comment_present():
    """hvac_zones.py must carry the v4.7.5 caller-inventory comment block."""
    with open(os.path.join(_COMPONENT_DIR, "domain_coordinators", "hvac_zones.py")) as f:
        src = f.read()
    assert "v4.7.5 D3 — Caller inventory for iter_canonical_hvac_zones" in src, (
        "v4.7.5 D3: caller-inventory comment block missing from hvac_zones.py. "
        "This block documents the rule and enumerates approved call sites."
    )
    assert "Bug Class #47" in src or "config_flow.py" in src, (
        "v4.7.5 D3: caller-inventory comment must mention the forbidden "
        "config_flow.py code path."
    )


def test_v475_d3_quality_context_has_lazy_canonical_section():
    """QUALITY_CONTEXT.md must document Lazy Canonical Resolution."""
    qc_path = os.path.join(_REPO_ROOT, "docs", "QUALITY_CONTEXT.md")
    with open(qc_path) as f:
        src = f.read()
    assert "Lazy Canonical Resolution" in src, (
        "v4.7.5 D3: QUALITY_CONTEXT.md must contain a 'Lazy Canonical "
        "Resolution' section describing the architectural rule."
    )
    assert "v4.7.5" in src, (
        "v4.7.5 D3: QUALITY_CONTEXT.md Lazy Canonical Resolution section "
        "must cite v4.7.5 (filed 2026-05-29)."
    )


def test_v475_d3_energy_consumer_splits_merged_name():
    """energy.py's DPM evaluator must resolve canonical names back to
    constituent raw house zones via " + " split fallback."""
    with open(os.path.join(_COMPONENT_DIR, "domain_coordinators", "energy.py")) as f:
        src = f.read()
    assert "Lazy Canonical Resolution" in src, (
        "v4.7.5 D3: energy.py's DPM evaluator must reference Lazy Canonical "
        "Resolution at the canonical→constituent resolution site."
    )
    assert '" + "' in src and "zone_name.split" in src, (
        "v4.7.5 D3: energy.py must split merged canonical zone_name on "
        "' + ' to resolve to constituent raw house zones at read time."
    )

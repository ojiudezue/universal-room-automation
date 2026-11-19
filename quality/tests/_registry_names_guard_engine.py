"""Registry-not-names guard engine (card REGISTRY-NOT-NAMES-1; spec
``docs/planning/AUDIT_registry_not_names_sweep_2026_11_13.md`` §6.1).

Operator rule (CLAUDE.md "Registry, never name guessing"): never infer an
entity's platform / NVR family / device / person / room from its entity_id
string, suffix or slug. This engine finds the AST shapes those guesses take.

AST ONLY: it parses source text and imports no production module.
``scan_tree({relpath: source})`` scans an in-memory tree, so a test can scan a
copy with one site changed. A hit is keyed ``(rule, file, qualname)``;
``qualname`` = enclosing classes and defs joined by ``.`` (``<module>`` at top
level; a lambda / comprehension is attributed to its enclosing def).

Rules (§6.1):
* ``N1_SUFFIX``   ``x.endswith/startswith(c)`` where ``c`` is a ``_``-leading
  string constant, a tuple of them, or a Name bound to a vocabulary constant.
  A bare ``"_"`` / ``"__"`` (private-name tests) is not a suffix.
* ``N2_IN``       ``"_x" in name`` / ``not in`` with a ``_``-leading constant on
  the left and a non-constant on the right.
* ``N3_FSTR_ID``  f-string whose first literal starts ``<ha_domain>.`` and that
  has a formatted value (a built entity id). Excluded: an id whose formatted
  values include the Name ``DOMAIN`` (URA's own ids).
* ``N4_SLUG``     ``.lower().replace(" ", "_")`` (either order) and calls to
  ``slugify`` / ``_slugify`` / ``*.slugify``.
* ``N5_RE_SUFFIX`` ``re.sub/compile/search/match/fullmatch`` with a constant
  pattern holding a ``_\\d`` / ``_(\\d`` / ``_[0-9]`` suffix anchored with ``$``
  (``import re as _re`` aliases followed).
* ``N6_OBJID``    ``x.split(".", 1)[1]`` / ``x.split(".")[1]`` (object-id
  parse) in a function that also does an endswith/startswith/replace call or an
  ``in`` compare (the object id feeds a name test). Index 0 (domain) is fine.
* ``N7_VOCAB``    module-level tuple/list/set/frozenset (or dict values / keys)
  of >= 2 strings all ``_``-leading (a suffix vocabulary), keyed
  ``<module>``; ``N7_VOCAB_USE`` every call (other than the endswith /
  startswith already counted by N1) passing a Name bound to one, including a
  vocabulary imported by name from another scanned module.

Detection limits (stated, not hidden): string building through
``str.format``, ``%``, concatenation with ``+``, ``"".join``, or a dict of
lambdas is not seen; dataflow is not followed (``s = "_x"; eid.endswith(s)``
is missed unless ``s`` is a module vocabulary); vocabulary passed through an
attribute (``mod.SUFFIXES``) or a function default is not resolved across
modules; ``quality/`` and ``scripts/`` are not scanned. The real-tree raw
total therefore is a floor, and the allowlist ratchet is the enforcement.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

URA = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"

RULES = ("N1_SUFFIX", "N2_IN", "N3_FSTR_ID", "N4_SLUG", "N5_RE_SUFFIX",
         "N6_OBJID", "N7_VOCAB", "N7_VOCAB_USE")

HA_DOMAINS = frozenset({
    "alarm_control_panel", "automation", "binary_sensor", "button", "calendar",
    "camera", "climate", "cover", "device_tracker", "event", "fan", "group",
    "humidifier", "image", "input_boolean", "input_button", "input_datetime",
    "input_number", "input_select", "input_text", "lawn_mower", "light", "lock",
    "media_player", "notify", "number", "person", "proximity", "remote", "scene",
    "script", "select", "sensor", "siren", "sun", "switch", "text", "time",
    "todo", "update", "vacuum", "valve", "water_heater", "weather", "zone",
})
_RE_FUNCS = frozenset({"sub", "subn", "compile", "search", "match", "fullmatch"})
_SUFFIX_RE = re.compile(r"_\(?(\\d|\[0-9\])")


@dataclass(frozen=True)
class Hit:
    rule: str
    file: str
    symbol: str
    line: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.rule, self.file, self.symbol)


def _is_suffix_str(v) -> bool:
    return isinstance(v, str) and len(v) > 1 and v.startswith("_") and v.strip("_") != ""


def _str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _vocab_literal(value) -> bool:
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
            and value.func.id in ("frozenset", "set", "tuple") and len(value.args) == 1:
        value = value.args[0]
    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        elts = value.elts
    elif isinstance(value, ast.Dict):
        vals = [_str(v) for v in value.values]
        keys = [_str(k) for k in value.keys if k is not None]
        return (len(vals) >= 2 and all(_is_suffix_str(v) for v in vals)) or \
               (len(keys) >= 2 and all(_is_suffix_str(k) for k in keys))
    else:
        return False
    vals = [_str(e) for e in elts]
    return len(vals) >= 2 and all(_is_suffix_str(v) for v in vals)


def module_vocab(tree: ast.Module) -> dict[str, int]:
    """Module-level names bound to a suffix vocabulary -> line."""
    out: dict[str, int] = {}
    for st in tree.body:
        targets, value = [], None
        if isinstance(st, ast.Assign):
            targets, value = st.targets, st.value
        elif isinstance(st, ast.AnnAssign) and st.value is not None:
            targets, value = [st.target], st.value
        if value is None or not _vocab_literal(value):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = st.lineno
    return out


def _iter_scoped(tree: ast.AST):
    """(node, qualname, func_node) for every node (mirrors the layer engine)."""
    out: list = []

    def rec(node, stack, func):
        out.append((node, ".".join(stack) or "<module>", func))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in node.decorator_list:
                rec(d, stack, func)
            if not isinstance(node, ast.ClassDef):
                rec(node.args, stack, func)
            inner = func if isinstance(node, ast.ClassDef) else node
            for b in node.body:
                rec(b, stack + [node.name], inner)
            return
        for child in ast.iter_child_nodes(node):
            rec(child, stack, func)

    for top in ast.iter_child_nodes(tree):
        rec(top, [], None)
    return out


def _attr_call(node, *names) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
        and node.func.attr in names


def _feeds_name_test(func) -> bool:
    if func is None:
        return False
    for n in ast.walk(func):
        if _attr_call(n, "endswith", "startswith", "replace"):
            return True
        if isinstance(n, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops):
            return True
    return False


def _is_objid_split(node) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    sl = node.slice
    if not (isinstance(sl, ast.Constant) and sl.value in (1, -1)):
        return False
    call = node.value
    return _attr_call(call, "split", "rsplit") and bool(call.args) and _str(call.args[0]) == "."


def scan_module(rel: str, tree: ast.Module, vocab: set[str]) -> list[Hit]:
    hits: list[Hit] = []
    local_vocab = module_vocab(tree)
    for name, line in local_vocab.items():
        hits.append(Hit("N7_VOCAB", rel, "<module>", line))
    seen_split: set[int] = set()
    re_names = {"re"} | {a.asname for st in ast.walk(tree) if isinstance(st, ast.Import)
                         for a in st.names if a.name == "re" and a.asname}
    for node, qual, func in _iter_scoped(tree):
        if isinstance(node, ast.Call):
            f = node.func
            # N1
            if _attr_call(node, "endswith", "startswith") and node.args:
                a = node.args[0]
                s = _str(a)
                if (s is not None and _is_suffix_str(s)) or \
                        (isinstance(a, ast.Tuple) and any(_is_suffix_str(_str(e)) for e in a.elts)) or \
                        (isinstance(a, ast.Name) and a.id in vocab):
                    hits.append(Hit("N1_SUFFIX", rel, qual, node.lineno))
                continue
            # N4
            if _attr_call(node, "replace") and len(node.args) >= 2 \
                    and _str(node.args[0]) == " " and _str(node.args[1]) == "_":
                recv = f.value
                if _attr_call(recv, "lower") or any(
                        _attr_call(n, "lower") for n in ast.walk(recv)):
                    hits.append(Hit("N4_SLUG", rel, qual, node.lineno))
                    continue
            if _attr_call(node, "lower") and _attr_call(f.value, "replace") \
                    and len(f.value.args) >= 2 and _str(f.value.args[0]) == " " \
                    and _str(f.value.args[1]) == "_":
                hits.append(Hit("N4_SLUG", rel, qual, node.lineno))
                continue
            callee = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if callee in ("slugify", "_slugify"):
                hits.append(Hit("N4_SLUG", rel, qual, node.lineno))
                continue
            # N5
            if isinstance(f, ast.Attribute) and f.attr in _RE_FUNCS \
                    and isinstance(f.value, ast.Name) and f.value.id in re_names and node.args:
                pat = _str(node.args[0])
                if pat is not None and pat.endswith("$") and _SUFFIX_RE.search(pat):
                    hits.append(Hit("N5_RE_SUFFIX", rel, qual, node.lineno))
                continue
            # N7 use
            if any(isinstance(a, ast.Name) and a.id in vocab for a in
                   list(node.args) + [k.value for k in node.keywords]):
                hits.append(Hit("N7_VOCAB_USE", rel, qual, node.lineno))
        elif isinstance(node, ast.Compare):
            if any(isinstance(o, (ast.In, ast.NotIn)) for o in node.ops) \
                    and _is_suffix_str(_str(node.left)) \
                    and not isinstance(node.comparators[0], ast.Constant):
                hits.append(Hit("N2_IN", rel, qual, node.lineno))
        elif isinstance(node, ast.JoinedStr):
            first = _str(node.values[0]) if node.values else None
            fvals = [v for v in node.values if isinstance(v, ast.FormattedValue)]
            if first and "." in first and first.split(".", 1)[0] in HA_DOMAINS and fvals:
                if not any(isinstance(n, ast.Name) and n.id == "DOMAIN"
                           for v in fvals for n in ast.walk(v.value)):
                    hits.append(Hit("N3_FSTR_ID", rel, qual, node.lineno))
        elif isinstance(node, ast.Subscript) and id(node) not in seen_split:
            if _is_objid_split(node) and _feeds_name_test(func):
                seen_split.add(id(node))
                hits.append(Hit("N6_OBJID", rel, qual, node.lineno))
    return hits


def load_tree(root: Path = URA) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))}


_PARSE_CACHE: dict[tuple[str, str], ast.Module] = {}
_SCAN_CACHE: dict[tuple[str, str, frozenset], list[Hit]] = {}


def _parse(rel: str, src: str) -> ast.Module:
    key = (rel, src)
    t = _PARSE_CACHE.get(key)
    if t is None:
        t = _PARSE_CACHE[key] = ast.parse(src)
    return t


def scan_tree(sources: dict[str, str]) -> list[Hit]:
    """Scan ``{relpath: source}``; parses and per-module scans are memoised
    on the exact source text, so a drill re-scans only the file it changed."""
    trees = {rel: _parse(rel, src) for rel, src in sources.items()}
    exported: set[str] = set()
    for t in trees.values():
        exported |= set(module_vocab(t))
    hits: list[Hit] = []
    for rel, t in trees.items():
        vocab = set(module_vocab(t))
        for st in ast.walk(t):
            if isinstance(st, ast.ImportFrom):
                for al in st.names:
                    if al.name in exported:
                        vocab.add(al.asname or al.name)
        ck = (rel, sources[rel], frozenset(vocab))
        got = _SCAN_CACHE.get(ck)
        if got is None:
            got = _SCAN_CACHE[ck] = scan_module(rel, t, vocab)
        hits.extend(got)
    return hits


def count_by_key(hits: Iterable[Hit]) -> dict[tuple[str, str, str], int]:
    out: dict[tuple[str, str, str], int] = {}
    for h in hits:
        out[h.key] = out.get(h.key, 0) + 1
    return out


def compare(hits: list[Hit], rows: dict[tuple[str, str, str], dict]) -> list[str]:
    """Ratchet: new key / over max -> fail; stale or under max -> fail (lower it)."""
    counts = count_by_key(hits)
    problems: list[str] = []
    for key, n in sorted(counts.items()):
        row = rows.get(key)
        if row is None:
            problems.append(f"NEW name guess {key} x{n}: resolve via the registry, or allowlist with a reason")
        elif n > row["max_count"]:
            problems.append(f"OVER {key}: {n} > max_count {row['max_count']}")
    for key, row in sorted(rows.items()):
        n = counts.get(key, 0)
        if n == 0:
            problems.append(f"STALE {key}: no longer hits; delete the row")
        elif n < row["max_count"]:
            problems.append(f"LOWER {key}: {n} < max_count {row['max_count']}; ratchet it down")
    return problems

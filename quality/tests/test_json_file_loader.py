"""FACE-ARRIVAL-REBUILD-1 D7: the shared JSON loader only reads, hashes,
parses and validates; it never installs and never falls back."""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

from custom_components.universal_room_automation import json_file_loader as L


class _Hass:
    async def async_add_executor_job(self, fn, *a):
        return fn(*a)


def _run(path, validate):
    return asyncio.run(L.load_validated_json(_Hass(), str(path), parse_validate=validate))


def test_helper_never_installs_or_falls_back(tmp_path):
    calls = []

    def v(spec):
        calls.append(spec)
        if spec.get("bad"):
            raise ValueError("bad spec")
        return spec, ["w1"]

    absent = _run(tmp_path / "none.json", v)
    assert (absent.status, absent.raw_sha256, absent.value) == ("absent", None, None)
    f = tmp_path / "x.json"
    f.write_text('{"bad": 1}')
    rej = _run(f, v)
    assert rej.status == "rejected" and rej.value is None and rej.error == "bad spec"
    assert rej.raw_sha256 == hashlib.sha256(b'{"bad": 1}').hexdigest()
    f.write_text("not json")
    assert _run(f, v).status == "rejected"
    f.write_text('{"ok": 1}')
    ok = _run(f, v)
    assert (ok.status, ok.value, ok.warnings) == ("loaded", {"ok": 1}, ("w1",))
    assert calls == [{"bad": 1}, {"ok": 1}]
    # The module exposes no install / fallback API at all.
    assert not [n for n in dir(L) if "install" in n or "fallback" in n]

#!/usr/bin/env python3
"""Write the ffmpeg v360 reference images for test_interior_dewarp.py.

The source is the deterministic synthetic fisheye in
quality/tests/_iv_dewarp_fixture.py (never family footage). For each view the
filter is the audit's (AUDIT_foyer_dewarp_feasibility_2026_11_16.md):
  v360=input=fisheye:ih_fov=180:iv_fov=180:output=flat:h_fov=110:v_fov=110:yaw=..:pitch=..:roll=..
Needs an ffmpeg with the v360 filter on PATH (generated with Homebrew ffmpeg 9.0.2).

Usage: python3 scripts/probes/make_interior_dewarp_fixture.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "quality" / "tests"))

from PIL import Image  # noqa: E402

import _iv_dewarp_fixture as F  # noqa: E402


def main() -> int:
    F.FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "synthetic_fisheye.png"
        Image.fromarray(F.synthetic_fisheye()).save(src)
        for view in F.VIEWS:
            yaw, pitch, roll = view
            vf = (f"v360=input=fisheye:ih_fov={F.IN_FOV:g}:iv_fov={F.IN_FOV:g}:output=flat:"
                  f"h_fov={F.OUT_FOV:g}:v_fov={F.OUT_FOV:g}:yaw={yaw:g}:pitch={pitch:g}:"
                  f"roll={roll:g}:w={F.OUT_PX}:h={F.OUT_PX}")
            out = F.FIXTURE_DIR / F.ref_name(view)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf,
                            "-frames:v", "1", str(out)], check=True)
            print(out.relative_to(REPO))
        # Review C H6: non-square source, out FOV 90.
        src2 = Path(tmp) / "synthetic_fisheye_nonsq.png"
        Image.fromarray(F.synthetic_fisheye(F.NONSQ_W, F.NONSQ_H)).save(src2)
        for view in F.NONSQ_VIEWS:
            yaw, pitch, roll = view
            vf = (f"v360=input=fisheye:ih_fov={F.IN_FOV:g}:iv_fov={F.IN_FOV:g}:output=flat:"
                  f"h_fov={F.NONSQ_OUT_FOV:g}:v_fov={F.NONSQ_OUT_FOV:g}:yaw={yaw:g}:"
                  f"pitch={pitch:g}:roll={roll:g}:w={F.OUT_PX}:h={F.OUT_PX}")
            out = F.FIXTURE_DIR / F.nonsq_ref_name(view)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src2), "-vf", vf,
                            "-frames:v", "1", str(out)], check=True)
            print(out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())

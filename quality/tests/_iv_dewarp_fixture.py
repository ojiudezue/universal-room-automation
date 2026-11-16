"""Synthetic fisheye fixture for the interior-vision dewarp tests (never
family footage). Shared by ``test_interior_dewarp.py`` and the generator
``scripts/probes/make_interior_dewarp_fixture.py``, which wrote the ffmpeg
v360 reference images under ``fixtures/interior_dewarp/``."""
from __future__ import annotations

from pathlib import Path

import numpy as np

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "interior_dewarp"
SOURCE_PX = 256
OUT_PX = 96
IN_FOV = 180.0
OUT_FOV = 110.0
# (yaw, pitch, roll): straight down the axis, one single-axis turn, and two
# compound turns (the foyer defaults' shape, order ypr).
VIEWS = ((0.0, 0.0, 0.0), (0.0, 30.0, 0.0), (-45.0, 20.0, 40.0), (-13.0, -15.0, -140.0))


def synthetic_fisheye(n: int = SOURCE_PX) -> np.ndarray:
    """A deterministic, asymmetric RGB pattern (sinusoids + quadrant blocks)
    so any wrong rotation sign or order shows up as a large pixel error."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    c = n / 2.0
    r = np.hypot(xx - c, yy - c) / c
    ang = np.arctan2(yy - c, xx - c)
    red = 127 + 120 * np.sin(xx / (n / 57.0)) * np.cos(yy / (n / 22.0))
    green = 127 + 120 * np.sin(ang * 3 + r * 7)
    blue = (np.where(xx < c, 220, 30) * (yy < c) + np.where(xx >= c, 160, 60) * (yy >= c))
    return np.stack([red, green, blue], -1).clip(0, 255).astype(np.uint8)


def ref_name(view) -> str:
    return "ffmpeg_v360_" + "_".join(f"{v:g}" for v in view) + ".png"

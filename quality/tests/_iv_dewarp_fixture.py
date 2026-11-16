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


# Review C H6: a NON-square still (camera stills are not square) and an
# output field of view other than the default, through ffmpeg too.
NONSQ_W, NONSQ_H = 320, 240
NONSQ_OUT_FOV = 90.0
NONSQ_VIEWS = ((-30.0, 20.0, 10.0), (25.0, -15.0, -60.0))


def synthetic_fisheye(n: int = SOURCE_PX, h: int | None = None) -> np.ndarray:
    """A deterministic, asymmetric RGB pattern (sinusoids + quadrant blocks)
    so any wrong rotation sign or order shows up as a large pixel error."""
    w, h = n, (n if h is None else h)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    c, cy = w / 2.0, h / 2.0
    r = np.hypot((xx - c) / c, (yy - cy) / cy)
    ang = np.arctan2(yy - c, xx - c)
    red = 127 + 120 * np.sin(xx / (n / 57.0)) * np.cos(yy / (n / 22.0))
    green = 127 + 120 * np.sin(ang * 3 + r * 7)
    blue = (np.where(xx < c, 220, 30) * (yy < cy) + np.where(xx >= c, 160, 60) * (yy >= cy))
    return np.stack([red, green, blue], -1).clip(0, 255).astype(np.uint8)


def ref_name(view) -> str:
    return "ffmpeg_v360_" + "_".join(f"{v:g}" for v in view) + ".png"


def nonsq_ref_name(view) -> str:
    return "ffmpeg_v360_nonsq_" + "_".join(f"{v:g}" for v in view) + ".png"

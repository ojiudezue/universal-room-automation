"""VISION-INTERIOR-SIGHTINGS-1 ship 2: the per-still fisheye dewarp
(``interior_dewarp.py``; card FOYER-FISHEYE-DEWARP-1).

Oracle: ffmpeg's own ``v360`` filter (an independent implementation), run
offline on a SYNTHETIC fisheye (``_iv_dewarp_fixture``; never family footage)
by ``scripts/probes/make_interior_dewarp_fixture.py``. The module must
reproduce it inside the fisheye circle; outside the circle ffmpeg paints a
fill colour and the module paints black (both are "no picture"), so the
comparison masks those pixels.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import _iv_dewarp_fixture as F

_SRC = (Path(__file__).resolve().parents[2] / "custom_components"
        / "universal_room_automation" / "interior_dewarp.py")


def _module():
    spec = importlib.util.spec_from_file_location("_ura_interior_dewarp_under_test", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dw():
    return _module()


@pytest.mark.parametrize("view", F.VIEWS)
def test_dewarp_matches_ffmpeg_v360(dw, view):
    """Inside the circle every pixel is within a few grey levels of ffmpeg
    v360 (bilinear rounding), for the straight, single-axis and compound
    (order ypr) views. A wrong rotation order measured MAE 19-144 here."""
    src = F.synthetic_fisheye()
    grid = dw.remap_grid(F.SOURCE_PX, F.SOURCE_PX, F.OUT_PX, F.OUT_PX, F.IN_FOV,
                         F.OUT_FOV, F.OUT_FOV, *view)
    mine = dw.dewarp_array(src, grid)
    ref = np.asarray(Image.open(F.FIXTURE_DIR / F.ref_name(view)).convert("RGB"))
    assert mine.shape == ref.shape == (F.OUT_PX, F.OUT_PX, 3)
    vis = grid[2]
    assert vis.mean() > 0.3, "the view must see the fisheye"
    diff = np.abs(ref.astype(int) - mine.astype(int))[vis]
    assert diff.mean() < 2.0, diff.mean()
    assert np.percentile(diff, 99) <= 10, np.percentile(diff, 99)


def test_outside_circle_is_black(dw):
    """A view turned past the lens edge has no picture there: black, never a
    smeared edge pixel."""
    src = F.synthetic_fisheye()
    grid = dw.remap_grid(F.SOURCE_PX, F.SOURCE_PX, 64, 64, 180.0, 110.0, 110.0,
                         90.0, 0.0, 0.0)
    out = dw.dewarp_array(src, grid)
    assert 0.3 < grid[2].mean() < 0.7
    assert out[~grid[2]].max() == 0


def test_dewarp_jpeg_one_flat_view_each(dw):
    """``dewarp_jpeg`` decodes one fisheye JPEG and returns one JPEG per
    view, each ``out_px`` square, and they differ (different views)."""
    buf = io.BytesIO()
    Image.fromarray(F.synthetic_fisheye(512)).save(buf, format="JPEG", quality=92)
    outs = dw.dewarp_jpeg(buf.getvalue(), [(-45, 20, 40), (-13, -15, -140)],
                          in_fov_deg=180.0, out_fov_deg=110.0, out_px=128, quality=90)
    assert len(outs) == 2
    ims = [np.asarray(Image.open(io.BytesIO(b)).convert("RGB")) for b in outs]
    assert [im.shape for im in ims] == [(128, 128, 3), (128, 128, 3)]
    assert np.abs(ims[0].astype(int) - ims[1].astype(int)).mean() > 10


def test_dewarp_jpeg_rejects_garbage(dw):
    """An undecodable still raises, so the caller falls back to the raw
    still and counts it."""
    with pytest.raises(Exception):
        dw.dewarp_jpeg(b"not a jpeg", [(0, 0, 0)], in_fov_deg=180.0, out_fov_deg=110.0,
                       out_px=32, quality=80)

"""Per-still fisheye dewarp for interior vision (VISION-INTERIOR-SIGHTINGS-1
ship 2; card FOYER-FISHEYE-DEWARP-1; audit
``docs/planning/AUDIT_foyer_dewarp_feasibility_2026_11_16.md``).

A 360-lens camera (the Foyer AI Theta) gives a circular fisheye still; the
model counted 0 of 2 people on it in the D0(g) pilot. Before a model call the
still is remapped into flat (rectilinear) views, one per configured view
(yaw / pitch / roll), the same projection as ffmpeg's
``v360=input=fisheye:ih_fov=..:iv_fov=..:output=flat:h_fov=..:v_fov=..``
(equidistant fisheye in, perspective out, bilinear sampling, default
rotation order yaw-pitch-roll). The numbers are checked against ffmpeg's own
v360 in ``quality/tests/test_interior_dewarp.py`` (fixture made offline with
ffmpeg 9.0.2; a synthetic image, never family footage).

Pure numpy + Pillow (both pinned by HA core: ``package_constraints.txt``,
used by the ``stream`` and ``image_upload`` components), imported lazily so
importing this module costs nothing. No subprocess, no ffmpeg in the HA
container needed. CPU work: callers run ``dewarp_jpeg`` in the executor.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Iterable, Sequence


def _rotation_matrix(yaw: float, pitch: float, roll: float) -> Any:
    """ffmpeg v360 rotation (default order ``ypr``): yaw about +y, pitch
    about +x, roll about +z, applied to the output ray before the input
    projection. Returned as a 3x3 numpy array R with ``v_in = R @ v_out``."""
    import numpy as np  # noqa: PLC0415

    y, p, r = (math.radians(float(a)) for a in (yaw, pitch, roll))
    ry = np.array([[math.cos(y), 0.0, math.sin(y)],
                   [0.0, 1.0, 0.0],
                   [-math.sin(y), 0.0, math.cos(y)]])
    rx = np.array([[1.0, 0.0, 0.0],
                   [0.0, math.cos(p), -math.sin(p)],
                   [0.0, math.sin(p), math.cos(p)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0.0],
                   [math.sin(r), math.cos(r), 0.0],
                   [0.0, 0.0, 1.0]])
    return ry @ rx @ rz


@lru_cache(maxsize=16)
def remap_grid(
    in_w: int, in_h: int, out_w: int, out_h: int,
    in_fov_deg: float, out_hfov_deg: float, out_vfov_deg: float,
    yaw: float, pitch: float, roll: float,
) -> tuple[Any, Any, Any]:
    """Source pixel coordinates for every output pixel of one flat view.

    Returns ``(src_x, src_y, visible)`` float32 / bool arrays of shape
    ``(out_h, out_w)``. ``visible`` is False outside the fisheye circle
    (those output pixels are black, as ffmpeg leaves them). Cached per
    geometry (a handful of cameras and views)."""
    import numpy as np  # noqa: PLC0415

    tx = math.tan(math.radians(float(out_hfov_deg)) / 2.0)
    ty = math.tan(math.radians(float(out_vfov_deg)) / 2.0)
    i = (2.0 * np.arange(out_w, dtype=np.float64) + 1.0) / out_w - 1.0
    j = (2.0 * np.arange(out_h, dtype=np.float64) + 1.0) / out_h - 1.0
    lx, ly = np.meshgrid(tx * i, ty * j)
    vec = np.stack([lx, ly, np.ones_like(lx)], axis=-1)
    vec /= np.linalg.norm(vec, axis=-1, keepdims=True)
    vec = vec @ _rotation_matrix(yaw, pitch, roll).T
    x, y, z = vec[..., 0], vec[..., 1], vec[..., 2]
    h = np.hypot(x, y)
    lh = np.where(h > 0.0, h, 1.0)
    theta = np.arctan2(h, z)                      # angle off the lens axis
    r = theta / math.radians(float(in_fov_deg) / 2.0)  # 1.0 = circle edge
    uf = x / lh * r * 0.5
    vf = y / lh * r * 0.5
    visible = (np.abs(uf) < 0.5) & (np.abs(vf) < 0.5) & (r <= 1.0)
    src_x = ((uf + 0.5) * in_w - 0.5).astype(np.float32)
    src_y = ((vf + 0.5) * in_h - 0.5).astype(np.float32)
    return src_x, src_y, visible


def dewarp_array(img: Any, grid: tuple[Any, Any, Any]) -> Any:
    """Bilinear sample ``img`` (H x W x C uint8) at ``grid``; pixels outside
    the fisheye circle are 0 (black)."""
    import numpy as np  # noqa: PLC0415

    src_x, src_y, visible = grid
    h, w = img.shape[:2]
    x0 = np.floor(src_x).astype(np.int64)
    y0 = np.floor(src_y).astype(np.int64)
    fx = (src_x - x0)[..., None]
    fy = (src_y - y0)[..., None]
    x0c, x1c = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1)
    y0c, y1c = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    src = img.astype(np.float32)
    top = src[y0c, x0c] * (1.0 - fx) + src[y0c, x1c] * fx
    bot = src[y1c, x0c] * (1.0 - fx) + src[y1c, x1c] * fx
    out = top * (1.0 - fy) + bot * fy
    out[~visible] = 0.0
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def dewarp_jpeg(
    jpeg: bytes, views: Iterable[Sequence[float]], *,
    in_fov_deg: float, out_fov_deg: float, out_px: int, quality: int,
) -> list[bytes]:
    """Decode one fisheye still, return one JPEG per view (``(yaw, pitch,
    roll)`` degrees). Raises on an undecodable image (the caller counts it
    and falls back to the raw still)."""
    import io  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    with Image.open(io.BytesIO(jpeg)) as im:
        arr = np.asarray(im.convert("RGB"))
    in_h, in_w = arr.shape[:2]
    out: list[bytes] = []
    for view in views:
        yaw, pitch, roll = (float(v) for v in view)
        grid = remap_grid(in_w, in_h, int(out_px), int(out_px), float(in_fov_deg),
                          float(out_fov_deg), float(out_fov_deg), yaw, pitch, roll)
        flat = dewarp_array(arr, grid)
        buf = io.BytesIO()
        Image.fromarray(flat, "RGB").save(buf, format="JPEG", quality=int(quality))
        out.append(buf.getvalue())
    return out

"""
exports.py
----------
GeoTIFF export of the mapped data.

The GeoTIFF holds the data values themselves (in real units, or class codes
for categorical maps) in the map's projection - what a GIS needs - not the
coloured picture.

Earth Engine limits a direct download to about 48 MB, so the pixel size is
chosen to fit: the dataset's native resolution when the region is small
enough, otherwise the finest size that fits.

Public API:
  geotiff_download(...) -> dict with the download URL and the pixel size used
  fetch_geotiff(url)    -> bytes
"""

from __future__ import annotations

import math

import ee
import requests

# Uncompressed size budget for one download, kept under Earth Engine's limit.
_MAX_BYTES = 32 * 1024 * 1024
_BYTES_PER_VALUE = 4          # data is exported as 32-bit


def _nice_scale(scale_m: float) -> float:
    """Round a pixel size up to a tidy value (10, 20, 25, 30, 50, 100, ...)."""
    if scale_m <= 0:
        return 10.0
    magnitude = 10 ** math.floor(math.log10(scale_m))
    for step in (1, 2, 2.5, 3, 5, 10):
        if step * magnitude >= scale_m - 1e-9:
            return float(step * magnitude)
    return float(10 * magnitude)


def geotiff_download(img: ee.Image, extent, projection: dict, n_bands: int,
                     native_scale_m: float | None, lat_mid: float = 0.0) -> dict | None:
    """
    Prepare a GeoTIFF download of `img` over the map extent.

    extent:      [xmin, xmax, ymin, ymax] in the map projection
    projection:  dict from projection.choose_map_projection()
    Returns {"url", "scale_m", "native_scale_m", "resampled"} or None on failure.
    """
    xmin, xmax, ymin, ymax = extent
    if projection["metric"]:
        width_m, height_m = xmax - xmin, ymax - ymin
    else:
        width_m = (xmax - xmin) * 111_320 * max(math.cos(math.radians(lat_mid)), 0.01)
        height_m = (ymax - ymin) * 110_540

    max_pixels = _MAX_BYTES / (_BYTES_PER_VALUE * max(n_bands, 1))
    fit_scale = math.sqrt(width_m * height_m / max_pixels)
    native = float(native_scale_m) if native_scale_m else 30.0
    scale = native if fit_scale <= native else _nice_scale(fit_scale)

    try:
        region = ee.Geometry.Rectangle([xmin, ymin, xmax, ymax], projection["crs"], False)
        url = img.getDownloadURL({
            "region": region, "crs": projection["crs"], "scale": scale, "format": "GEO_TIFF",
        })
    except Exception as e:
        print(f"GeoTIFF export could not be prepared: {e}")
        return None
    return {"url": url, "scale_m": scale, "native_scale_m": native, "resampled": scale > native}


def fetch_geotiff(url: str) -> bytes:
    """Download a prepared GeoTIFF. Raises RuntimeError with Earth Engine's message on failure."""
    resp = requests.get(url, timeout=300)
    if resp.status_code != 200:
        raise RuntimeError(f"Earth Engine returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.content

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

One request for a whole country often runs past Earth Engine's time limit
(composites computed on the fly are the slow case), so the data is requested
as a grid of tiles on one exact pixel grid, downloaded in parallel and
written into a single GeoTIFF here. Earth Engine's own geo keys for the
projection are copied into the file, so EPSG codes and custom projections
are described exactly as Earth Engine understands them.

Public API:
  geotiff_download(...)  -> dict with the tile download URLs and the pixel size used
  fetch_geotiff(geotiff) -> bytes
"""

from __future__ import annotations

import io
import math
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

import ee
import numpy as np
import requests
from PIL import Image

# Uncompressed size budget for one download, kept under Earth Engine's limit.
_MAX_BYTES = 32 * 1024 * 1024
_BYTES_PER_VALUE = 4          # data is exported as 32-bit

_TILE_VALUES = 1024 * 1024    # values (pixels x bands) in one tile request
_MAX_PARALLEL = 8             # simultaneous tile downloads
_TILE_TIMEOUT = 240           # seconds for one tile
_METRES_PER_DEGREE = 111_320  # pixel size in degrees for the geographic projection

# GeoTIFF tags copied from Earth Engine's file: the projection's geo keys.
_GEO_KEY_TAGS = (34735, 34736, 34737)


def _nice_scale(scale_m: float) -> float:
    """Round a pixel size up to a tidy value (10, 20, 25, 30, 50, 100, ...)."""
    if scale_m <= 0:
        return 10.0
    magnitude = 10 ** math.floor(math.log10(scale_m))
    for step in (1, 2, 2.5, 3, 5, 10):
        if step * magnitude >= scale_m - 1e-9:
            return float(step * magnitude)
    return float(10 * magnitude)


def _spans(length: int, tile: int) -> list[tuple[int, int]]:
    """Split `length` pixels into near-equal (start, size) runs of at most `tile`."""
    count = max(math.ceil(length / tile), 1)
    edges = [round(length * i / count) for i in range(count + 1)]
    return [(edges[i], edges[i + 1] - edges[i]) for i in range(count)]


def array_tiles(img: ee.Image, crs: str, origin, pixel, width: int, height: int, n_bands: int,
                tile_values: int | None = None) -> list[tuple]:
    """
    NPY download URLs covering a width x height pixel grid of `img`, as
    [(x px, y px, width px, height px, url), ...].

    origin: (x, y) of the grid's top-left corner in `crs`
    pixel:  (pixel width, pixel height) in `crs` units
    URLs are created one at a time (the Earth Engine client is not
    thread-safe); fetch_array() downloads them in parallel.
    """
    tile_px = max(int(math.sqrt((tile_values or _TILE_VALUES) / max(n_bands, 1))), 64)
    (x_origin, y_origin), (px_w, px_h) = origin, pixel
    tiles = []
    for y0, h in _spans(height, tile_px):
        for x0, w in _spans(width, tile_px):
            url = img.getDownloadURL({
                "crs": crs, "format": "NPY", "dimensions": f"{w}x{h}",
                "crs_transform": [px_w, 0, x_origin + x0 * px_w, 0, -px_h, y_origin - y0 * px_h],
            })
            tiles.append((x0, y0, w, h, url))
    return tiles


def fetch_array(tiles: list[tuple], width: int, height: int) -> tuple[np.ndarray, list[str]]:
    """
    Download the tiles from array_tiles() and join them: (bands x rows x
    columns array, band names). Masked pixels are -inf for floating-point
    data and 0 for integers. Raises RuntimeError with Earth Engine's message.
    """
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        parts = list(pool.map(lambda tile: _get(tile[4]), tiles))
    data, names = None, None
    for (x0, y0, w, h, _), raw in zip(tiles, parts):
        part = np.load(io.BytesIO(raw), allow_pickle=False)
        if data is None:
            names = list(part.dtype.names)
            dtype = np.result_type(*[part.dtype[n] for n in names])
            data = np.zeros((len(names), height, width), dtype=dtype)
        for b, name in enumerate(names):
            data[b, y0:y0 + h, x0:x0 + w] = part[name][:h, :w]
    return data, names


def geotiff_download(img: ee.Image, extent, projection: dict, n_bands: int,
                     native_scale_m: float | None, lat_mid: float = 0.0) -> dict | None:
    """
    Prepare a GeoTIFF download of `img` over the map extent.

    extent:      [xmin, xmax, ymin, ymax] in the map projection
    projection:  dict from projection.choose_map_projection()
    Returns {"tiles", "keys_url", "width", "height", "origin", "pixel",
    "scale_m", "native_scale_m", "resampled"} or None on failure.
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

    # One pixel grid for the whole file: every tile is a window of it.
    pixel = scale if projection["metric"] else scale / _METRES_PER_DEGREE
    width = max(math.ceil((xmax - xmin) / pixel - 1e-6), 1)
    height = max(math.ceil((ymax - ymin) / pixel - 1e-6), 1)
    crs = projection["crs"]

    try:
        tiles = array_tiles(img, crs, (xmin, ymax), (pixel, pixel), width, height, n_bands)
        # A one-pixel GeoTIFF in the same projection, for its geo keys.
        keys_url = ee.Image.constant(0).toFloat().getDownloadURL({
            "crs": crs, "format": "GEO_TIFF", "dimensions": "1x1",
            "crs_transform": [pixel, 0, xmin, 0, -pixel, ymax],
        })
    except Exception as e:
        print(f"GeoTIFF export could not be prepared: {e}")
        return None
    return {"tiles": tiles, "keys_url": keys_url, "width": width, "height": height,
            "origin": (xmin, ymax), "pixel": pixel,
            "scale_m": scale, "native_scale_m": native, "resampled": scale > native}


def _get(url: str, attempts: int = 2) -> bytes:
    """Download one URL, retrying once. Raises RuntimeError with Earth Engine's message."""
    last = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, timeout=_TILE_TIMEOUT)
            if resp.status_code == 200:
                return resp.content
            last = f"Earth Engine returned HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code == 400 and not any(k in resp.text.lower() for k in ("memory", "timed out", "deadline")):
                break           # a bad request fails the same way every time
        except requests.exceptions.Timeout:
            last = "Earth Engine took too long to compute part of the region"
        except Exception as e:
            last = str(e)
        time.sleep(1 + attempt)
    raise RuntimeError(last or "download failed")


def fetch_geotiff(geotiff: dict) -> bytes:
    """
    Download a prepared GeoTIFF (the dict from geotiff_download) and return
    the file. Raises RuntimeError with Earth Engine's message on failure.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        keys_job = pool.submit(_get, geotiff["keys_url"])
        data, names = fetch_array(geotiff["tiles"], geotiff["width"], geotiff["height"])
        keys_tif = keys_job.result()

    tags = Image.open(io.BytesIO(keys_tif)).tag_v2
    geo_keys = {tag: tags[tag] for tag in _GEO_KEY_TAGS if tag in tags}
    # Masked pixels come out as -inf for floating-point data and 0 for
    # integers - the same no-data values Earth Engine's own GeoTIFF declares.
    nodata = "-Infinity" if data.dtype.kind == "f" else "0"
    return _write_geotiff(data, names, geotiff["origin"], geotiff["pixel"], geo_keys, nodata)


# ---------------------- GeoTIFF writer ----------------------

_SHORT, _LONG, _DOUBLE, _ASCII = 3, 4, 12, 2
_TYPE_FORMAT = {_SHORT: "H", _LONG: "I", _DOUBLE: "d"}
_SAMPLE_FORMAT = {"u": 1, "i": 2, "f": 3}


def _write_geotiff(data: np.ndarray, names: list[str], origin, pixel: float,
                   geo_keys: dict, nodata: str) -> bytes:
    """
    Write bands x rows x columns as a little-endian, deflate-compressed
    GeoTIFF: one plane per band, the pixel grid given by its top-left corner
    `origin` and square pixel size `pixel`, the projection by `geo_keys`
    (GeoKeyDirectory, GeoDoubleParams, GeoAsciiParams tags).
    """
    n_bands, height, width = data.shape
    data = data.astype(data.dtype.newbyteorder("<"), copy=False)
    rows_per_strip = max(1, min(height, (1 << 20) // max(width * data.dtype.itemsize, 1)))

    out = io.BytesIO()
    out.write(b"II*\x00\x00\x00\x00\x00")       # header; IFD offset patched below
    offsets, counts = [], []
    for band in data:                            # band-major strips (planar configuration 2)
        for top in range(0, height, rows_per_strip):
            block = zlib.compress(np.ascontiguousarray(band[top:top + rows_per_strip]).tobytes(), 6)
            offsets.append(out.tell())
            counts.append(len(block))
            out.write(block)
            if out.tell() % 2:
                out.write(b"\x00")

    sample_format = _SAMPLE_FORMAT[data.dtype.kind]
    metadata = "<GDALMetadata>" + "".join(
        f'<Item name="DESCRIPTION" sample="{i}" role="description">{escape(str(name))}</Item>'
        for i, name in enumerate(names)) + "</GDALMetadata>"
    entries = {
        256: (_LONG, [width]),
        257: (_LONG, [height]),
        258: (_SHORT, [data.dtype.itemsize * 8] * n_bands),
        259: (_SHORT, [8]),                      # deflate
        262: (_SHORT, [1]),                      # black is zero
        273: (_LONG, offsets),
        277: (_SHORT, [n_bands]),
        278: (_LONG, [rows_per_strip]),
        279: (_LONG, counts),
        284: (_SHORT, [2 if n_bands > 1 else 1]),
        339: (_SHORT, [sample_format] * n_bands),
        33550: (_DOUBLE, [pixel, pixel, 0.0]),   # ModelPixelScale
        33922: (_DOUBLE, [0.0, 0.0, 0.0, float(origin[0]), float(origin[1]), 0.0]),   # ModelTiepoint
        42112: (_ASCII, metadata),
        42113: (_ASCII, nodata),
    }
    if n_bands > 1:
        entries[338] = (_SHORT, [0] * (n_bands - 1))    # extra samples: unspecified
    for tag, value in geo_keys.items():
        if tag == 34737:
            entries[tag] = (_ASCII, str(value))
        else:
            entries[tag] = (_SHORT if tag == 34735 else _DOUBLE,
                            [value] if isinstance(value, (int, float)) else list(value))

    # Values longer than 4 bytes go after the strips; the IFD comes last.
    ifd = []
    for tag in sorted(entries):
        kind, value = entries[tag]
        if kind == _ASCII:
            raw = value.encode("ascii", "replace") + b"\x00"
            count = len(raw)
        else:
            raw = struct.pack(f"<{len(value)}{_TYPE_FORMAT[kind]}", *value)
            count = len(value)
        if len(raw) <= 4:
            ifd.append(struct.pack("<HHI", tag, kind, count) + raw.ljust(4, b"\x00"))
        else:
            where = out.tell()
            out.write(raw)
            if out.tell() % 2:
                out.write(b"\x00")
            ifd.append(struct.pack("<HHII", tag, kind, count, where))

    ifd_offset = out.tell()
    out.write(struct.pack("<H", len(ifd)) + b"".join(ifd) + struct.pack("<I", 0))
    out.seek(4)
    out.write(struct.pack("<I", ifd_offset))
    return out.getvalue()

"""
thumbnail.py
------------
Fetches the rendered map image from Earth Engine, in the map's projection,
at print resolution.

A single large image request is slow (Earth Engine computes it in one go and
often times out), so the map is requested as a grid of tiles downloaded in
parallel and stitched together. If tiles fail, the whole map is requested
as one smaller image instead.
"""

import io
import math
import time
from concurrent.futures import ThreadPoolExecutor

import ee
import requests
from PIL import Image

TARGET_LONG_SIDE = 2048     # px; fills the map frame of the exported figure at close to 300 dpi
TILE_SIZE        = 512      # px; longest side of one tile
MAX_PARALLEL     = 8        # simultaneous tile downloads
FALLBACK_SIZES   = [1024, 512]   # single-image sizes tried if the tiled fetch fails


def _thumb_url(vis_img, vis_params, bounds, crs, width, height):
    xmin, ymin, xmax, ymax = bounds
    region = ee.Geometry.Rectangle([xmin, ymin, xmax, ymax], crs, False)
    return vis_img.getThumbURL({**vis_params, "region": region, "crs": crs,
                                "dimensions": f"{width}x{height}", "format": "png"})


def _download(url, timeout, attempts=2):
    last = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                return Image.open(io.BytesIO(resp.content)).convert("RGBA")
            last = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code == 400:
                break           # a bad request fails the same way every time
        except requests.exceptions.Timeout:
            last = "timed out"
        except Exception as e:
            last = str(e)
        time.sleep(1 + attempt)
    raise RuntimeError(last or "download failed")


def _tile_jobs(vis_img, vis_params, extent, crs, width, height):
    """Tiles covering the image: [(x px, y px, width px, height px, url), ...]."""
    xmin, xmax, ymin, ymax = extent
    n_cols = max(math.ceil(width / TILE_SIZE), 1)
    n_rows = max(math.ceil(height / TILE_SIZE), 1)
    # Pixel edges of each column/row; map edges follow from the same fractions,
    # so neighbouring tiles share an exact boundary and pixels stay square.
    col_px = [round(width * i / n_cols) for i in range(n_cols + 1)]
    row_px = [round(height * j / n_rows) for j in range(n_rows + 1)]

    jobs = []
    for j in range(n_rows):
        for i in range(n_cols):
            x0 = xmin + (xmax - xmin) * col_px[i] / width
            x1 = xmin + (xmax - xmin) * col_px[i + 1] / width
            y1 = ymax - (ymax - ymin) * row_px[j] / height          # top edge
            y0 = ymax - (ymax - ymin) * row_px[j + 1] / height      # bottom edge
            w, h = col_px[i + 1] - col_px[i], row_px[j + 1] - row_px[j]
            # URLs are created one at a time (the Earth Engine client is not
            # thread-safe); only the downloads run in parallel.
            url = _thumb_url(vis_img, vis_params, (x0, y0, x1, y1), crs, w, h)
            jobs.append((col_px[i], row_px[j], w, h, url))
    return jobs


def _stitch(jobs, tiles, width, height):
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for (px, py, w, h, _), tile in zip(jobs, tiles):
        if tile.size != (w, h):
            tile = tile.resize((w, h), Image.NEAREST)
        canvas.paste(tile, (px, py))
    return canvas


def _fetch_tiled(vis_img, vis_params, extent, crs, width, height):
    jobs = _tile_jobs(vis_img, vis_params, extent, crs, width, height)
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        tiles = list(pool.map(lambda job: _download(job[4], timeout=120, attempts=1), jobs))
    return _stitch(jobs, tiles, width, height)


def _dimensions(extent, long_side):
    """Pixel width and height for `extent` with square pixels and the given longest side."""
    xmin, xmax, ymin, ymax = extent
    aspect = (xmax - xmin) / max(ymax - ymin, 1e-9)
    if aspect >= 1:
        return long_side, max(int(round(long_side / aspect)), 1)
    return max(int(round(long_side * aspect)), 1), long_side


def fetch_thumbnail_with_retry(vis_img, vis_params, extent, crs, target_long_side=TARGET_LONG_SIDE):
    """
    Render `vis_img` over `extent` and download it as an image.

    extent: [xmin, xmax, ymin, ymax] in the coordinates of `crs`
    crs:    CRS string Earth Engine accepts (EPSG code or WKT)

    The returned image covers exactly `extent`, with square pixels, so it can
    be drawn on a map with that same extent and projection.
    target_long_side: longest side in pixels to aim for; pass a smaller value
    for very heavy computations (composites of many hundreds of images).
    Returns (PIL image, longest side in pixels).
    """
    xmin, xmax, ymin, ymax = extent

    def _size(long_side):
        return _dimensions(extent, long_side)

    errors = []
    try:
        width, height = _size(target_long_side)
        return _fetch_tiled(vis_img, vis_params, extent, crs, width, height), target_long_side
    except Exception as e:
        errors.append(f"{target_long_side}px tiled: {e}")
        # A request Earth Engine rejects outright (unknown band, incompatible
        # images) will be rejected at any size - report it now.
        if "HTTP 400" in str(e) and not any(k in str(e).lower() for k in ("too large", "memory", "timed out")):
            raise RuntimeError(f"Earth Engine could not render the map ({e}).")

    for dim in [s for s in FALLBACK_SIZES if s < target_long_side]:
        try:
            width, height = _size(dim)
            url = _thumb_url(vis_img, vis_params, (xmin, ymin, xmax, ymax), crs, width, height)
            return _download(url, timeout=180), dim
        except Exception as e:
            errors.append(f"{dim}px: {e}")
    raise RuntimeError("Earth Engine could not render the map (" + "; ".join(errors)[:600] + ").")


def fetch_panel_thumbnails(vis_imgs, vis_params, extent, crs, long_side, on_panel=None):
    """
    Render several images over the same extent, with the same visualisation -
    the maps of one multi-map figure.

    The tiles of all the maps are downloaded together, so a figure of twelve
    maps takes little longer than one. A map whose tiles fail is requested
    again on its own, at a smaller size if need be.
    on_panel(done, total): called as each map is finished, for progress.
    Returns a list of PIL images, one per input image, each covering `extent`.
    """
    width, height = _dimensions(extent, long_side)
    # URLs are created one at a time (the Earth Engine client is not thread-safe).
    jobs_per_map = [_tile_jobs(img, vis_params, extent, crs, width, height) for img in vis_imgs]

    def _try(job):
        try:
            return _download(job[4], timeout=150, attempts=2)
        except Exception as e:
            return e

    images = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        pending = [[pool.submit(_try, job) for job in jobs] for jobs in jobs_per_map]
        for index, (jobs, futures) in enumerate(zip(jobs_per_map, pending)):
            tiles = [f.result() for f in futures]
            if any(isinstance(t, Exception) for t in tiles):
                image, _dim = fetch_thumbnail_with_retry(vis_imgs[index], vis_params, extent, crs,
                                                         target_long_side=long_side)
            else:
                image = _stitch(jobs, tiles, width, height)
            images.append(image)
            if on_panel:
                on_panel(index + 1, len(vis_imgs))
    return images

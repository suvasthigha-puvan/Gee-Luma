"""
restyle.py
----------
Changing the colour ramp and the legend's range of a finished map without
asking Earth Engine to render it again.

When a continuous map is finished, the values behind its picture are
prepared for download on exactly the picture's pixel grid
(prepare_restyle) and fetched once (fetch_values). A new style is then
applied here: the values are coloured the way Earth Engine colours them -
the palette spread evenly between the legend's minimum and maximum, values
outside the range given the end colours, masked pixels transparent - and the
layout is drawn again. That takes seconds, whatever the dataset.

Public API:
  prepare_restyle(...)                    -> dict | None
  fetch_values(job)                       -> None (keeps the values in the job)
  restyle_map(job, palette, vmin, vmax)   -> {"png": bytes, "pdf": bytes}
"""

from __future__ import annotations

import re
import threading

import ee
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image

from gee_luma.cartography import render_cartographic_figure, render_composite_figure
from gee_luma.exports import array_tiles, fetch_array

# Values per download tile: about the size of one tile of the rendered picture.
_TILE_VALUES = 512 * 512


def prepare_restyle(images: list, band: str, extent, crs: str, size: tuple[int, int],
                    render_kwargs: dict, panels: list[dict] | None = None,
                    layout: dict | None = None) -> dict | None:
    """
    Everything needed to restyle a finished continuous map later.

    images:  the map's image(s) - one, or one per map of a multi-map figure
    band:    the band the map shows
    extent:  [xmin, xmax, ymin, ymax] the pictures cover, in `crs`
    size:    (width, height) of the rendered picture(s) in pixels
    render_kwargs: the arguments the figure was drawn with
    panels / layout: for a multi-map figure, [{"label", "note"}] and the grid
    Returns None if the downloads could not be prepared.
    """
    xmin, xmax, ymin, ymax = extent
    width, height = size
    try:
        stack = ee.Image.cat([image.select([band]).toFloat().rename([f"map{i}"])
                              for i, image in enumerate(images)])
        tiles = array_tiles(stack, crs, (xmin, ymax), ((xmax - xmin) / width, (ymax - ymin) / height),
                            width, height, n_bands=len(images), tile_values=_TILE_VALUES)
    except Exception as e:
        print(f"Restyling could not be prepared: {e}")
        return None
    return {
        "tiles": tiles, "width": width, "height": height,
        "render_kwargs": render_kwargs, "panels": panels, "layout": layout,
        "values": None, "lock": threading.Lock(),
    }


def fetch_values(job: dict) -> None:
    """Download the map's values once; later calls return at once. Raises RuntimeError on failure."""
    with job["lock"]:
        if job["values"] is None:
            data, _names = fetch_array(job["tiles"], job["width"], job["height"])
            job["values"] = data.astype(np.float32, copy=False)


def _color(value: str) -> str:
    """Earth Engine palettes may omit the '#' of hex colours."""
    text = str(value).strip()
    return "#" + text if re.fullmatch(r"[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3}", text) else text


def colorize(values: np.ndarray, palette: list[str], vmin: float, vmax: float) -> Image.Image:
    """One map's values as an RGBA picture, coloured as Earth Engine colours a palette."""
    cmap = LinearSegmentedColormap.from_list("ramp", [_color(c) for c in palette], N=1024)
    valid = np.isfinite(values)
    scaled = np.zeros(values.shape, dtype=np.float32)
    scaled[valid] = np.clip((values[valid] - vmin) / (vmax - vmin), 0.0, 1.0)
    rgba = cmap(scaled, bytes=True)
    rgba[~valid, 3] = 0
    return Image.fromarray(rgba, mode="RGBA")


def restyle_map(job: dict, palette: list[str], vmin: float, vmax: float) -> dict:
    """
    Draw the map again with another colour ramp and legend range.
    Returns {"png": bytes, "pdf": bytes}; raises RuntimeError if the values
    could not be downloaded.
    """
    fetch_values(job)
    kwargs = dict(job["render_kwargs"])
    kwargs["vis_params_gee"] = {**kwargs["vis_params_gee"], "palette": list(palette),
                                "min": float(vmin), "max": float(vmax)}
    pictures = [colorize(values, palette, vmin, vmax) for values in job["values"]]
    if job["panels"]:
        return render_composite_figure(
            panels=[{**panel, "image": picture} for panel, picture in zip(job["panels"], pictures)],
            layout=job["layout"], **kwargs)
    return render_cartographic_figure(map_pil_image=pictures[0], **kwargs)

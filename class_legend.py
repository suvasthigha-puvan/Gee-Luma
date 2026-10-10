"""
class_legend.py
---------------
Class legends for classified (categorical) bands of any dataset.

Earth Engine datasets publish their classes in different ways, and many do
not publish them at all. This module gives every case a swatch legend:

  1. The catalog lists the classes with names and colours (gee:classes)
       -> used as published.
  2. The catalog lists classes without colours
       -> published names, distinct colours assigned here.
  3. The classes are only written out in the band description
     ("0 = cloud/shadow, 1 = clear", "* 2 - Tidal Flat * 3 - Mangrove")
       -> names parsed from the text, distinct colours assigned here.
  4. Nothing is published, but the band holds a handful of whole-number
     values (masks, flags, community classifications)
       -> detected from the data, classes labelled by their value.

Public API:
  parse_classes_from_text(description)        -> [{value, label}]
  distinct_colors(n)                          -> [hex]
  complete_class_colors(classes)              -> classes, every one with a colour
  is_class_candidate(band_meta, band_type)    -> worth checking the data?
  distinct_values(img, band, region, scale)   -> sorted values, or None if not class-like
  schema_from_values(values, named_classes)   -> {value: {label, color}}
  shorten_legend(legend, max_rows)            -> legend that fits the map panel
"""

from __future__ import annotations

import colorsys
import re

import ee

# A band with more distinct values than this is treated as a measurement,
# not a classification, when the dataset publishes no class list.
MAX_DETECTED_CLASSES = 16

# Most legend rows that stay readable in the map's side panel.
MAX_LEGEND_ROWS = 18

NEUTRAL_COLOR = "#D4D4D8"      # value 0 of an unnamed band: usually "none" / "other"

# Colour-blind-friendly qualitative colours (Okabe-Ito, then Tableau).
_QUALITATIVE = [
    "#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442",
    "#7F3C8D", "#11A579", "#E73F74", "#80BA5A", "#A5AA99", "#3969AC", "#F2B701",
    "#008695", "#CF1C90",
]

_CLASS_HINT = re.compile(
    r"class|categor|land ?cover|land ?use|lulc|\btype\b|label|mask|flag|zone|strat|biome|ecoregion",
    re.IGNORECASE)

# "0 = cloud", "1: Land", "* 2 - Tidal Flat", "(0=no clouds, 1=clouds)"
_TEXT_CLASS = re.compile(
    r"(?<![\w.])(\d{1,4})\s*(?:=|:|\s-\s|\s–\s)\s*([A-Za-z][^,;.\n|*()=:]{1,48})")


def parse_classes_from_text(description: str) -> list[dict]:
    """
    Classes written out in a band description, as [{value, label}].
    Returns [] unless at least two distinct values are described.
    """
    found: dict[int, str] = {}
    for value, label in _TEXT_CLASS.findall(str(description or "")):
        label = re.sub(r"\s+", " ", label).strip(" -")
        label = re.split(r"\s+(?:and|or)\s+\d", label)[0]        # "0: water and 1: land"
        if label and int(value) not in found:
            found[int(value)] = label[0].upper() + label[1:]
    if len(found) < 2:
        return []
    return [{"value": v, "label": found[v]} for v in sorted(found)]


def distinct_colors(n: int) -> list[str]:
    """n clearly different colours: a curated set first, then evenly spread hues."""
    colors = list(_QUALITATIVE[:n])
    hue = 0.11
    while len(colors) < n:
        hue = (hue + 0.618033988749895) % 1.0
        level = len(colors) % 3
        r, g, b = colorsys.hsv_to_rgb(hue, (0.75, 0.55, 0.85)[level], (0.85, 0.70, 0.60)[level])
        colors.append("#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255)))
    return colors


def complete_class_colors(classes: list[dict]) -> list[dict]:
    """
    Give a colour to every class that has none. Published colours are kept;
    if the dataset publishes no usable colours at all, every class gets a
    distinct one (value 0 a neutral grey).
    """
    def usable(c):
        return bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", str(c.get("color") or "")))

    missing = [c for c in classes if not usable(c)]
    if not missing:
        return classes
    palette = iter(distinct_colors(len(missing)))
    completed = []
    for c in classes:
        if usable(c):
            completed.append(c)
        elif c.get("value") == 0:
            completed.append({**c, "color": NEUTRAL_COLOR})
        else:
            completed.append({**c, "color": next(palette)})
    return completed


def is_class_candidate(band_meta: dict | None, band_type: dict | None, band_name: str = "") -> bool:
    """
    Could this band be a classification although the catalog lists no classes?
    Only whole-number bands without units or a scale factor qualify, and then
    only if the name or description suggests classes or the value range is a
    single byte. The data itself decides afterwards (see distinct_values).
    """
    band_meta = band_meta or {}
    if band_meta.get("is_bitmask") or band_meta.get("units"):
        return False
    if band_meta.get("scale") not in (None, 1, 1.0) or band_meta.get("offset") not in (None, 0, 0.0):
        return False
    if band_type and band_type.get("precision") not in (None, "int"):
        return False
    if band_meta.get("text_classes"):
        return True
    if _CLASS_HINT.search(f"{band_name} {band_meta.get('description', '')}"):
        return True
    if band_type and band_type.get("min") is not None and band_type.get("max") is not None:
        return (band_type["max"] - band_type["min"]) <= 255
    return False


def distinct_values(img: "ee.Image", band: str, region_geom, scale: float,
                    max_classes: int = MAX_DETECTED_CLASSES) -> list[int] | None:
    """
    The distinct values of `band` over the region, if they look like classes:
    whole numbers, and no more than `max_classes` of them.
    Returns None for measurements (many values, or fractional ones) and on failure.
    """
    # Random points read at the dataset's own pixel size. A histogram of the
    # whole region would be read from Earth Engine's reduced-resolution
    # copies, which for many datasets are averages: a 0/100 mask would then
    # appear to hold every value in between.
    try:
        hist = img.select([band]).sample(
            region=region_geom, scale=float(scale or 30), numPixels=20000,
            seed=7, dropNulls=True, geometries=False,
        ).aggregate_histogram(band).getInfo() or {}
    except Exception:
        return None
    values = []
    for key in hist:
        number = float(key)
        if number != int(number):
            return None
        values.append(int(number))
    if not values or len(values) > max_classes:
        return None
    return sorted(values)


def snap_to_values(img: "ee.Image", values: list[int]) -> "ee.Image":
    """
    Move every pixel to the nearest of `values` (sorted). When a class band
    is drawn zoomed out, Earth Engine may hand back averaged pixels (37 in a
    0/100 mask); snapping turns them back into one of the real classes.
    """
    snapped = ee.Image.constant(values[0])
    for lower, upper in zip(values, values[1:]):
        snapped = snapped.add(img.gt((lower + upper) / 2.0).multiply(upper - lower))
    return snapped.updateMask(img.mask()).toInt().rename(img.bandNames())


def schema_from_values(values: list[int], named_classes: list[dict] | None = None) -> dict:
    """
    Class schema {value: {label, color}} for a band the catalog gives no
    colours for. Names come from `named_classes` (parsed from the band
    description) where a value has one; other values are labelled by number.
    """
    names = {int(c["value"]): c["label"] for c in (named_classes or [])}
    classes = [{"value": v, "label": names.get(v, f"Class {v}")} for v in values]
    return {c["value"]: {"label": c["label"], "color": c["color"]}
            for c in complete_class_colors(classes)}


def shorten_legend(legend: list[dict], shares: dict | None = None,
                   max_rows: int = MAX_LEGEND_ROWS) -> list[dict]:
    """
    Legend that fits the side panel. When a region has more classes than fit,
    the largest ones (by `shares`, {label: percent}) are listed in the
    dataset's order and the rest are summed up in one closing line.
    """
    if len(legend) <= max_rows:
        return legend
    keep = max_rows - 1
    if shares:
        ranked = sorted(range(len(legend)), key=lambda i: shares.get(legend[i].get("key"), 0.0), reverse=True)
        kept_index = set(ranked[:keep])
        rest_percent = sum(shares.get(legend[i].get("key"), 0.0) for i in ranked[keep:])
        closing = f"+ {len(legend) - keep} smaller classes ({rest_percent:.1f}%)"
    else:
        kept_index = set(range(keep))
        closing = f"+ {len(legend) - keep} more classes"
    shortened = [entry for i, entry in enumerate(legend) if i in kept_index]
    shortened.append({"label": closing, "color": None})
    return shortened

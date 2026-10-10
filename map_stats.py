"""
map_stats.py
------------
Summary statistics of the mapped data over the region, computed on Earth
Engine, and their export as CSV.

  - continuous maps: mean, median, min, max, standard deviation, 10th and
    90th percentiles, plus a histogram of values
  - categorical maps: area and share of the region for every class

Statistics are computed from the same image that is drawn on the map, so
the numbers and the picture always describe the same data.

Public API:
  continuous_stats(...)  -> dict | None
  class_stats(...)       -> dict | None
  stats_to_csv(...)      -> str
"""

from __future__ import annotations

import csv
import io

import ee

# Statistics do not need every pixel: Earth Engine may coarsen the working
# resolution so that at most this many pixels are read (bestEffort).
_MAX_PIXELS = 1e7
_HISTOGRAM_BINS = 20


def _region_area_km2(region_geom) -> ee.Number:
    return ee.Number(region_geom.area(maxError=100)).divide(1e6)


def continuous_stats(img: ee.Image, band: str, region_geom, vmin: float, vmax: float,
                     scale: float = 30) -> dict | None:
    """
    Summary statistics and a histogram for one continuous band over the region.

    vmin/vmax: the map's display range, used as the histogram's range so the
               histogram lines up with the legend.
    Returns None if the statistics could not be computed.
    """
    try:
        image = img.select([band])
        reducer = (ee.Reducer.mean()
                   .combine(ee.Reducer.minMax(), sharedInputs=True)
                   .combine(ee.Reducer.stdDev(), sharedInputs=True)
                   .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
                   .combine(ee.Reducer.count(), sharedInputs=True))
        kwargs = dict(geometry=region_geom, scale=scale, bestEffort=True, maxPixels=_MAX_PIXELS)
        request = {
            "stats": image.reduceRegion(reducer=reducer, **kwargs),
            "area_km2": _region_area_km2(region_geom),
        }
        if vmax > vmin:
            request["hist"] = image.reduceRegion(
                reducer=ee.Reducer.fixedHistogram(vmin, vmax, _HISTOGRAM_BINS), **kwargs).get(band)
        result = ee.Dictionary(request).getInfo()
    except Exception as e:
        print(f"Statistics failed: {e}")
        return None

    raw = result.get("stats") or {}
    if raw.get(f"{band}_mean") is None:
        return None
    rows = [
        ("Mean", raw.get(f"{band}_mean")),
        ("Median", raw.get(f"{band}_p50")),
        ("Minimum", raw.get(f"{band}_min")),
        ("Maximum", raw.get(f"{band}_max")),
        ("Standard deviation", raw.get(f"{band}_stdDev")),
        ("10th percentile", raw.get(f"{band}_p10")),
        ("90th percentile", raw.get(f"{band}_p90")),
    ]
    width = (vmax - vmin) / _HISTOGRAM_BINS if vmax > vmin else 0
    histogram = [
        {"from": start, "to": start + width, "pixels": count}
        for start, count in (result.get("hist") or [])
    ]
    return {
        "kind": "continuous",
        "rows": [(name, value) for name, value in rows if value is not None],
        "histogram": histogram,
        "area_km2": result.get("area_km2"),
    }


def class_stats(class_img: ee.Image, band: str, region_geom, labels: dict | None = None,
                scale: float = 30, share_of_region: bool = False) -> dict | None:
    """
    Area of every class of a categorical band over the region.

    labels: {pixel value: class name}; values without a name are reported
            as "Class <value>".
    share_of_region: express each class's share against the region's whole
            area (use when the map shows only selected classes) instead of
            against the mapped area.
    Returns rows sorted by area, largest first, or None on failure.
    """
    try:
        grouped = (ee.Image.pixelArea().addBands(class_img.select([band]))
                   .reduceRegion(
                       reducer=ee.Reducer.sum().group(groupField=1, groupName="value"),
                       geometry=region_geom, scale=scale, bestEffort=True, maxPixels=_MAX_PIXELS * 10))
        result = ee.Dictionary({
            "groups": grouped.get("groups"),
            "area_km2": _region_area_km2(region_geom),
        }).getInfo()
    except Exception as e:
        print(f"Class statistics failed: {e}")
        return None

    groups = result.get("groups") or []
    total_m2 = sum(g.get("sum", 0) for g in groups)
    if total_m2 <= 0:
        return None
    # When only some classes are mapped, a class's share is of the whole
    # region, not of the few classes shown.
    denominator_m2 = total_m2
    if share_of_region and result.get("area_km2"):
        denominator_m2 = max(result["area_km2"] * 1e6, total_m2)
    rows = []
    for g in groups:
        value = int(g["value"])
        rows.append({
            "value": value,
            "class": (labels or {}).get(value, f"Class {value}"),
            "area_km2": g["sum"] / 1e6,
            "percent": 100.0 * g["sum"] / denominator_m2,
        })
    rows.sort(key=lambda r: r["area_km2"], reverse=True)
    return {
        "kind": "categorical",
        "rows": rows,
        "area_km2": result.get("area_km2"),
        "mapped_km2": total_m2 / 1e6,
    }


def format_value(value: float) -> str:
    """Number with a sensible count of digits for its size."""
    if value is None:
        return "-"
    magnitude = abs(value)
    if magnitude == 0:
        return "0"
    if magnitude >= 10000:
        return f"{value:,.0f}"
    if magnitude >= 100:
        return f"{value:.1f}"
    if magnitude >= 1:
        return f"{value:.2f}"
    if magnitude >= 0.001:
        return f"{value:.4f}"
    return f"{value:.3e}"


def stats_to_csv(stats: dict, context: dict) -> str:
    """
    CSV with a short header block (what, where, when, which dataset) followed
    by the statistics table, and the histogram for continuous maps.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for key, value in context.items():
        writer.writerow([key, value])
    if stats.get("area_km2") is not None:
        writer.writerow(["Region area (km2)", f"{stats['area_km2']:.2f}"])
    writer.writerow([])

    if stats["kind"] == "categorical":
        writer.writerow(["Class value", "Class", "Area (km2)", "Share of area (%)"])
        for row in stats["rows"]:
            writer.writerow([row["value"], row["class"], f"{row['area_km2']:.3f}", f"{row['percent']:.2f}"])
    else:
        writer.writerow(["Statistic", "Value"])
        for name, value in stats["rows"]:
            writer.writerow([name, repr(float(value))])
        if stats.get("histogram"):
            writer.writerow([])
            writer.writerow(["Bin from", "Bin to", "Pixels"])
            for b in stats["histogram"]:
                writer.writerow([repr(float(b["from"])), repr(float(b["to"])), f"{b['pixels']:.0f}"])
    return out.getvalue()

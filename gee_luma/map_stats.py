"""
map_stats.py
------------
Summary statistics of the mapped data over the region, computed on Earth
Engine, and their export as CSV.

  - continuous maps: mean, median, min, max, standard deviation, 10th and
    90th percentiles, plus a histogram of values
  - categorical maps: area and share of the region for every class
  - multi-map figures: the same figures for every map, side by side

Statistics are computed from the same image that is drawn on the map, so
the numbers and the picture always describe the same data.

Public API:
  continuous_stats(...)  -> dict | None
  class_stats(...)       -> dict | None
  series_stats(...)      -> dict | None
  series_class_stats(...) -> dict | None
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
# Percentiles are computed exactly from at most this many pixels. Earth
# Engine's default percentile is approximate (values are binned first), and a
# few extreme pixels stretch the bins so far that every percentile comes out
# the same.
_EXACT_PERCENTILE_PIXELS = 1_000_000
# A large region with a heavy image (a country-wide composite computed on the
# fly) fails within seconds with "User memory limit exceeded". Earth Engine
# then gets the same request split into smaller pieces (tileScale), which is
# slower but fits; small regions keep the fast single pass.
_TILE_SCALES = (1, 4, 16)


def _get_info(build):
    """
    Evaluate build(tile_scale) on Earth Engine, retrying with a larger tile
    scale when it runs out of memory.
    """
    for tile_scale in _TILE_SCALES:
        try:
            return build(tile_scale).getInfo()
        except Exception as e:
            if "memory" not in str(e).lower() or tile_scale == _TILE_SCALES[-1]:
                raise
            print(f"Statistics ran out of memory at tileScale={tile_scale}; retrying in smaller pieces")


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
                   .combine(ee.Reducer.count(), sharedInputs=True))

        def build(tile_scale):
            kwargs = dict(geometry=region_geom, scale=scale, bestEffort=True, maxPixels=_MAX_PIXELS,
                          tileScale=tile_scale)
            request = {
                "stats": image.reduceRegion(reducer=reducer, **kwargs),
                "percentiles": image.reduceRegion(
                    reducer=ee.Reducer.percentile([10, 50, 90], maxRaw=_EXACT_PERCENTILE_PIXELS),
                    geometry=region_geom, scale=scale, bestEffort=True, maxPixels=_EXACT_PERCENTILE_PIXELS,
                    tileScale=tile_scale),
                # Area that actually has data (not masked by cloud or missing).
                "valid_km2": ee.Number(
                    ee.Image.pixelArea().updateMask(image.mask()).rename("area")
                    .reduceRegion(reducer=ee.Reducer.sum(), **kwargs).get("area")).divide(1e6),
                "area_km2": _region_area_km2(region_geom),
            }
            if vmax > vmin:
                request["hist"] = image.reduceRegion(
                    reducer=ee.Reducer.fixedHistogram(vmin, vmax, _HISTOGRAM_BINS), **kwargs).get(band)
            return ee.Dictionary(request)

        result = _get_info(build)
    except Exception as e:
        print(f"Statistics failed: {e}")
        return None

    raw = {**(result.get("stats") or {}), **(result.get("percentiles") or {})}
    if raw.get(f"{band}_mean") is None:
        return None
    coverage = None
    if result.get("valid_km2") is not None and result.get("area_km2"):
        coverage = min(100.0, 100.0 * result["valid_km2"] / result["area_km2"])
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
        "coverage_percent": coverage,
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
        def build(tile_scale):
            grouped = (ee.Image.pixelArea().addBands(class_img.select([band]))
                       .reduceRegion(
                           reducer=ee.Reducer.sum().group(groupField=1, groupName="value"),
                           geometry=region_geom, scale=scale, bestEffort=True, maxPixels=_MAX_PIXELS * 10,
                           tileScale=tile_scale))
            return ee.Dictionary({
                "groups": grouped.get("groups"),
                "area_km2": _region_area_km2(region_geom),
            })

        result = _get_info(build)
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


def series_stats(images: list, labels: list[str], band: str, region_geom, scale: float = 30) -> dict | None:
    """
    Mean, minimum, maximum, standard deviation and data coverage of every map
    of a multi-map figure, in one request.

    images / labels: the maps in reading order and their labels.
    Returns {"kind": "series", "rows": [{label, mean, min, max, std,
    coverage_percent}], "area_km2"} or None on failure.
    """
    try:
        names = [f"p{i}" for i in range(len(images))]
        values = ee.Image.cat([im.select([band]).rename([n]) for im, n in zip(images, names)])
        # Area of each map that actually has data (not masked or missing).
        valid = ee.Image.cat([ee.Image.pixelArea().updateMask(im.select([band]).mask()).rename([n])
                              for im, n in zip(images, names)])
        reducer = (ee.Reducer.mean()
                   .combine(ee.Reducer.minMax(), sharedInputs=True)
                   .combine(ee.Reducer.stdDev(), sharedInputs=True))

        def build(tile_scale):
            kwargs = dict(geometry=region_geom, scale=scale, bestEffort=True, maxPixels=_MAX_PIXELS,
                          tileScale=tile_scale)
            return ee.Dictionary({
                "stats": values.reduceRegion(reducer=reducer, **kwargs),
                "valid_m2": valid.reduceRegion(reducer=ee.Reducer.sum(), **kwargs),
                "area_km2": _region_area_km2(region_geom),
            })

        result = _get_info(build)
    except Exception as e:
        print(f"Series statistics failed: {e}")
        return None

    raw, valid_m2, area_km2 = result.get("stats") or {}, result.get("valid_m2") or {}, result.get("area_km2")
    rows = []
    for name, label in zip(names, labels):
        coverage = None
        if valid_m2.get(name) is not None and area_km2:
            coverage = min(100.0, 100.0 * valid_m2[name] / 1e6 / area_km2)
        rows.append({
            "label": label, "mean": raw.get(f"{name}_mean"), "min": raw.get(f"{name}_min"),
            "max": raw.get(f"{name}_max"), "std": raw.get(f"{name}_stdDev"), "coverage_percent": coverage,
        })
    if all(row["mean"] is None for row in rows):
        return None
    return {"kind": "series", "rows": rows, "area_km2": area_km2}


def series_class_stats(images: list, labels: list[str], band: str, region_geom,
                       class_labels: dict | None = None, scale: float = 30,
                       share_of_region: bool = False) -> dict | None:
    """
    Area of every class in every map of a multi-map figure.

    Returns {"kind": "series_categorical", "panels": [label, ...],
    "rows": [{value, class, area_km2: [per map], percent: [per map]}],
    "area_km2"}, classes sorted by their average area, or None on failure.
    """
    per_map = [class_stats(im, band, region_geom, class_labels, scale, share_of_region) for im in images]
    if not any(per_map):
        return None
    classes: dict[int, dict] = {}
    for i, stats in enumerate(per_map):
        for row in (stats or {}).get("rows", []):
            entry = classes.setdefault(row["value"], {
                "value": row["value"], "class": row["class"],
                "area_km2": [0.0] * len(images), "percent": [0.0] * len(images)})
            entry["area_km2"][i] = row["area_km2"]
            entry["percent"][i] = row["percent"]
    rows = sorted(classes.values(), key=lambda r: sum(r["area_km2"]), reverse=True)
    return {
        "kind": "series_categorical", "panels": list(labels), "rows": rows,
        "area_km2": next(s["area_km2"] for s in per_map if s),
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
    if stats.get("coverage_percent") is not None:
        writer.writerow(["Region covered by valid data (%)", f"{stats['coverage_percent']:.1f}"])
    writer.writerow([])

    if stats["kind"] == "series":
        writer.writerow(["Map", "Mean", "Minimum", "Maximum", "Standard deviation",
                         "Region covered by valid data (%)"])
        for row in stats["rows"]:
            writer.writerow([row["label"]]
                            + ["" if row[k] is None else repr(float(row[k])) for k in ("mean", "min", "max", "std")]
                            + ["" if row["coverage_percent"] is None else f"{row['coverage_percent']:.1f}"])
    elif stats["kind"] == "series_categorical":
        writer.writerow(["Class value", "Class"]
                        + [f"{label} area (km2)" for label in stats["panels"]]
                        + [f"{label} share (%)" for label in stats["panels"]])
        for row in stats["rows"]:
            writer.writerow([row["value"], row["class"]]
                            + [f"{v:.3f}" for v in row["area_km2"]] + [f"{v:.2f}" for v in row["percent"]])
    elif stats["kind"] == "categorical":
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

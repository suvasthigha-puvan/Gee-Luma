"""
dataset_options.py
------------------
The datasets a request could be answered with, when there are several.

"NDVI using MODIS" fits a dozen MODIS products (250 m, 500 m or 1 km; Terra
or Aqua; 16-day or monthly), and "rainfall in Sri Lanka" names no dataset at
all while CHIRPS, GPM and others all map rainfall. Rather than let the agent
settle on one silently, the pipeline asks the person which one they want
before any processing starts.

`find_dataset_options()` returns the datasets to offer, or None when there is
nothing to ask: the request names one dataset exactly (a product code such as
MOD13Q1 or a full collection ID), or only one dataset fits.

The candidates come from the live Earth Engine catalog, so every ID offered is
real; the language model only decides which of them suit the request.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import ee

from gee_luma.catalog_search import (
    _load_catalogs, _DATASET_NAMES, RECOMMENDED_DATASETS, recommended_for, search_gee_catalog,
)
from gee_luma.stac_metadata import fetch_dataset_metadata

MAX_OPTIONS = 8          # more than this is a catalog listing, not a choice
MAX_CANDIDATES = 150     # datasets of the family shown to the language model
AUTO_CHOICE = "auto"     # "let Gee-Luma pick", in place of a dataset ID

# Satellite series whose number is part of the name ("Sentinel-2", "Landsat 8").
_NUMBERED = ("sentinel", "landsat")
_IMAGE_TYPES = ("image", "image_collection")


def _word(name: str) -> re.Pattern:
    """`name` as a whole word: 'esa' must not match inside 'mesa'."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z])")


def named_datasets(prompt: str) -> list[tuple[str, str]]:
    """
    Dataset, sensor and provider names the request uses, as (family, text):
    the catalog name ("sentinel") and what the person wrote ("Sentinel-2").
    """
    found = []
    for name in _DATASET_NAMES:
        match = _word(name).search(prompt.lower())
        if match:
            end = match.end()
            if name in _NUMBERED:
                number = re.match(r"[- ]?\d{1,2}[a-z]?(?![a-z0-9])", prompt[end:].lower())
                end += number.end() if number else 0
            found.append((name, prompt[match.start():end]))
    return found


def _haystack(dataset: dict) -> str:
    return " ".join(str(dataset.get(k, "")) for k in ("id", "title", "tags", "provider")).lower()


def _family(names: list[str]) -> list[dict]:
    """Image datasets of the catalog that belong to the named family."""
    catalogs = _load_catalogs()
    patterns = [_word(n) for n in names]
    for source in ("official", "community"):
        scored = []
        for dataset in catalogs.get(source, []):
            if dataset.get("type") not in _IMAGE_TYPES or "deprecated" in str(dataset.get("title", "")).lower():
                continue
            hay = _haystack(dataset)
            hits = sum(1 for p in patterns if p.search(hay))
            if hits:
                scored.append((hits, dataset))
        if len(scored) >= 2:
            # A request naming two things ("ESA WorldCover") means the datasets that are both.
            best = max(hits for hits, _d in scored)
            return [d for hits, d in scored if hits == best]
        # Fewer than two official datasets: the family may live in the community catalog.
    return []


def _whole_catalog() -> list[dict]:
    """Every image dataset of the official catalog (for requests that name no dataset)."""
    return [d for d in _load_catalogs().get("official", [])
            if d.get("type") in _IMAGE_TYPES and "deprecated" not in str(d.get("title", "")).lower()]


def _theme_matches(prompt: str, limit: int = 8) -> list[str]:
    """
    IDs of catalog datasets tagged with the theme of the request (rainfall,
    land cover, ...), best match first. They back up the language model's
    first pass, which tends to stop at the two or three best-known datasets.
    """
    lower = re.sub(r"\bET\b", "evapotranspiration", prompt).lower()
    words = []
    for phrases, _rec_id, _rec_title in RECOMMENDED_DATASETS:
        if any(re.search(r"\b" + re.escape(ph) + r"s?\b", lower) for ph in phrases):
            words += phrases[:3]
    if not words:
        return []
    found = search_gee_catalog(" ".join(words), max_results=limit * 2, include_community=False)
    return [r["id"] for r in found if r.get("type") in _IMAGE_TYPES][:limit]


def _names_one_product(prompt: str, family: list[dict]) -> bool:
    """True when the request spells out a product code (MOD13Q1) or a full collection ID."""
    lower = prompt.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", lower))
    for dataset in family:
        dataset_id = str(dataset.get("id", "")).lower()
        if dataset_id and dataset_id in lower:
            return True
        for part in dataset_id.split("/"):
            if (len(part) >= 5 and re.search(r"\d", part) and re.search(r"[a-z]", part)
                    and part in tokens):
                return True
    return False


_RULES = (
    "Each one must:\n"
    "- hold the requested variable itself, or the spectral bands needed to compute it. A dataset "
    "about a different variable must never be selected (no land cover, cloud score or temperature "
    "product for a true-colour or NDVI request; no rainfall product for an evapotranspiration request);\n"
    "- come from the satellite or sensor exactly as the user named it, if they named one (\"Landsat 8\" "
    "excludes Landsat 9, \"Sentinel-2\" excludes Sentinel-1 and products merely derived from Sentinel-2);\n"
    "- cover the place in the request - never a dataset limited to another country or continent "
    "(CONUS, USA, North America, Europe, ... when the place is elsewhere) - and still be updated if "
    "the request is about a recent period.\n"
    "Leave out quality, context and auxiliary layers (identifier grids, land area, data masks), and "
    "raw (unprocessed) data when a processed version is listed.\n"
)


def _json(answer) -> dict:
    text = str(answer or "")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def _shortlist(prompt: str, named: str, family: list[dict], llm) -> tuple[list[str], dict, list | None]:
    """
    First pass, over the whole family: the IDs of the datasets that may suit
    the request, the period it asks for ({} if it names none), and an
    approximate [west, south, east, north] box of the place (None if unknown).
    """
    listing = "\n".join(
        f"{d['id']} | {d.get('title', '')} | {', '.join(str(d.get('tags', '')).split(', ')[:8])}"
        for d in family
    )
    today = date.today().isoformat()
    if named:
        source = (f'The request names "{named}" as the data source. Below are the Google Earth Engine '
                  "datasets related to that name, one per line as: id | title | tags.\n\n")
    else:
        source = ("The request names no data source, so any dataset that maps the requested variable "
                  "may serve. Below is the Google Earth Engine catalog, one dataset per line as: "
                  "id | title | tags.\n\n")
    answer = llm.call(
        f"Today's date is {today}.\n"
        f'A user of a mapping application asked: "{prompt}"\n\n'
        f"{source}"
        f"{listing}\n\n"
        "Select the datasets that are genuine alternatives for making exactly the map the user asks "
        f"for. {_RULES}"
        "Include every genuine alternative: the well-known, widely used datasets for the variable from "
        "every sensor that provides it (for a spectral index or a colour image that means Sentinel-2, "
        "Landsat 8 and 9 and MODIS surface reflectance as well as ready-made index products), and the "
        "other resolutions, update frequencies, satellites (Terra and Aqua) and versions of the same "
        "product. If the request already identifies exactly one dataset, select only that one.\n"
        f"Give at most {MAX_OPTIONS * 2}, the most suitable first.\n"
        f"Also give the period the request asks for. Today is {today}: \"last 3 months\" means the three "
        f"months ending {today}, \"this year\" means {today[:4]}. Use null for both dates when the request "
        "names no period.\n"
        "Also give an approximate bounding box of the place the map is of, in decimal degrees "
        "(null when the request names no place).\n"
        'Return ONLY valid JSON: {"period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}, '
        '"place_bbox": [west, south, east, north], "ids": ["<id exactly as listed>", ...]}'
    )
    parsed = _json(answer)
    period = parsed.get("period") if isinstance(parsed.get("period"), dict) else {}
    box = parsed.get("place_bbox")
    if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)
            and -180 <= box[0] <= box[2] <= 180 and -90 <= box[1] <= box[3] <= 90):
        box = None
    return [str(i).strip() for i in parsed.get("ids", [])], period, box


def _confirm(prompt: str, named: str, options: list[dict], llm) -> list[dict]:
    """
    Second pass, over the shortlist only and with each dataset's resolution,
    frequency and coverage in view: the options that really fit, best first,
    as [{"id", "note"}]. A short list is judged far more reliably than a catalog.
    """
    listing = "\n".join(
        f"{o['id']} | {o['title']} | {o['tags']} | {option_summary(o) or 'no details'}" for o in options
    )
    answer = llm.call(
        f"Today's date is {date.today().isoformat()}.\n"
        f'A user of a mapping application asked: "{prompt}"\n'
        + (f'The request names "{named}" as the data source.\n' if named else "")
        + "\nThese Google Earth Engine datasets were shortlisted, one per line as: "
        "id | title | tags | resolution - update frequency - coverage.\n\n"
        f"{listing}\n\n"
        "Judge every dataset in the list, one by one, on whether it can make exactly the map the user "
        f"asks for. {_RULES}"
        "For each dataset answer three questions: does it hold the requested variable (or the bands to "
        "compute it) as a main data layer; does its coverage include the place in the request (a national "
        "dataset of another country does not: USDA, NLCD and CONUS products cover only the USA); and is "
        "it from the source the user named (true when they named none). Then write a note of at most 12 "
        "words saying what sets it apart from the others (satellite or source, method, processing "
        "level) - do not repeat its resolution or frequency.\n"
        "List them with the most suitable first.\n"
        'Return ONLY valid JSON: {"datasets": [{"id": "<id exactly as listed>", "holds_variable": true, '
        '"covers_place": true, "from_named_source": true, "note": "<note>"}]}'
    )
    return [p for p in _json(answer).get("datasets", [])
            if isinstance(p, dict) and p.get("holds_variable") and p.get("covers_place")
            and p.get("from_named_source", True)]


def _resolution_text(metres) -> str:
    if not metres:
        return ""
    if metres >= 1000:
        return f"{metres / 1000:.3g} km"
    return f"{metres:.2g} m" if metres < 10 else f"{round(metres):g} m"     # 0.5 m, 2.5 m, 30 m


def _cadence_text(cadence: str) -> str:
    """'every 16 day' as the catalog gives it -> 'every 16 days'; 'every 1 month' -> 'monthly'."""
    match = re.fullmatch(r"every (\d+) (day|month|year|hour|minute)s?", cadence or "")
    if not match:
        return ""
    count, unit = int(match.group(1)), match.group(2)
    if count == 1:
        return {"day": "daily", "month": "monthly", "year": "yearly", "hour": "hourly"}.get(unit, f"every {unit}")
    return f"every {count} {unit}s"


def _outside_period(meta: dict, period: dict) -> bool:
    """
    True when a regularly updated dataset cannot cover the requested period:
    it starts after the period ends, or it stopped more than a year before the
    period begins. (A yearly product a few months behind is still offered -
    the pipeline shows its most recent release.)
    """
    try:
        start, end = date.fromisoformat(str(period["start"])), date.fromisoformat(str(period["end"]))
    except Exception:
        return False
    if not meta["cadence"] or not meta["date_start"]:
        return False        # single, undated dataset (elevation, one-off land cover)
    if date.fromisoformat(meta["date_start"]) > end:
        return True
    return bool(meta["date_end"]) and date.fromisoformat(meta["date_end"]) < start - timedelta(days=366)


def _overlaps(boxes: list, bounds: dict) -> bool:
    """True when any of the dataset's [west, south, east, north] boxes touches the region's bounds."""
    for west, south, east, north in boxes:
        if south > bounds["lat_max"] or north < bounds["lat_min"]:
            continue
        # A box crossing the antimeridian has west > east.
        spans = [(west, east)] if west <= east else [(west, 180.0), (-180.0, east)]
        if any(w <= bounds["lon_max"] and e >= bounds["lon_min"] for w, e in spans):
            return True
    return False


def _is_global(boxes: list) -> bool:
    """True when the dataset's published extent spans the whole width of the globe."""
    return any(west <= -170 and east >= 170 for west, _south, east, _north in boxes)


def _ids_without_data(kinds: dict, bounds: dict) -> set:
    """
    The datasets of {id: "image" | "image_collection"} that have no image over
    the region, asked of Earth Engine in one request. A published extent can
    be far wider than the data (USGS 3DEP lists a box spanning the Pacific for
    a US-only product); the images' own footprints are what count.
    """
    if not kinds:
        return set()
    region = ee.Geometry.Rectangle([bounds["lon_min"], bounds["lat_min"], bounds["lon_max"], bounds["lat_max"]])
    checks = {
        dataset_id: (ee.Image(dataset_id).geometry().intersects(region, ee.ErrorMargin(1000)) if kind == "image"
                     else ee.ImageCollection(dataset_id).filterBounds(region).limit(1).size().gt(0))
        for dataset_id, kind in kinds.items()
    }
    try:
        found = ee.Dictionary(checks).getInfo()
    except Exception:
        return set()            # could not check: offer them all, as before
    return {dataset_id for dataset_id, has_data in found.items() if not has_data}


def _countries_in(bounds: dict) -> list[str]:
    """Names of the countries the region's bounding box touches (at most five), or [] if unknown."""
    try:
        box = ee.Geometry.Rectangle([bounds["lon_min"], bounds["lat_min"], bounds["lon_max"], bounds["lat_max"]])
        names = (ee.FeatureCollection("WM/geoLab/geoBoundaries/600/ADM0").filterBounds(box)
                 .aggregate_array("shapeName").distinct().getInfo())
        return [str(n) for n in names][:5]
    except Exception:
        return []


def _describe(dataset: dict, note: str, period: dict, bounds: dict | None = None) -> dict | None:
    """One option as shown to the person, or None if the catalog says it should not be offered."""
    option = {
        "id": dataset["id"], "title": dataset.get("title") or dataset["id"],
        "provider": dataset.get("provider", ""), "note": note,
        "tags": ", ".join(str(dataset.get("tags", "")).split(", ")[:8]),
        "resolution": "", "resolution_m": None, "cadence": "", "coverage": "",
    }
    meta = fetch_dataset_metadata(dataset["id"])
    if meta:
        if meta["deprecated"] or meta["type"] not in _IMAGE_TYPES or _outside_period(meta, period):
            return None
        if bounds and meta.get("bbox") and not _overlaps(meta["bbox"], bounds):
            return None         # the dataset's published extent misses the region
        if meta.get("bbox") and not _is_global(meta["bbox"]):
            option["regional"] = meta["type"]       # its image footprints are checked against the region
        option["title"] = meta["title"] or option["title"]
        option["provider"] = meta["provider"] or option["provider"]
        option["resolution_m"] = meta["gsd"]
        option["resolution"] = _resolution_text(meta["gsd"])
        option["cadence"] = _cadence_text(meta["cadence"])
        if meta["date_start"]:
            option["coverage"] = f"{meta['date_start']} to {meta['date_end'] or 'present'}"
    return option


def find_dataset_options(prompt: str, llm, region_bounds: dict | None = None,
                         region_label: str = "") -> dict | None:
    """
    {"named": the dataset name as the request wrote it ("" if it names none),
    "options": [...]} when two or more datasets fit the request; else None.

    A request that names a dataset family is offered the datasets of that
    family; one that names none ("rainfall in Sri Lanka") is offered the
    datasets on its theme from the whole catalog, the standard one first.

    Datasets with no data over the place are left out: the uploaded region's
    bounds when there is one (region_bounds: {lon_min, lon_max, lat_min,
    lat_max}), otherwise the language model's box for the place named in the
    request. With an uploaded region the request text does not say where the
    map is ("the uploaded area"), so the language model is also told.

    Never raises: if the catalog or the language model cannot be reached the
    request simply goes ahead without a question.
    """
    try:
        # What the language model reads: the request, plus where an uploaded region lies.
        request = prompt
        if region_bounds:
            countries = _countries_in(region_bounds)
            b = region_bounds
            request = (f'{prompt} [The map covers the user\'s uploaded region "{region_label or "region"}", '
                       + (f"in {', '.join(countries)}, " if countries else "")
                       + f"longitude {b['lon_min']:.2f} to {b['lon_max']:.2f}, "
                       f"latitude {b['lat_min']:.2f} to {b['lat_max']:.2f}.]")
        names = named_datasets(prompt)
        named = " ".join(text for _name, text in names)
        family = _family([name for name, _text in names]) if names else _whole_catalog()
        if len(family) < 2 or _names_one_product(prompt, family):
            return None
        by_id = {d["id"]: d for d in family}
        ids, period, place_box = _shortlist(request, named, family[:MAX_CANDIDATES] if names else family, llm)
        bounds = region_bounds
        if not bounds and place_box:
            # The language model's box is approximate: widen it so a dataset
            # that does cover the place is never left out.
            west, south, east, north = place_box
            bounds = {"lon_min": max(west - 1, -180), "lon_max": min(east + 1, 180),
                      "lat_min": max(south - 1, -90), "lat_max": min(north + 1, 90)}
        # The standard dataset for the theme is always among the options, and leads them.
        standard = [] if names else [rec_id for rec_id, _title in recommended_for(prompt) if rec_id in by_id]
        if not names:
            ids += _theme_matches(prompt)
        shortlist = {}
        for dataset_id in (standard + ids)[:MAX_OPTIONS * 2 + 2]:
            if dataset_id in by_id and dataset_id not in shortlist:
                option = _describe(by_id[dataset_id], "", period, bounds)
                if option:
                    option["standard"] = dataset_id in standard
                    shortlist[dataset_id] = option
        if bounds:
            regional = {i: o["regional"] for i, o in shortlist.items() if o.get("regional")}
            for dataset_id in _ids_without_data(regional, bounds):
                shortlist.pop(dataset_id, None)
        if len(shortlist) < 2:
            return None
        options = []
        for pick in _confirm(request, named, list(shortlist.values()), llm):
            option = shortlist.pop(str(pick.get("id", "")).strip(), None)
            if option:
                option["note"] = str(pick.get("note") or "").strip().rstrip(".")
                options.append(option)
        # Kept whatever the second pass said: it is what the request gets by default.
        options = [o for o in shortlist.values() if o["standard"]] + options
        for option in options:
            option.pop("tags")
            option.pop("regional", None)
            if option["standard"] and not option["note"]:
                option["note"] = "Standard choice for this kind of map"
        if len(options) < 2:
            return None
        # The standard dataset first, then finest resolution; among equals, the
        # language model's order of suitability.
        options = sorted(options[:MAX_OPTIONS],
                         key=lambda o: (not o["standard"], o["resolution_m"] or float("inf")))
        return {"named": named, "options": options}
    except Exception:
        return None


def option_summary(option: dict) -> str:
    """Resolution, update frequency and coverage of an option on one line."""
    return " - ".join(option[k] for k in ("resolution", "cadence", "coverage") if option.get(k))

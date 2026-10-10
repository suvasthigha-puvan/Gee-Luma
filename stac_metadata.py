"""
stac_metadata.py
----------------
Per-dataset metadata from the public Earth Engine STAC catalog.

Every dataset in the official Earth Engine catalog publishes a JSON record
describing its bands: scale and offset, units, class values with names and
colours for categorical bands, native resolution, the period it covers, and
who provides it. Reading that record is what lets the app handle a dataset
it has never seen before instead of relying on hand-written tables:

  - scale / offset   -> values shown in real units
  - gee:classes      -> a proper class legend for any categorical band
  - units            -> legend label
  - date range       -> clear message when the request is outside coverage
  - title / provider -> data credit line on the map

Community datasets (projects/...) are not in this catalog; callers get None
and fall back to live band introspection and data-driven colour ranges.

Public API:
  fetch_dataset_metadata(cid) -> dict | None
  get_dataset_info_tool       -> CrewAI tool wrapping the same lookup
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests
import streamlit as st
from crewai.tools import tool

STAC_ROOT = "https://storage.googleapis.com/earthengine-stac/catalog"
_FETCH_TIMEOUT = 15  # seconds


def _clean_text(text) -> str:
    """Catalog text as plain text: HTML tags (e.g. <sub>2</sub>) removed, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text))).strip()


def _short_label(description: str, max_len: int = 34) -> str:
    """First phrase of a class description, short enough for a legend row."""
    # Cut at the end of the first sentence or clause (not at a decimal point).
    text = re.split(r"\.(?:\s|$)|[:;(]", _clean_text(description), maxsplit=1)[0].strip().replace("_", " ")
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].rstrip(" ,-/")     # cut at a word boundary
    return text or str(description)[:max_len]


def _first(value, default=None):
    """STAC stores many scalars as one-element lists."""
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


def _parse_band(raw: dict) -> dict:
    classes = [
        {
            "value": c.get("value"),
            "label": _short_label(c.get("description", c.get("value"))),
            "color": "#" + str(c.get("color", "888888")).lstrip("#"),
        }
        for c in raw.get("gee:classes", [])
        if c.get("value") is not None
    ]
    return {
        "name": raw.get("name", ""),
        "description": _clean_text(raw.get("description", "")),
        "units": _clean_text(raw.get("gee:units", "")).replace("^", ""),
        "scale": raw.get("gee:scale"),
        "offset": raw.get("gee:offset"),
        "gsd": _first(raw.get("gsd")),
        "classes": classes,
        "is_bitmask": "gee:bitmask" in raw,
    }


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_dataset_metadata(cid: str) -> dict[str, Any] | None:
    """
    Metadata for a dataset in the official Earth Engine catalog, or None if
    the dataset is not listed there (community assets) or the fetch fails.
    """
    cid = (cid or "").strip()
    if not cid or cid.startswith("projects/") or cid.startswith("users/"):
        return None
    url = f"{STAC_ROOT}/{cid.split('/')[0]}/{cid.replace('/', '_')}.json"
    try:
        resp = requests.get(url, timeout=_FETCH_TIMEOUT)
        if resp.status_code != 200:
            return None
        doc = resp.json()
    except Exception:
        return None

    summaries = doc.get("summaries", {}) or {}
    bands = {}
    for raw in summaries.get("eo:bands", []) or []:
        band = _parse_band(raw)
        if band["name"]:
            bands[band["name"]] = band

    visualizations = []
    for vis in summaries.get("gee:visualizations", []) or []:
        band_vis = (vis.get("image_visualization") or {}).get("band_vis") or {}
        if band_vis.get("bands"):
            visualizations.append({
                "name": vis.get("display_name", ""),
                "bands": band_vis["bands"],
                "palette": ["#" + str(c).lstrip("#") for c in band_vis.get("palette", [])],
            })

    interval = _first((doc.get("extent", {}).get("temporal", {}) or {}).get("interval"), [None, None])
    cadence = doc.get("gee:interval") or {}
    gsd_values = [b["gsd"] for b in bands.values() if isinstance(b["gsd"], (int, float))]
    summary_gsd = _first(summaries.get("gsd"))
    if isinstance(summary_gsd, (int, float)):
        gsd_values.append(summary_gsd)
    providers = [p.get("name", "") for p in doc.get("providers", []) if p.get("name")]

    return {
        "id": doc.get("id", cid),
        "title": doc.get("title", cid),
        "type": doc.get("gee:type", ""),            # image | image_collection | table | ...
        "provider": providers[0] if providers else "",
        "date_start": (interval[0] or "")[:10],
        "date_end": (interval[1] or "")[:10],
        "cadence": (f"every {cadence.get('interval')} {cadence.get('unit')}"
                    if cadence.get("interval") else ""),
        "deprecated": bool(doc.get("deprecated")) or "[deprecated]" in str(doc.get("title", "")),
        "gsd": min(gsd_values) if gsd_values else None,
        "bands": bands,
        "visualizations": visualizations,
    }


def stac_palette_for_band(meta: dict | None, band: str) -> list[str]:
    """Colour ramp the catalog itself uses to display this band, if it gives one."""
    for vis in (meta or {}).get("visualizations", []):
        if vis["bands"] == [band] and len(vis["palette"]) >= 2:
            return vis["palette"]
    return []


def band_display_label(meta: dict | None, band: str) -> str:
    """Legend label for a band: its description plus units, e.g. 'Precipitation (mm/d)'."""
    info = (meta or {}).get("bands", {}).get(band)
    if not info:
        return band
    text = _short_label(info["description"], 40) if info["description"] else band
    text = text[0].upper() + text[1:] if text else band
    return f"{text} ({info['units']})" if info["units"] else text


@tool("Get GEE Dataset Info")
def get_dataset_info_tool(collection_id: str) -> str:
    """
    Look up the real contents of a Google Earth Engine dataset by its exact
    collection ID: title, type (image / image_collection / table), the period
    it covers, how often it updates, and every band with its description,
    units, scale factor and whether it is categorical.

    Call this for the collection you have chosen BEFORE writing your final
    answer. Use only band names it returns, copy scale factors from it, and
    keep date_start/date_end inside the period it reports. If it reports
    type "table" or "not found", choose a different collection.
    """
    cid = (collection_id or "").strip().strip("'\"")
    meta = fetch_dataset_metadata(cid)
    if meta is None:
        # Not in the official catalog: fall back to asking Earth Engine directly.
        try:
            from dataset_config import introspect_collection
            info = introspect_collection(cid)
        except Exception as exc:
            info = {"error": str(exc), "bands": []}
        if info.get("error") or not info.get("bands"):
            return json.dumps({
                "id": cid, "found": False,
                "message": "Dataset not found or not an image dataset. Choose a different collection ID.",
            })
        return json.dumps({
            "id": cid, "found": True, "source": "live introspection (community dataset)",
            "is_temporal": not info.get("is_static", False),
            "bands": [{"name": b} for b in info["bands"][:60]],
        })

    bands = []
    for b in list(meta["bands"].values())[:60]:
        entry = {"name": b["name"], "description": b["description"][:90]}
        if b["units"]:
            entry["units"] = b["units"]
        if b["scale"] is not None:
            entry["scale_factor"] = b["scale"]
        if b["offset"] is not None:
            entry["scale_offset"] = b["offset"]
        if b["classes"]:
            entry["categorical_classes"] = len(b["classes"])
        if b["is_bitmask"]:
            entry["quality_bitmask"] = True
        bands.append(entry)

    return json.dumps({
        "id": meta["id"], "found": True, "title": meta["title"], "type": meta["type"],
        "deprecated": meta["deprecated"],
        "available_from": meta["date_start"], "available_to": meta["date_end"],
        "cadence": meta["cadence"], "resolution_m": meta["gsd"],
        "bands": bands,
    }, ensure_ascii=False)

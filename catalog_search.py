"""
catalog_search.py
------------------
Live Google Earth Engine dataset catalog search.

Replaces the old static "Section 2 — GEE Dataset Registry" block that used to
live in knowledge_base.md. Instead of asking the LLM to recall a collection ID
purely from memory (which risks stale, deprecated, or outright hallucinated
IDs for anything not in the top few well-known sensors), the agent calls the
`search_gee_catalog` tool to look up real collection IDs from:

  - Official EE Data Catalog (~880 datasets), mirrored at:
    https://raw.githubusercontent.com/samapriya/ee-catalog-jsons/refs/heads/main/gee_catalog_formatted.json
  - Awesome GEE Community Catalog (~4,300 datasets):
    https://raw.githubusercontent.com/samapriya/awesome-gee-community-datasets/master/community_datasets.json

These are the same catalog sources the `geeadd utils search` CLI command
uses, and they're kept up to date by their maintainer independently of us.

Scope note: this module ONLY resolves dataset *identity* (collection ID,
title, provider, docs link) — not band names or scale factors. Band-level
verification is still handled entirely by `introspect_collection()` in
dataset_config.py, which queries the dataset live via `ee` once a collection
ID has been chosen. The two are complementary: catalog search helps the
agent pick the right dataset up front, introspect_collection() confirms
what's actually inside it once the app runs.

Sections 3 (Precomputed Band Registry) and 6 (Agent Decision Rules) of
knowledge_base.md are unaffected by this module — those encode judgment
calls (precomputed-first, scale conventions, sensor fallback order) that no
catalog lookup can regenerate.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests
import streamlit as st
from crewai.tools import tool

OFFICIAL_CATALOG_URL = (
    "https://raw.githubusercontent.com/samapriya/ee-catalog-jsons/"
    "refs/heads/main/gee_catalog_formatted.json"
)
COMMUNITY_CATALOG_URL = (
    "https://raw.githubusercontent.com/samapriya/awesome-gee-community-datasets/"
    "master/community_datasets.json"
)

_FETCH_TIMEOUT = 15  # seconds

# Well-established global datasets per theme. When a search touches one of
# these themes the dataset is returned first and marked as recommended, so a
# general request ("land cover of X") gets the standard product rather than
# whichever regional or coarse dataset happens to match the words.
RECOMMENDED_DATASETS: list[tuple[tuple[str, ...], str, str]] = [
    (("land cover", "landcover", "land use", "lulc", "cropland", "farmland", "built-up area",
      "crop class", "crop area", "crop extent", "crop land", "crop cover", "agricultural land", "agriculture class",
      "forest class", "water class", "urban class", "built-up class"),"ESA/WorldCover/v200", "ESA WorldCover 10m v200 (global land cover, 2021)"),
    (("elevation", "dem", "terrain", "slope", "hillshade", "aspect"), "USGS/SRTMGL1_003", "NASA SRTM Digital Elevation 30m"),
    (("rain", "rainfall", "precipitation"), "UCSB-CHG/CHIRPS/DAILY", "CHIRPS Daily Precipitation (global, 1981-present)"),
    (("land surface temperature", "lst"), "MODIS/061/MOD11A2", "MODIS Terra Land Surface Temperature 8-Day 1km"),
    (("night light", "nighttime", "night-time"), "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG", "VIIRS Nighttime Day/Night Band Monthly Composites"),
    (("population",), "WorldPop/GP/100m/pop", "WorldPop Global Project Population Data 100m"),
    (("surface water", "water occurrence"), "JRC/GSW1_4/GlobalSurfaceWater", "JRC Global Surface Water Mapping Layers v1.4"),
    (("no2", "nitrogen dioxide"), "COPERNICUS/S5P/OFFL/L3_NO2", "Sentinel-5P OFFL NO2: Offline Nitrogen Dioxide"),
    (("carbon monoxide",), "COPERNICUS/S5P/OFFL/L3_CO", "Sentinel-5P OFFL CO: Offline Carbon Monoxide"),
    (("methane", "ch4"), "COPERNICUS/S5P/OFFL/L3_CH4", "Sentinel-5P OFFL CH4: Offline Methane"),
    (("so2", "sulphur dioxide", "sulfur dioxide"), "COPERNICUS/S5P/OFFL/L3_SO2", "Sentinel-5P OFFL SO2: Offline Sulphur Dioxide"),
    (("evapotranspiration",), "MODIS/061/MOD16A2GF", "MODIS Terra Net Evapotranspiration Gap-Filled 8-Day 500m"),
    (("air temperature", "2m temperature"), "ECMWF/ERA5_LAND/MONTHLY_AGGR", "ERA5-Land Monthly Aggregated - ECMWF Climate Reanalysis"),
]


# Names by which a request points at a particular dataset, sensor or provider.
# A request that uses one is not answered with the standard dataset unless
# the standard dataset is the one named.
_DATASET_NAMES = (
    "esa", "worldcover", "worldcereal", "world cereal", "corine", "modis", "mcd12", "dynamic world",
    "copernicus", "proba", "nlcd", "globcover", "esri", "glad", "landsat", "sentinel", "mapbiomas",
    "cgls", "usda", "cdl", "era5", "ecmwf", "gpm", "imerg", "trmm", "terraclimate", "chirps", "srtm",
    "aster", "alos", "nasadem", "viirs", "dmsp", "worldpop", "ghsl", "gpw", "landscan", "jrc",
    "hansen", "smap", "gldas", "daymet", "prism", "tropomi", "merit", "gedi", "noaa", "nasa", "usgs",
    "jaxa", "fao", "openlandmap", "landfire", "glims", "cams", "persiann", "gsmap",
)


def recommended_for(text: str) -> list[tuple[str, str]]:
    """(id, title) of the standard datasets for every theme mentioned in `text`."""
    lower = text.lower()
    named = [n for n in _DATASET_NAMES if re.search(r"\b" + re.escape(n) + r"\b", lower)]
    matches = []
    for phrases, rec_id, rec_title in RECOMMENDED_DATASETS:
        # Whole words only: "rain" must not match "rainforest".
        if any(re.search(r"\b" + re.escape(ph) + r"s?\b", lower) for ph in phrases):
            target = f"{rec_id} {rec_title}".lower()
            if named and not any(n in target for n in named):
                continue        # the request names some other dataset
            matches.append((rec_id, rec_title))
    return matches


@st.cache_resource(ttl=24 * 3600, show_spinner=False)
def _load_catalogs() -> dict[str, Any]:
    """Fetch + cache both catalog JSON files once per day per server process."""
    catalogs: dict[str, Any] = {"official": [], "community": []}
    for key, url in (("official", OFFICIAL_CATALOG_URL), ("community", COMMUNITY_CATALOG_URL)):
        try:
            resp = requests.get(url, timeout=_FETCH_TIMEOUT)
            resp.raise_for_status()
            catalogs[key] = resp.json()
        except Exception as exc:  # network hiccup, rate limit, schema change, etc.
            catalogs[f"{key}_error"] = str(exc)
    return catalogs


def _ee_snippet(dataset_id: str, dtype: str) -> str:
    if dtype == "image_collection":
        return f"ee.ImageCollection('{dataset_id}')"
    if dtype == "image":
        return f"ee.Image('{dataset_id}')"
    if dtype == "table":
        return f"ee.FeatureCollection('{dataset_id}')"
    return f"'{dataset_id}'"


def _score(dataset: dict[str, Any], keywords: list[str]) -> int:
    """Cheap relevance score: exact-phrase + per-keyword hits across key fields."""
    title = str(dataset.get("title", "")).lower()
    tags = str(dataset.get("tags", "")).lower()
    theme = str(dataset.get("thematic_group", "")).lower()
    provider = str(dataset.get("provider", "")).lower()
    asset_id = str(dataset.get("id", "")).lower()

    phrase = " ".join(keywords)
    score = 0
    if phrase and phrase in title:
        score += 20
    if phrase and phrase in tags:
        score += 10
    for kw in keywords:
        if kw in title:
            score += 5
        if kw in tags:
            score += 3
        if kw in theme:
            score += 2
        if kw in provider:
            score += 2
        if kw in asset_id:
            score += 2
    return score


def search_gee_catalog(
    query: str, max_results: int = 8, include_community: bool = True
) -> list[dict[str, Any]]:
    """
    Search the live GEE dataset catalog (official + community) for `query`.
    Returns a list of compact dataset records sorted by relevance.
    """
    catalogs = _load_catalogs()
    keywords = [k.strip().lower() for k in re.split(r"[,\s]+", query) if k.strip()]
    if not keywords:
        return []

    pool: list[tuple[int, dict[str, Any], str]] = []
    for dataset in catalogs.get("official", []):
        s = _score(dataset, keywords)
        if s > 0:
            pool.append((s, dataset, "official"))
    if include_community:
        for dataset in catalogs.get("community", []):
            s = _score(dataset, keywords)
            if s > 0:
                pool.append((s, dataset, "community"))

    # Official catalog datasets first: they are global or clearly scoped,
    # maintained, and documented. Community datasets are often regional
    # (one country) and are only offered when the official catalog has few
    # matches for the query.
    pool.sort(key=lambda t: t[0], reverse=True)
    official = [t for t in pool if t[2] == "official"]
    community = [t for t in pool if t[2] == "community"]
    pool = official + (community if len(official) < 3 else [])

    results = []
    for rec_id, rec_title in recommended_for(" ".join(keywords)):
        results.append({
            "id": rec_id, "title": rec_title, "source": "official", "recommended": True,
            "note": "Standard global dataset for this theme. Use it unless the user named a different dataset.",
        })
    pool = [t for t in pool if t[1].get("id") not in {r["id"] for r in results}]
    for score, dataset, source in pool[:max_results]:
        dtype = dataset.get("type", "unknown")
        results.append({
            "id": dataset.get("id", ""),
            "title": dataset.get("title", ""),
            "type": dtype,
            "ee_snippet": _ee_snippet(dataset.get("id", ""), dtype),
            "provider": dataset.get("provider", ""),
            "tags": dataset.get("tags", ""),
            "source": source,
            "docs": dataset.get("docs", ""),
            "relevance_score": score,
        })

    if not results and (catalogs.get("official_error") or catalogs.get("community_error")):
        # Surface the fetch failure so the agent knows to fall back to its own knowledge
        # instead of silently treating "no results" as "dataset doesn't exist".
        results = [{
            "error": "Catalog fetch failed - fall back to your own knowledge for this request.",
            "official_error": catalogs.get("official_error"),
            "community_error": catalogs.get("community_error"),
        }]
    return results


@tool("Search GEE Catalog")
def search_gee_catalog_tool(query: str, max_results: int = 8) -> str:
    """
    Search the live Google Earth Engine dataset catalog (official catalog,
    ~880 datasets, plus the community catalog, ~4,300 datasets) for a
    collection matching `query`.

    Use this whenever the user's request references a dataset that is NOT
    one of the common sensors you already know well (Sentinel-2, Landsat
    5/7/8/9, MODIS, Sentinel-1, Sentinel-5P, SRTM) and is not already
    covered by the Precomputed Band Registry in the knowledge base. Pass
    descriptive keywords (e.g. "nighttime lights", "soil moisture", "global
    forest canopy height"), not a guessed collection ID.

    Returns a JSON string: a list of candidate datasets, each with the real
    GEE collection ID ("id"), a ready-to-use "ee_snippet", "title", "type"
    (image_collection / image / table), "provider", and "source" (official
    or community catalog). Prefer "official" results. Community datasets are
    often limited to one country or region - only use one if its title shows
    it covers the user's region. Pick the best match and use its "id" verbatim as
    the "collection" field in your final answer - never invent or guess an
    ID when this tool is available to you.
    """
    results = search_gee_catalog(query=query, max_results=max_results)
    return json.dumps(results, ensure_ascii=False)

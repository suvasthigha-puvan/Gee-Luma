"""
app.py
------
Gee-Luma – GEE Map Studio
Main Streamlit entry point.

Run with:
    streamlit run app.py
"""

# ====================== COMPATIBILITY SHIMS ======================
import warnings
from utils import _make_warn_skip_file_prefixes_compatible, ascii_label
warnings.warn = _make_warn_skip_file_prefixes_compatible(warnings.warn)

# ====================== STDLIB / THIRD-PARTY IMPORTS ======================
import os
import json
import io
import time
import requests
import re
import unicodedata
from pathlib import Path
from dotenv import load_dotenv
import textwrap
from crewai import Agent, Task, Crew, LLM
from catalog_search import search_gee_catalog_tool

try:
    from pyproj import Transformer, CRS
    PYPROJ_AVAILABLE = True
except ImportError:
    PYPROJ_AVAILABLE = False

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import matplotlib.colorbar as mcolorbar
import matplotlib.gridspec as mgridspec
import matplotlib.ticker as mticker
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import cartopy.crs as ccrs
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
from PIL import Image
import streamlit as st
import ee

matplotlib.rcParams.update({"font.family": "DejaVu Sans"})

try:
    import spyndex
    SPYNDEX_AVAILABLE = True
except ImportError:
    SPYNDEX_AVAILABLE = False
    
from pathlib import Path

KNOWLEDGE_BASE = Path("knowledge_base.md").read_text(
    encoding="utf-8"
)
# ====================== LOCAL MODULE IMPORTS ======================
from styles import (
    inject_css, SIDEBAR_WORDMARK, GUIDANCE_HTML,
    section_label, metric_card,
)
from cloud_masking import (
    CLOUD_MASK_FUNCTIONS, user_wants_cloud_removal,
    mask_s2_clouds, mask_s2_toa_clouds, mask_landsat_c2_clouds,
    mask_modis_clouds, mask_viirs_clouds,
)
from dataset_config import (
    COLLECTION_ALIASES, LULC_CLASS_SCHEMAS, DATASET_BAND_MAP,
    detect_lulc_class_filter, apply_lulc_class_filter,
    build_lulc_class_legend, full_lulc_legend, generic_discrete_legend,
    lulc_classes_for_display, lulc_vis_for_classes,
    introspect_collection, get_dataset_band_map,
    get_scale_config, resolve_is_static, detect_cloud_prop,
    is_sar_collection, auto_vis_params,
)
from palettes import INDEX_PALETTES, PRECOMPUTED_PALETTE_MAP, get_palette
from map_engine import compute_spyndex_on_gee, compute_special_map
from cartography import render_cartographic_figure, _dynamic_scale_ticks
from thumbnail import fetch_thumbnail_with_retry
from geojson_helpers import (
    _ensure_wgs84, geojson_to_ee_geometry,
    get_geojson_bounds, get_geojson_label,
)
from boundary_agent import BoundaryAgent

# ====================== PAGE CONFIG ======================
_page_icon_path = Path("icon.png")
PAGE_ICON = str(_page_icon_path) if _page_icon_path.exists() else "🛰️"

st.set_page_config(
    page_title="Gee-Luma",
    page_icon=PAGE_ICON,
    layout="wide"
)

inject_css()

# ====================== GEE AUTH ======================
if "ee_initialized" not in st.session_state:
    try:
        ee.Initialize(project='ee-suvasthigha')
        st.session_state.ee_initialized = True
    except Exception as e:
        st.error(f"GEE Error: {e}")
        st.stop()

# ====================== OPENAI SETUP ======================
load_dotenv()

if "crew_ready" not in st.session_state:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        api_key = st.text_input("Enter your OpenAI API Key", type="password")
    if api_key:
        st.session_state.llm = LLM(model="openai/gpt-4o-mini", api_key=api_key, temperature=0.2)
        st.session_state.crew_ready = True

# ====================== SIDEBAR ======================
st.sidebar.markdown(SIDEBAR_WORDMARK, unsafe_allow_html=True)

palette_presets = {
    "Auto (index-based)": None,
    "NDVI Green":  ['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],
    "Viridis":     ['#440154','#3E4A89','#26828E','#35B779','#FDE725'],
    "Hot":         ['#000000','#8B0000','#FF0000','#FF8C00','#FFFF00','#FFFFFF'],
    "Blues":       ['#FFFFFF','#C6DBEF','#6BAED6','#2171B5','#084594'],
    "Spectral":    ['#9E0142','#D53E4F','#FDAE61','#FEE08B','#E6F598','#3288BD','#5E4FA2'],
}
selected_palette = st.sidebar.selectbox("Color Palette Override", list(palette_presets.keys()))

st.sidebar.markdown("---")
uploaded_geojson_file = st.sidebar.file_uploader(
    "Upload region as GeoJSON",
    type=["json", "geojson"],
    help=(
        "Upload a GeoJSON file exported from any shapefile. "
        "Supports FeatureCollection, Feature, or Geometry types. "
        "Any coordinate system is accepted — the app will reproject to WGS-84 automatically "
        "(requires pyproj). Single or multiple polygons are both supported."
    ),
)

# Parse and validate the uploaded file
uploaded_region_geojson  = None   # reprojected WGS-84 dict
uploaded_region_label    = None   # display name
uploaded_region_error    = None   # error string if parse fails

if uploaded_geojson_file is not None:
    try:
        raw_geojson = json.loads(uploaded_geojson_file.read())
        wgs84_geojson = _ensure_wgs84(raw_geojson)
        uploaded_region_geojson = wgs84_geojson
        uploaded_region_label   = get_geojson_label(wgs84_geojson)
        bounds_preview          = get_geojson_bounds(wgs84_geojson)

        st.sidebar.success(f"Loaded: {ascii_label(uploaded_region_label)}")
        if bounds_preview:
            st.sidebar.caption(
                f"{bounds_preview['lon_min']:.3f}°E – {bounds_preview['lon_max']:.3f}°E  ·  "
                f"{bounds_preview['lat_min']:.3f}°N – {bounds_preview['lat_max']:.3f}°N"
            )
        n_features = (len(wgs84_geojson.get("features", []))
                      if wgs84_geojson.get("type") == "FeatureCollection" else 1)
        st.sidebar.caption(f"{n_features} polygon{'s' if n_features != 1 else ''}  ·  WGS-84")

        if st.sidebar.button("✕ Remove region", use_container_width=True):
            uploaded_region_geojson = None
            uploaded_region_label   = None
            st.rerun()

    except Exception as exc:
        uploaded_region_error = str(exc)
        st.sidebar.error(f"Parse error: {exc}")

if uploaded_region_geojson is not None:
    st.sidebar.info("Region active — geometry overrides the place name in your query.")

st.sidebar.markdown("---")

if SPYNDEX_AVAILABLE:
    n_indices = len(spyndex.indices)
    st.sidebar.success(f"spyndex · {n_indices} indices ready")
    with st.sidebar.expander("Browse spectral indices"):
        domain_filter = st.selectbox("Filter by domain",
            ["all","vegetation","water","burn","snow","soil","urban","radar","kernel"])
        for name, idx in spyndex.indices.items():
            if domain_filter == "all" or idx.application_domain == domain_filter:
                st.markdown(f"**{name}** — {idx.long_name}  \n`{idx.formula}`")
                st.markdown("---")
else:
    st.sidebar.warning("spyndex not installed. Run: pip install spyndex")

# ====================== MISSION INPUT ======================
st.markdown(section_label("Mission Parameters"), unsafe_allow_html=True)

user_prompt = st.text_area(
    "Describe your Earth observation mission:",
    placeholder=(
        "Examples:\n"
        "- NDVI map for Sri Lanka using Sentinel-2, last 3 months, with cloud removal\n"
        "- kNDVI (kernel NDVI) for the Amazon rainforest 2023, cloud-free\n"
        "- BAIS2 burned area index over Australia 2020 wildfire season\n"
        "- True-color RGB composite of Tokyo using Sentinel-2, mask clouds\n"
        "- Land surface temperature over India summer 2024 using MODIS\n"
        "- Nighttime lights in Southeast Asia 2023\n"
        "- Sentinel-1 SAR VV/VH RGB composite over Bangladesh flood 2022\n"
        "- SRTM elevation map of Nepal with hillshade\n"
        "- NO2 air pollution over Europe using Sentinel-5P\n"
        "- MNDWI water index for the Nile Delta, max 15% cloud cover\n"
        "- Evapotranspiration over India 2023 using MODIS MOD16A2GF\n"
        "- VIIRS EVI2 for West Africa 2024"
    ),
    height=140,
)

with st.expander("Query syntax reference"):
    st.markdown(GUIDANCE_HTML, unsafe_allow_html=True)

map_title_override = st.text_input(
    "Custom map title (optional):",
    placeholder="e.g. Jaffna District Cropland 2021 — leave blank to auto-generate",
    help=(
        "Override the auto-generated map title shown on the exported PNG. "
        "If left blank the title is built from the index name, region, and date range."
    ),
)

col1, col2 = st.columns([1, 4])
with col1:
    generate = st.button("GENERATE MAP", type="primary", use_container_width=True)

# ====================== MAIN GENERATION LOGIC ======================
if generate and user_prompt and "llm" in st.session_state:

    apply_cloud_removal = user_wants_cloud_removal(user_prompt)

    spyndex_index_summary = ""
    if SPYNDEX_AVAILABLE:
        lines = [f"  {name}: {idx.long_name} [{idx.application_domain}] bands={list(idx.bands)}"
                 for name, idx in list(spyndex.indices.items())[:80]]
        spyndex_index_summary = "SPYNDEX INDICES (first 80 of {}):\n".format(len(spyndex.indices)) + "\n".join(lines)

    with st.spinner("AI agent is analysing your request..."):

        agent = Agent(
            role="Senior Remote Sensing & GEE Specialist",
            goal="Parse user request and return the exact GEE collection ID, map type, index, and all band/scale metadata",
            backstory=(
                "You are an expert in Google Earth Engine. You know the common sensors "
                "(Sentinel-2, Landsat 5/7/8/9, MODIS, Sentinel-1, Sentinel-5P, SRTM) cold, "
                "including their collection IDs, band names, and scale conventions. You are "
                "also an expert user of the spyndex library. For anything outside those common "
                "sensors - unusual sensors, thematic products, or datasets you are not fully "
                "confident about - you ALWAYS call the search_gee_catalog tool to look up the "
                "real collection ID rather than guessing one from memory. Once you have a "
                "collection ID (from your own knowledge or from the tool), you provide the "
                "relevant band names via band_override, the correct scale_factor and "
                "scale_offset, and set is_temporal appropriately."
            ),
            tools=[search_gee_catalog_tool],
            llm=st.session_state.llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=f"""
User request: "{user_prompt}"
{"" if uploaded_region_geojson is None else f'NOTE: The user has uploaded a custom region shapefile named "{uploaded_region_label}". Use this as the "region" field value in your JSON response. The geometry will be applied automatically  you do NOT need to know its coordinates.'}

=== KNOWLEDGE BASE ===
{KNOWLEDGE_BASE}

=== SPYNDEX INDEX CATALOGUE (use for any spectral index request) ===
{spyndex_index_summary}

Return ONLY valid JSON. No markdown, no explanation, no extra text.

Required fields:
- "collection": exact GEE collection ID. You may use ANY valid GEE public collection, not only those listed in the knowledge base.
- "index": spyndex short name (e.g. "NDVI", "kNDVI")  empty string "" if not a spyndex index
- "map_type": one of PRECOMPUTED | SPYNDEX | RGB | FALSE_COLOR | SWIR | SAR_RGB | ELEVATION | SLOPE | ASPECT | HILLSHADE | LANDCOVER | LST | NIGHTLIGHTS | PRECIPITATION | TEMPERATURE | WATER | SOIL_MOISTURE | TREECOVER | FOREST_LOSS | BIOMASS | CANOPY_HEIGHT | FIRE | NO2 | CO | AEROSOL | CH4 | SO2 | POPULATION | ET | PET
- "precomputed_band": GEE band name to select directly when map_type is PRECOMPUTED; empty string otherwise
- "precomputed_scale": numeric scale factor for the precomputed band; use 1.0 if no scaling needed
- "region": country or place name
- "date_start": YYYY-MM-DD
- "date_end": YYYY-MM-DD
- "cloud_cover": integer 0-100 (default 85; irrelevant for SAR/DEM/static datasets)
- "band_override": dict mapping spyndex variable letters OR role names to actual GEE band names.
  For SPYNDEX: include variable  band (e.g. {{"N":"B8","R":"B4","G":"B3","B":"B2"}})
  For RGB/FALSE_COLOR/SWIR: include role  band (e.g. {{"red":"B4","green":"B3","blue":"B2","nir":"B8","swir1":"B11","swir2":"B12"}})
  For SAR_RGB: include {{"vv":"VV","vh":"VH"}}
  For known collections in the knowledge base, this may be empty {{}}
  For ANY unlisted or non-standard collection, this MUST be populated with correct band names
- "is_temporal": true if the collection is time-varying, false if static (DEMs, land cover, etc.)
- "scale_factor": reflectance scale factor (e.g. 0.0001 for S2/MODIS SR, 0.0000275 for Landsat C2, 1.0 for SAR/derived)
- "scale_offset": offset added after scale_factor multiplication (-0.2 for Landsat C2 SR, 0.0 otherwise)
- "notes": one sentence  state whether precomputed band or spyndex was used and why. For unlisted collections, explain band mapping.

DECISION RULES (apply in order):
1. PRECOMPUTED-FIRST: If the variable/index is already a band in the chosen collection (see Section 3):
    map_type="PRECOMPUTED", precomputed_band=<band>, precomputed_scale=<scale>, index=""
2. SPYNDEX fallback: If no precomputed band but spyndex supports the index and raw bands are available:
    map_type="SPYNDEX", index=<name>, band_override={{spyndex_var: gee_band, ...}}
3. RGB/composite  map_type RGB/FALSE_COLOR/SWIR with band_override={{role: band, ...}}
4. SAR  SAR_RGB with band_override={{vv: ..., vh: ...}}
5. Terrain  ELEVATION/SLOPE/ASPECT/HILLSHADE
6. ET without specified dataset  MODIS/061/MOD16A2GF, precomputed ET band
7. Historical before 2014  do NOT use Sentinel-2
8. Tropical/cloudy  prefer MODIS (precomputed) or Landsat over Sentinel-2
9. Static datasets  is_temporal=false

UNLISTED COLLECTION RULE: If the user's dataset is not a common sensor you already know well
and is not in the Precomputed Band Registry, call the search_gee_catalog tool with descriptive
keywords BEFORE writing your final answer, and use the returned "id" verbatim as "collection".
Do not guess a collection ID from memory when the tool is available. Once you have a collection
ID (from your own knowledge or from the tool), you MUST still provide correct band names in
band_override, correct scale_factor/scale_offset, and is_temporal. If the tool call fails or
returns nothing useful, fall back to your best-effort knowledge rather than blocking the request.

Examples:

NDVI via MODIS (precomputed):
{{"collection":"MODIS/061/MOD13Q1","index":"","map_type":"PRECOMPUTED","precomputed_band":"NDVI","precomputed_scale":0.0001,"region":"Sri Lanka","date_start":"2024-01-01","date_end":"2024-03-31","cloud_cover":85,"band_override":{{}},"is_temporal":true,"scale_factor":0.0001,"scale_offset":0.0,"notes":"MOD13Q1 has precomputed NDVI; used directly."}}

NDVI via Sentinel-2 (spyndex):
{{"collection":"COPERNICUS/S2_SR_HARMONIZED","index":"NDVI","map_type":"SPYNDEX","precomputed_band":"","precomputed_scale":1.0,"region":"Germany","date_start":"2024-06-01","date_end":"2024-08-31","cloud_cover":20,"band_override":{{"N":"B8","R":"B4"}},"is_temporal":true,"scale_factor":0.0001,"scale_offset":0.0,"notes":"Sentinel-2 has no precomputed NDVI; computing via spyndex."}}

ET via MODIS (precomputed):
{{"collection":"MODIS/061/MOD16A2GF","index":"","map_type":"PRECOMPUTED","precomputed_band":"ET","precomputed_scale":0.1,"region":"India","date_start":"2024-01-01","date_end":"2024-12-31","cloud_cover":85,"band_override":{{}},"is_temporal":true,"scale_factor":1.0,"scale_offset":0.0,"notes":"MOD16A2GF provides precomputed ET."}}

RGB Sentinel-2:
{{"collection":"COPERNICUS/S2_SR_HARMONIZED","index":"","map_type":"RGB","precomputed_band":"","precomputed_scale":1.0,"region":"Tokyo","date_start":"2024-03-01","date_end":"2024-04-01","cloud_cover":20,"band_override":{{"red":"B4","green":"B3","blue":"B2","nir":"B8","swir1":"B11","swir2":"B12"}},"is_temporal":true,"scale_factor":0.0001,"scale_offset":0.0,"notes":"Sentinel-2 true-color composite."}}
""",
            agent=agent,
            expected_output="Valid JSON only",
        )

        crew   = Crew(agents=[agent], tasks=[task], verbose=False, process="sequential")
        result = crew.kickoff()

    try:
        raw = result.raw.strip()
        if "```" in raw:
            raw = raw.split("```")[1].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        params = json.loads(raw)
    except Exception:
        st.warning("Could not parse agent output - using NDVI fallback.")
        params = {
            "collection": "MODIS/061/MOD13Q1", "index": "",
            "map_type": "PRECOMPUTED", "precomputed_band": "NDVI",
            "precomputed_scale": 0.0001, "region": "Sri Lanka",
            "date_start": "2024-01-01", "date_end": "2024-12-31",
            "cloud_cover": 85, "band_override": {}, "is_temporal": True,
            "scale_factor": 0.0001, "scale_offset": 0.0,
            "notes": "Fallback: MODIS precomputed NDVI."
        }

    cid = COLLECTION_ALIASES.get(params.get("collection", ""), params.get("collection", "MODIS/061/MOD13Q1"))
    params["collection"] = cid

    with st.expander("Agent Decision", expanded=False):
        st.caption(params.get("notes", ""))
        if apply_cloud_removal:
            st.info("Cloud removal is enabled for this request.")
        st.json(params)

    try:
        region_name       = params.get("region", "Sri Lanka").strip().title()
        index_name        = params.get("index", "").upper()
        map_type          = params.get("map_type", "SPYNDEX").upper()
        date_start        = params.get("date_start", "2024-01-01")
        date_end          = params.get("date_end",   "2024-12-31")
        cloud_cover       = int(params.get("cloud_cover", 85))
        band_override     = params.get("band_override", {}) or {}
        agent_scale_f     = float(params.get("scale_factor", 1.0))
        agent_scale_o     = float(params.get("scale_offset", 0.0))
        agent_is_temporal = bool(params.get("is_temporal", True))

        if uploaded_region_geojson is not None:
            display_region_name = uploaded_region_label or region_name
            status_region = st.status(f"Using uploaded region: **{ascii_label(display_region_name)}**", expanded=True)
            try:
                region_geom = geojson_to_ee_geometry(uploaded_region_geojson)
                region_name = display_region_name
                status_region.update(
                    label=f"Custom region loaded: {ascii_label(region_name)}", state="complete"
                )
            except Exception as e:
                status_region.update(
                    label=f"Could not use uploaded region ({e}) - resolving '{ascii_label(region_name)}' instead",
                    state="error",
                )
                # Couldn't use the upload after all - fall through to name-based
                # resolution below instead of leaving region_geom undefined.
                uploaded_region_geojson = None
                region_geom = None

        if uploaded_region_geojson is None:
            status_region = st.status(f"Resolving boundary for **{ascii_label(region_name)}**", expanded=True)
            try:
                admin_level, admin_type = BoundaryAgent.detect_admin_level(region_name)
                geom_dict = BoundaryAgent.fetch_boundary(region_name, country_name="Sri Lanka", admin_level=admin_level)
                if geom_dict is None:
                    raise ValueError(
                        f"No boundary found for '{region_name}' in the geoBoundaries dataset."
                    )
                region_geom = ee.Geometry(geom_dict)
                status_region.update(
                    label=f"Region resolved: {ascii_label(region_name)} ({admin_type})", state="complete"
                )
            except Exception as e:
                status_region.update(label=f"Could not resolve '{ascii_label(region_name)}'", state="error")
                st.error(
                    f"Could not automatically find a boundary for **{ascii_label(region_name)}**. "
                    f"({e})\n\n"
                    "Try naming a country, province, or district, or upload a custom AOI "
                    "(GeoJSON) in the sidebar instead."
                )
                st.stop()

        try:
            bounds     = region_geom.bounds().getInfo()
            coords     = bounds["coordinates"][0]
            all_lons   = [c[0] for c in coords]
            all_lats   = [c[1] for c in coords]
            geo_bounds = {
                "lon_min": min(all_lons), "lon_max": max(all_lons),
                "lat_min": min(all_lats), "lat_max": max(all_lats),
            }
        except Exception:
            geo_bounds = None

        status_intro = st.status(f"Inspecting dataset `{cid}`", expanded=False)
        col_info = introspect_collection(cid)
        if col_info["error"]:
            st.warning(f"Dataset introspection warning: {col_info['error']}")
        n_bands = len(col_info["bands"])
        status_intro.update(
            label=f"Dataset: {n_bands} band{'s' if n_bands != 1 else ''} detected" + (" (static)" if col_info["is_static"] else ""),
            state="complete"
        )

        # Show detected bands for unknown/unlisted collections
        if cid not in DATASET_BAND_MAP and col_info["bands"]:
            with st.expander(f"Detected bands in `{cid}`"):
                st.write(col_info["bands"])

        is_static  = resolve_is_static(cid, col_info, agent_is_temporal)
        cloud_prop = detect_cloud_prop(cid, col_info)
        band_map   = get_dataset_band_map(cid, band_override, col_info)
        scale_cfg  = get_scale_config(cid, agent_scale_f, agent_scale_o)

        lulc_class_values: list[int] = []
        requested_lulc = (
            map_type == "LANDCOVER"
            or PRECOMPUTED_PALETTE_MAP.get(str(params.get("precomputed_band", "")), "").upper() == "LANDCOVER"
        )
        if requested_lulc:
            lulc_class_values = detect_lulc_class_filter(user_prompt, cid)
            if lulc_class_values:
                filtered_labels = [
                    LULC_CLASS_SCHEMAS.get(cid, {}).get(v, {}).get("label", str(v))
                    for v in lulc_class_values
                ]
                st.info(f"Filtering LULC to class(es): **{', '.join(filtered_labels)}** "
                        f"(values: {lulc_class_values})")

        cloud_mask_fn         = CLOUD_MASK_FUNCTIONS.get(cid)
        cloud_removal_applied = apply_cloud_removal and (cloud_mask_fn is not None) and (not is_static)

        status_col = st.status(f"Loading dataset `{cid}`", expanded=True)

        if is_static:
            try:
                if col_info["is_image_collection"]:
                    img = ee.ImageCollection(cid).filterBounds(region_geom).mosaic()
                else:
                    img = ee.Image(cid)
            except Exception:
                img = ee.Image(cid)
            n_images = 1
            if apply_cloud_removal:
                st.info("Cloud removal is not applicable to static datasets - skipped.")
        else:
            col = (ee.ImageCollection(cid)
                   .filterDate(date_start, date_end)
                   .filterBounds(region_geom))
            if cloud_prop:
                col = col.filter(ee.Filter.lt(cloud_prop, cloud_cover))
            if "S1_GRD" in cid:
                col = col.filter(ee.Filter.eq("instrumentMode", "IW"))

            if apply_cloud_removal and cloud_mask_fn is None:
                st.warning(
                    f"Pixel-level cloud masking is not available for `{cid}`. "
                    "Cloud filtering by scene percentage is still applied."
                )
            if cloud_removal_applied:
                status_col.update(label=f"Applying pixel-level cloud mask for `{cid}`")
                col = col.map(cloud_mask_fn)

            n_images = col.size().getInfo()
            if n_images == 0:
                st.error(
                    f"**No usable imagery found** for **{ascii_label(region_name)}** "
                    f"between {date_start} and {date_end}."
                )
                if apply_cloud_removal:
                    st.warning(
                        "This may be because cloud removal filtered out all scenes.\n"
                        "- Expand the date range (e.g. 6-12 months)\n"
                        "- Increase the cloud cover threshold in your query\n"
                        "- Remove the cloud removal request\n"
                        "- Switch to MODIS for more frequent coverage"
                    )
                else:
                    st.warning("Try expanding the date range or raising the cloud cover threshold.")
                st.stop()
            img = col.median()

        status_col.update(
            label=(f"Dataset loaded ({n_images} image{'s' if n_images != 1 else ''})"
                   + (" - Cloud masked" if cloud_removal_applied else "")),
            state="complete"
        )

        status_compute = st.status(f"Computing **{map_type}** ({index_name or 'none'})", expanded=True)

        if map_type == "PRECOMPUTED":
            precomputed_band  = params.get("precomputed_band", "")
            precomputed_scale = float(params.get("precomputed_scale", 1.0))
            if not precomputed_band:
                # Fall back to first available band
                precomputed_band = col_info["bands"][0] if col_info["bands"] else ""
                if precomputed_band:
                    st.info(f"No precomputed_band specified - using first band: `{precomputed_band}`")
            if not precomputed_band:
                st.warning("No band to display for PRECOMPUTED mode.")
                st.stop()
            result_img = img.select(precomputed_band)
            if precomputed_scale != 1.0:
                result_img = result_img.multiply(precomputed_scale)
            result_img = result_img.rename(precomputed_band)
            palette_key = PRECOMPUTED_PALETTE_MAP.get(precomputed_band, precomputed_band.upper())
            if palette_key == "LANDCOVER" and cid in LULC_CLASS_SCHEMAS:
                lulc_class_values = lulc_classes_for_display(cid, lulc_class_values)
                result_img = result_img.remap(
                    lulc_class_values,
                    list(range(len(lulc_class_values)))
                ).rename("LANDCOVER")
                vis_params = lulc_vis_for_classes(cid, lulc_class_values)
                precomputed_band = "LANDCOVER"
            else:
                vis_params = get_palette(palette_key)
            # For bands not in any known palette, auto-range from data
            if palette_key not in INDEX_PALETTES and palette_key != "LANDCOVER":
                auto = auto_vis_params(result_img, precomputed_band, region_geom)
                vis_params = {**INDEX_PALETTES["SPYNDEX_GENERIC"],
                              "min": auto["min"], "max": auto["max"],
                              "label": precomputed_band}
            vis_params_gee = {k: v for k, v in vis_params.items() if k != "label"}
            display_label  = vis_params.get("label", precomputed_band)
            final_img      = result_img.clip(region_geom)
            map_label      = precomputed_band

        elif map_type == "SPYNDEX" and index_name:
            result_img = compute_spyndex_on_gee(
                img, cid, index_name, band_map, scale_cfg,
                band_override=band_override or None
            )
            if result_img is None:
                available = col_info.get("bands", [])
                st.warning(
                    f"Spyndex could not compute **{index_name}** for `{cid}`.\n"
                    f"Available bands: `{available}`\n"
                    "Check that the dataset has all required spectral bands."
                )
                st.stop()
            vis_params     = get_palette(index_name)
            vis_params_gee = {k: v for k, v in vis_params.items() if k != "label"}
            display_label  = vis_params.get("label", index_name)
            final_img      = result_img.clip(region_geom)
            map_label      = index_name

        else:
            result_img, vis_params_raw = compute_special_map(
                img, map_type, cid, band_map, scale_cfg,
                lulc_class_values=lulc_class_values if map_type == "LANDCOVER" else None,
            )
            display_label  = INDEX_PALETTES.get(map_type, {}).get("label", map_type)
            vis_params_gee = {k: v for k, v in vis_params_raw.items() if k != "label"}
            final_img      = result_img.clip(region_geom)
            map_label      = map_type

        # Apply sidebar palette override
        palette_override = palette_presets.get(selected_palette)
        if palette_override and "palette" in vis_params_gee:
            vis_params_gee["palette"] = palette_override

        status_compute.update(label=f"{map_type} computed", state="complete")

        status_thumb = st.status("Fetching map thumbnail", expanded=True)
        map_pil, final_dim = fetch_thumbnail_with_retry(final_img, vis_params_gee, region_geom)
        status_thumb.update(label=f"Thumbnail fetched at {final_dim}px", state="complete")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(metric_card(ascii_label(map_label), "Map Index", accent=True), unsafe_allow_html=True)
        with m2:
            st.markdown(metric_card(ascii_label(region_name), "Region"), unsafe_allow_html=True)
        with m3:
            st.markdown(metric_card(str(n_images), "Scenes"), unsafe_allow_html=True)
        with m4:
            if cloud_removal_applied:
                engine_lbl = "Cloud masked"
            elif apply_cloud_removal and not cloud_removal_applied:
                engine_lbl = "Cloud filtered"
            elif map_type == "PRECOMPUTED":
                engine_lbl = "Precomputed"
            elif map_type == "SPYNDEX":
                engine_lbl = "Spyndex"
            else:
                engine_lbl = "Built-in"
            st.markdown(metric_card(engine_lbl, "Engine"), unsafe_allow_html=True)

        status_render = st.status("Rendering cartographic layout", expanded=True)
        is_rgb = "bands" in vis_params_gee and len(vis_params_gee["bands"]) == 3

        # Build discrete LULC legend for the panel
        lulc_legend: list | None = None
        is_lulc_output = (
            map_type == "LANDCOVER"
            or map_label == "LANDCOVER"
            or PRECOMPUTED_PALETTE_MAP.get(str(map_label), "").upper() == "LANDCOVER"
        )
        if is_lulc_output:
            if lulc_class_values:
                lulc_legend = build_lulc_class_legend(cid, lulc_class_values)
            else:
                lulc_legend = full_lulc_legend(cid) or None
            if not lulc_legend:
                # cid has no hardcoded class scheme in LULC_CLASS_SCHEMAS (e.g. a
                # land-cover dataset found via the live catalog search rather than
                # one of our registered ones). Build a discrete legend from the
                # actual class values present in the AOI instead of silently
                # falling back to a misleading continuous colorbar on categorical
                # data.
                lulc_legend = generic_discrete_legend(
                    final_img, map_label, region_geom,
                    vis_params_gee.get("palette", []),
                    vis_params_gee.get("min", 0), vis_params_gee.get("max", 100),
                ) or None
                if lulc_legend:
                    st.caption(
                        f"`{cid}` isn't in the app's known LULC class registry - "
                        "showing a generic per-value legend built from the classes "
                        "actually present in this map."
                    )

        png_bytes = render_cartographic_figure(
            map_pil_image         = map_pil,
            region_name           = region_name,
            map_label             = map_label,
            date_start            = date_start,
            date_end              = date_end,
            vis_params_gee        = vis_params_gee,
            display_label         = display_label,
            is_rgb                = is_rgb,
            geo_bounds            = geo_bounds,
            cloud_removal_applied = cloud_removal_applied,
            lulc_legend           = lulc_legend,
            region_geom           = region_geom,
            uploaded_geojson      = uploaded_region_geojson,
            custom_title          = map_title_override.strip() or None,
        )
        status_render.update(label="Cartographic layout rendered", state="complete")

        st.markdown(section_label("Map Output"), unsafe_allow_html=True)
        st.image(png_bytes, use_column_width=True,
                 caption=f"{ascii_label(map_label)} - {ascii_label(region_name)} - {cid}"
                         + (" - Cloud masked" if cloud_removal_applied else ""))
        st.success("Map generated successfully"
                   + (" with pixel-level cloud masking applied." if cloud_removal_applied else "."))

        suffix = "_cloudmasked" if cloud_removal_applied else ""
        fname  = f"{ascii_label(map_label)}_{ascii_label(region_name).replace(' ','_')}_{date_start[:4]}{suffix}.png"
        st.download_button(label="Download Map PNG", data=png_bytes,
                           file_name=fname, mime="image/png")

        if map_type == "SPYNDEX" and SPYNDEX_AVAILABLE and index_name in spyndex.indices:
            idx_info = spyndex.indices[index_name]
            with st.expander(f"About {index_name} - {idx_info.long_name}"):
                st.markdown(f"**Formula:** `{idx_info.formula}`")
                st.markdown(f"**Domain:** {idx_info.application_domain}")
                st.markdown(f"**Required bands:** {', '.join(idx_info.bands)}")
                st.markdown(f"**Reference:** {idx_info.reference}")
                if col_info["bands"]:
                    st.markdown(f"**Available bands in `{cid}`:** `{', '.join(col_info['bands'])}`")
                if band_override:
                    st.markdown(f"**Band mapping used:** `{band_override}`")

        if cloud_removal_applied:
            with st.expander("Cloud Removal Details"):
                fn_name = cloud_mask_fn.__name__
                desc_map = {
                    "mask_s2_clouds":        "Sentinel-2 SR - QA60 bitmask (bits 10 and 11: opaque and cirrus clouds)",
                    "mask_s2_toa_clouds":    "Sentinel-2 TOA - QA60 bitmask (bits 10 and 11: opaque and cirrus clouds)",
                    "mask_landsat_c2_clouds":"Landsat Collection 2 - QA_PIXEL bitmask (bit 3: cloud, bit 4: cloud shadow)",
                    "mask_modis_clouds":     "MODIS MOD09GA - state_1km QA band (bits 0-1: cloud state = clear)",
                    "mask_viirs_clouds":     "VIIRS VNP09GA - QF1 quality flag (bits 2-3: confident/probably clear)",
                }
                st.markdown(f"**Method:** {desc_map.get(fn_name, fn_name)}")
                st.markdown(f"**Dataset:** `{cid}`")
                st.markdown(
                    "Pixel-level cloud masking was applied before computing the median composite. "
                    "Masked pixels are excluded from index computation."
                )

    except Exception as e:
        st.error(f"Map generation failed: {e}")
        st.info(
            "Tips:\n"
            "- Cloudy tropical regions - prefer MODIS or Landsat over Sentinel-2\n"
            "- Check that spyndex is installed: pip install spyndex\n"
            "- Try expanding the date range for more images\n"
            "- Some indices require bands not present in every dataset\n"
            "- If cloud removal left no valid pixels, try a longer date range\n"
            "- For unlisted datasets, verify the collection ID in the GEE catalog"
        )

elif generate and "llm" not in st.session_state:
    st.warning("Please enter your OpenAI API key first.")

# ====================== FOOTER ======================
spyndex_count = len(spyndex.indices) if SPYNDEX_AVAILABLE else 0
st.markdown(f"""
<div style="
  margin-top: 48px;
  padding: 20px 0 8px;
  border-top: 1px solid var(--cv-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
">
  <div style="font-family: var(--font-mono, monospace); font-size: 0.62rem; color: var(--cv-muted, #666); letter-spacing: 0.08em;">
    Gee-Luma &nbsp;·&nbsp; Google Earth Engine &nbsp;·&nbsp; CrewAI &nbsp;·&nbsp; spyndex
  </div>
  <div style="font-family: var(--font-mono, monospace); font-size: 0.62rem; color: var(--cv-muted, #666); letter-spacing: 0.08em;">
    {spyndex_count} spectral indices &nbsp;·&nbsp; Multi-sensor remote sensing
  </div>
</div>
""", unsafe_allow_html=True)

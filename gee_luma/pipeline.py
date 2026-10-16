"""
pipeline.py
-----------
The map pipeline, independent of any user interface:

    request text -> agent decision -> region -> dataset -> composite
    -> gap filling -> computation -> statistics -> rendered map + exports

A request for several maps (one per month, season or year, a multi-year
climatology, or named periods to compare) follows the same path with one
composite per map, and ends in a single figure with a shared legend.

`run_pipeline()` reports progress through a small `ui` object, so the same
code drives the Streamlit app (which passes Streamlit itself) and the web
API (which passes a recorder that turns the calls into progress events).

The `ui` object must provide:
    status(label, expanded=...) -> object with .update(label=..., state=...)
    info / warning / error / caption / markdown / json / code
    expander(label, expanded=...) and spinner(text) as context managers
    stop()  - abandon the request; must raise (not return)
"""

# ====================== COMPATIBILITY SHIMS ======================
import warnings
from gee_luma.utils import _make_warn_skip_file_prefixes_compatible, ascii_label
warnings.warn = _make_warn_skip_file_prefixes_compatible(warnings.warn)

# ====================== STDLIB / THIRD-PARTY IMPORTS ======================
import os
import json
import io
import time
import requests
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
import textwrap
from crewai import Agent, Task, Crew, LLM
from gee_luma.catalog_search import search_gee_catalog_tool, recommended_for
from gee_luma.dataset_options import find_dataset_options, AUTO_CHOICE
from gee_luma.request_check import check_request

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
import ee

matplotlib.rcParams.update({"font.family": "DejaVu Sans"})

try:
    import spyndex
    SPYNDEX_AVAILABLE = True
except ImportError:
    SPYNDEX_AVAILABLE = False
    
from pathlib import Path

KNOWLEDGE_BASE = Path(__file__).with_name("knowledge_base.md").read_text(encoding="utf-8")
# ====================== LOCAL MODULE IMPORTS ======================
from gee_luma.cloud_masking import (
    user_wants_cloud_removal, user_declined_cloud_removal,
    cloud_mask_method, apply_cloud_mask,
)
from gee_luma.dataset_config import (
    COLLECTION_ALIASES, LULC_CLASS_SCHEMAS, LULC_BAND_LUT, DATASET_BAND_MAP, DATASET_SENSOR,
    register_stac_classes, register_detected_classes, first_categorical_band, auto_rgb_stretch,
    detect_lulc_class_filter, apply_lulc_class_filter,
    build_lulc_class_legend, full_lulc_legend, generic_discrete_legend,
    lulc_classes_for_display, lulc_vis_for_classes,
    introspect_collection, get_dataset_band_map,
    get_scale_config, resolve_is_static, detect_cloud_prop,
    is_sar_collection, auto_vis_params, shared_vis_range,
)
from gee_luma.palettes import INDEX_PALETTES, PRECOMPUTED_PALETTE_MAP, get_palette
from gee_luma.map_engine import compute_spyndex_on_gee, compute_special_map
from gee_luma.cartography import render_cartographic_figure, render_composite_figure, choose_grid_layout
from gee_luma.projection import choose_map_projection, projected_extent
from gee_luma.stac_metadata import (
    fetch_dataset_metadata, get_dataset_info_tool,
    stac_palette_for_band, band_display_label,
)
from gee_luma.thumbnail import fetch_thumbnail_with_retry, fetch_panel_thumbnails
from gee_luma.geojson_helpers import (
    _ensure_wgs84, geojson_to_ee_geometry,
    get_geojson_bounds, get_geojson_label,
)
from gee_luma.boundary_agent import BoundaryAgent
from gee_luma.map_stats import (
    continuous_stats, class_stats, series_stats, series_class_stats, stats_to_csv, format_value,
)
from gee_luma.units import whole_period, relabel_units
from gee_luma.time_series import (
    CLIMATOLOGIES, MAX_PANELS, normalise_series, infer_series_from_prompt, refine_series, build_panels,
    series_title, series_subtitle, series_processing,
)
from gee_luma.class_legend import (
    is_class_candidate, distinct_values, snap_to_values, shorten_legend, MAX_DETECTED_CLASSES,
)
from gee_luma.exports import geotiff_download, fetch_geotiff
from gee_luma.restyle import prepare_restyle

# Ways to combine the images of a period into one map.
TEMPORAL_REDUCERS = {
    "median": ee.Reducer.median, "mean": ee.Reducer.mean, "sum": ee.Reducer.sum,
    "max": ee.Reducer.max, "min": ee.Reducer.min, "mode": ee.Reducer.mode,
}
# Map types that show one variable of a thematic dataset. When the agent
# names the band, these are drawn straight from it, whatever the dataset.
THEMATIC_MAP_TYPES = {
    "LST", "NIGHTLIGHTS", "PRECIPITATION", "TEMPERATURE", "WATER", "SOIL_MOISTURE",
    "TREECOVER", "FOREST_LOSS", "BIOMASS", "CANOPY_HEIGHT", "FIRE", "NO2", "CO",
    "AEROSOL", "CH4", "SO2", "POPULATION", "ET", "PET",
}
# Palettes whose value range is physically fixed (normalised indices,
# percentages, angles). Everything else is stretched to the data in the region.
FIXED_RANGE_KEYS = {
    "NDVI", "EVI", "EVI2", "SAVI", "GNDVI", "NDRE", "kNDVI", "NDWI", "MNDWI", "NBR", "NBR2",
    "NDSI", "BSI", "NDBI", "RVI", "RFDI", "WATER", "TREECOVER", "FOREST_LOSS", "ASPECT", "HILLSHADE",
}
MAP_TYPE_TITLES = {
    "RGB": "True-colour image", "FALSE_COLOR": "False-colour composite (near infrared)",
    "SWIR": "Shortwave-infrared composite", "SAR_RGB": "Radar backscatter composite",
    "ELEVATION": "Elevation", "SLOPE": "Slope", "ASPECT": "Aspect", "HILLSHADE": "Hillshade",
    "LANDCOVER": "Land cover", "LST": "Land surface temperature", "NIGHTLIGHTS": "Night-time lights",
    "PRECIPITATION": "Precipitation", "TEMPERATURE": "Air temperature",
    "WATER": "Surface water occurrence", "SOIL_MOISTURE": "Soil moisture", "TREECOVER": "Tree cover",
    "FOREST_LOSS": "Forest loss", "BIOMASS": "Above-ground biomass", "CANOPY_HEIGHT": "Canopy height",
    "FIRE": "Active fire", "NO2": "Nitrogen dioxide (NO2)", "CO": "Carbon monoxide (CO)",
    "AEROSOL": "Aerosol index", "CH4": "Methane (CH4)", "SO2": "Sulphur dioxide (SO2)",
    "POPULATION": "Population density", "ET": "Evapotranspiration", "PET": "Potential evapotranspiration",
}
# Words in a band's name or description that identify its theme, so a band
# of any dataset gets the colours conventional for that variable.
THEME_KEYWORDS = [
    ("LST", ("land surface temperature", "lst")),
    ("TEMPERATURE", ("temperature",)),
    ("PRECIPITATION", ("precipitation", "rainfall", "rain")),
    ("ELEVATION", ("elevation", "height above")),
    ("SOIL_MOISTURE", ("soil moisture", "soil water")),
    ("ET", ("evapotranspiration",)),
    ("POPULATION", ("population",)),
    ("NIGHTLIGHTS", ("radiance", "nighttime", "night-time")),
    ("CANOPY_HEIGHT", ("canopy height",)),
    ("BIOMASS", ("biomass",)),
    ("NDVI", ("ndvi", "vegetation index")),
]


def infer_theme(band: str, description: str) -> str | None:
    text = f"{band} {description}".lower().replace("_", " ")
    for key, words in THEME_KEYWORDS:
        if any(w in text for w in words):
            return key
    return None


# Used when the agent does not name a reducer; anything not listed uses median.
DEFAULT_REDUCER_BY_MAP_TYPE = {
    "PRECIPITATION": "sum", "ET": "sum", "PET": "sum",
    "LANDCOVER": "mode", "FIRE": "max",
    "LST": "mean", "TEMPERATURE": "mean", "NIGHTLIGHTS": "mean", "SOIL_MOISTURE": "mean",
    "NO2": "mean", "CO": "mean", "AEROSOL": "mean", "CH4": "mean", "SO2": "mean",
}

def data_coverage_percent(image, band: str, region_geom, scale: float) -> float:
    """Share of the region (0-100) where `band` of `image` has data, i.e. is not masked."""
    valid_m2 = (ee.Image.pixelArea().updateMask(image.select([band]).mask()).rename("area")
                .reduceRegion(reducer=ee.Reducer.sum(), geometry=region_geom, scale=scale,
                              bestEffort=True, maxPixels=1e6).get("area"))
    percent = (ee.Number(ee.Algorithms.If(valid_m2, valid_m2, 0))
               .divide(region_geom.area(maxError=100)).multiply(100).getInfo())
    return float(min(max(percent, 0.0), 100.0))


# Totals per period from images that each cover several days (8-day ET,
# 16-day or monthly sums). Such an image often straddles two periods: counted
# whole in the one it starts in, months would get three or four 8-day images
# by accident of the calendar and their totals would differ for that reason
# alone. Each image is instead divided between the periods by days.

def multi_day_periods(images) -> dict | None:
    """
    {start: end} in milliseconds for the period every image of `images`
    covers, or None when the images cover a day or less each (or do not say).

    An image's stated end is cut back to the start of the next image: the
    last 8-day MODIS image of a year is stamped as running four days into
    January although it holds only the days left in December.
    """
    try:
        first = images.first()
        days = (ee.Number(first.get("system:time_end")).subtract(first.get("system:time_start"))
                .divide(86_400_000).getInfo())
        if not days or days <= 1.5:
            return None
        pairs = images.reduceColumns(
            ee.Reducer.toList(2), ["system:time_start", "system:time_end"]).get("list").getInfo()
    except Exception:
        return None
    ends: dict[int, int] = {}
    for start, end in pairs:
        ends[int(start)] = max(ends.get(int(start), 0), int(end))
    starts = sorted(ends)
    periods = {}
    for i, start in enumerate(starts):
        end = min(ends[start], starts[i + 1]) if i + 1 < len(starts) else ends[start]
        if end > start:
            periods[start] = end
    return periods or None


def prorated_total(images, periods: dict, start_iso: str, end_iso: str, band_names):
    """
    Total over start_iso..end_iso (end exclusive) from multi-day images, each
    counted by the share of its days that fall inside. None if no image does.
    """
    def _ms(iso):
        return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)

    a, b = _ms(start_iso), _ms(end_iso)
    shares = {str(start): (min(end, b) - max(start, a)) / (end - start)
              for start, end in periods.items() if min(end, b) > max(start, a)}
    if not shares:
        return None
    lookup = ee.Dictionary(shares)
    weighted = (images.filter(ee.Filter.inList("system:time_start", [int(k) for k in shares]))
                # Cast: the shares differ, and with them the value range Earth Engine infers.
                .map(lambda im: im.toDouble().multiply(ee.Number(
                    lookup.get(ee.Number(im.get("system:time_start")).toLong().format("%d"))))))
    return weighted.reduce(ee.Reducer.sum()).rename(band_names)


# Gap filling: when cloud leaves holes in the requested period, they are
# filled from imagery of the surrounding dates, nearest first.
GAP_FILL_BELOW_PERCENT = 97      # fill when less of the region than this has data
GAP_FILL_STEPS = 3               # how many times the window may be widened
GAP_FILL_OPT_OUT = ("no gap fill", "without gap fill", "no gap-fill", "don't fill", "do not fill",
                    "no filling", "original only", "unfilled")


def gap_fill_skipped_note(error: Exception) -> str:
    """Why gap filling was skipped, in plain words (Earth Engine's own message goes to the log)."""
    text = str(error).lower()
    if "memory" in text:
        reason = "the region is too large for Earth Engine to work out where the gaps are"
    elif "timed out" in text or "timeout" in text or "deadline" in text:
        reason = "Earth Engine took too long to work out where the gaps are"
    elif "too many" in text or "quota" in text or "rate limit" in text:
        reason = "Earth Engine is busy right now"
    else:
        reason = "Earth Engine could not work out where the gaps are"
    return f"Gap filling was skipped: {reason}. The map shows the requested period only."



PALETTE_PRESETS = {
    "Auto (index-based)": None,
    "NDVI Green":  ['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],
    "Viridis":     ['#440154','#3E4A89','#26828E','#35B779','#FDE725'],
    "Hot":         ['#000000','#8B0000','#FF0000','#FF8C00','#FFFF00','#FFFFFF'],
    "Blues":       ['#FFFFFF','#C6DBEF','#6BAED6','#2171B5','#084594'],
    "Spectral":    ['#9E0142','#D53E4F','#FDAE61','#FEE08B','#E6F598','#3288BD','#5E4FA2'],
}

# Settings come from the .env file only (found by walking up from here), and
# win over environment variables of the same name. They are read at import.
load_dotenv(override=True)
REQUIRED_SETTINGS = ("OPENAI_API_KEY", "EE_PROJECT", "GEE_LUMA_MODEL", "PORT")
EE_PROJECT = os.getenv("EE_PROJECT", "").strip()
LLM_MODEL = os.getenv("GEE_LUMA_MODEL", "").strip()


def missing_settings_message(names=REQUIRED_SETTINGS) -> str | None:
    """None when every named setting is in the .env file; otherwise what to add."""
    missing = [n for n in names if not os.getenv(n, "").strip()]
    if not missing:
        return None
    return f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set. Add to the .env file (see .env.example)."


def create_llm(api_key: str) -> LLM:
    """The language model the agent uses."""
    return LLM(model=LLM_MODEL, api_key=api_key, temperature=0.2)


def render_original_map(job: dict) -> dict:
    """
    Render the original (not gap-filled) map from the job stored with a
    gap-filled result. Returns {"png": bytes, "pdf": bytes}.
    """
    kwargs = job["render_kwargs"]
    image, _size = fetch_thumbnail_with_retry(
        job["image"], job["vis_params"], kwargs["extent"], kwargs["projection"]["crs"],
        target_long_side=job["target_px"])
    return render_cartographic_figure(map_pil_image=image, **kwargs)


def run_pipeline(user_prompt: str, *, llm, ui, uploaded_region_geojson=None, uploaded_region_label=None,
                 map_title_override: str = "", selected_palette: str = "Auto (index-based)",
                 fill_gaps_option: bool = True, dataset: str = ""):
    """
    Turn a plain-language request into a finished map.

    Returns the result dict (map PNG/PDF bytes, statistics, export details,
    description of what was done), or None if the request failed - in which
    case the reason has been reported through `ui.error`.

    When several datasets fit the request - it names a family ("using MODIS")
    or no dataset at all ("rainfall in Sri Lanka") - nothing is processed yet:
    the return value is {"dataset_options": {"named": ..., "options": [...]}}
    and the caller asks the person to pick one, then calls again with
    `dataset` set to the chosen ID (or to AUTO_CHOICE to leave the choice to
    the agent).
    """
    dataset = (dataset or "").strip()
    if not dataset:
        # Text that describes no map ("asdf") stops here, before the dataset
        # search offers datasets for it.
        with ui.spinner("Reading your request..."):
            problem = check_request(user_prompt, llm, has_uploaded_region=uploaded_region_geojson is not None)
        if problem:
            ui.error(problem)
            ui.stop()
        with ui.spinner("Checking which datasets fit your request..."):
            dataset_options = find_dataset_options(
                user_prompt, llm,
                region_bounds=get_geojson_bounds(uploaded_region_geojson) if uploaded_region_geojson else None,
                region_label=uploaded_region_label or "")
        if dataset_options:
            return {"dataset_options": dataset_options}
    chosen_dataset = "" if dataset == AUTO_CHOICE else dataset


    apply_cloud_removal    = user_wants_cloud_removal(user_prompt)      # asked for explicitly
    cloud_masking_declined = user_declined_cloud_removal(user_prompt)   # asked to keep clouds

    spyndex_index_summary = ""
    if SPYNDEX_AVAILABLE:
        lines = [f"  {name}: {idx.long_name} [{idx.application_domain}] bands={list(idx.bands)}"
                 for name, idx in list(spyndex.indices.items())[:80]]
        spyndex_index_summary = "SPYNDEX INDICES (first 80 of {}):\n".format(len(spyndex.indices)) + "\n".join(lines)

    # Standard dataset for the theme of the request, stated up front so a
    # general request is not answered with an obscure or coarse dataset.
    recommended = recommended_for(user_prompt)
    recommended_note = ""
    if chosen_dataset:
        recommended_note = (
            f"DATASET CHOSEN BY THE USER: {chosen_dataset}. The user picked this dataset from a list of "
            "alternatives. Use exactly this collection ID - never substitute another dataset, whatever "
            "the rules below say - and take the band names and scale factors from it.\n"
        )
    elif recommended:
        recommended_note = (
            "STANDARD DATASET for this request: "
            + "; ".join(f"{rec_id} ({rec_title})" for rec_id, rec_title in recommended)
            + ". Use exactly this collection unless the user's request itself names a different "
              "dataset, sensor or satellite.\n"
        )

    with ui.spinner("AI agent is analysing your request..."):

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
                "scale_offset, and set is_temporal appropriately. Before answering you ALWAYS "
                "call the Get GEE Dataset Info tool on the collection you chose, and you only "
                "ever use band names that tool returned."
            ),
            tools=[search_gee_catalog_tool, get_dataset_info_tool],
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=f"""
User request: "{user_prompt}"
{recommended_note}Today's date is {date.today().isoformat()}. Resolve relative periods ("last 3 months", "this year", "recent") against this date. date_end must never be later than today.
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
- "region": the place name exactly as an administrative unit is named, without words like "District" or "Province" (e.g. "Galle", "Western", "Nepal", "Bavaria")
- "country": English name of the country that contains the region (same as "region" when the region is itself a country; "" when the region is not inside a single country)
- "country_iso3": ISO 3166-1 alpha-3 code of that country (e.g. "LKA", "DEU", "USA"); "" when there is no single country
- "region_aliases": list of other names the region is officially known by, especially its local-language name (e.g. ["Bayern"] for Bavaria, ["Sachsen"] for Saxony); [] if none
- "admin_level": 0 if the region is a country, 1 if it is a province/state, 2 if it is a district/county, null if it is not an administrative unit (continent, river basin, city area, multi-country region)
- "bbox": [west, south, east, north] in decimal degrees, an approximate bounding box of the region. Always provide it; it is used when no administrative boundary exists (e.g. "Europe", "Amazon rainforest", "Nile Delta").
- "date_start": YYYY-MM-DD
- "date_end": YYYY-MM-DD
- "temporal_reducer": how the images in the date range are combined into one map. One of median | mean | sum | max | min | mode.
  median: reflectance and spectral indices (default). mean: temperature, LST, gas concentrations, night lights, soil moisture.
  sum: accumulated totals where every image is a total for its own period (daily/monthly rainfall in mm, 8-day ET). Never sum rates such as mm/hr.
  max: fire masks, peak values. mode: categorical data such as land cover classes.
- "series": how many maps the request asks for. One of none | monthly | seasonal | annual | monthly_climatology | seasonal_climatology | annual_climatology | custom.
  Read the research terms in "Rule 10 - Research terms for time" of the knowledge base before choosing. KEY DISTINCTION:
  "monthly X from 2020 to 2025" = every month of every year (72 maps); "long-term / average / mean monthly X from 2020 to 2025"
  = the 12 calendar months, each averaged over the years (all Januaries together, all Februaries together, ...) = monthly_climatology.
  none: ONE map of the whole period. This is the default - use it unless the request asks for several maps or a breakdown over time.
  monthly: one map per calendar month between date_start and date_end ("monthly ET maps for 2025" -> 12 maps).
  seasonal: one map per three-month season (Dec-Feb, Mar-May, Jun-Aug, Sep-Nov) in the period.
  annual: one map per calendar year, for consecutive years ("annual rainfall maps 2015 to 2024", "yearly NDVI since 2019").
  monthly_climatology: 12 maps, each calendar month averaged over several years ("average monthly rainfall 2001-2020", "monthly climatology", "long-term monthly mean").
  seasonal_climatology: 4 maps, each season averaged over several years.
  annual_climatology: ONE map of the average year over several years ("mean annual rainfall 2001-2020", "long-term annual average ET",
    "average annual NDVI 2015-2024"). For rainfall/ET keep temporal_reducer "sum": each year's total is averaged over the years.
  custom: specific periods to compare that are not consecutive months, seasons or years ("July 2015 vs July 2025", "2000, 2010 and 2020"). List them in "panels".
  For every value except none: date_start and date_end span ALL the maps together, and temporal_reducer says how the images
  inside EACH map's own period are combined. Use sum for a total per month / season / year - the default for rainfall and
  evapotranspiration ("monthly ET" means the monthly total). Use mean when the user asks for the average of the values
  ("monthly average temperature", "mean monthly LST", "average daily rainfall per month"). Use median for reflectance and indices.
  For a climatology of rainfall or ET keep temporal_reducer "sum": the totals are averaged over the years automatically.
- "panels": only for series "custom": list of {{"label": short name shown above the map, "date_start": "YYYY-MM-DD", "date_end": "YYYY-MM-DD"}}; [] otherwise.
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
10. DEFAULT DATASETS - when the user does not name a dataset, use these global ones (do not search for alternatives):
    land cover / LULC: ESA/WorldCover/v200 (band "Map", is_temporal=false) | elevation, slope, hillshade: USGS/SRTMGL1_003
    rainfall: UCSB-CHG/CHIRPS/DAILY (band "precipitation", sum) | land surface temperature: MODIS/061/MOD11A2
    night lights: NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG | population: WorldPop/GP/100m/pop | surface water: JRC/GSW1_4/GlobalSurfaceWater
    true colour / spectral indices: COPERNICUS/S2_SR_HARMONIZED (2017 onwards), Landsat before that
11. Never choose a dataset whose title names a country or region other than the user's region.

DATASET CHECK RULE (always): after choosing the collection, call the "Get GEE Dataset Info" tool with
its exact ID. Then: use only band names it lists (precomputed_band, band_override); copy scale_factor /
precomputed_scale from it; keep date_start and date_end inside its available period; set is_temporal=false
when its type is "image". If it says the dataset is not found, is deprecated, or is a "table", pick another
collection (search the catalog again) and check that one. For ANY single-variable request (rainfall,
temperature, a land cover product, a gas, an index band, ...) always fill "precomputed_band" with the exact
band to display, even when map_type is a thematic type such as PRECIPITATION or LANDCOVER.

UNLISTED COLLECTION RULE: If the user's dataset is not a common sensor you already know well
and is not in the Precomputed Band Registry, call the search_gee_catalog tool with descriptive
keywords BEFORE writing your final answer, and use the returned "id" verbatim as "collection".
Do not guess a collection ID from memory when the tool is available. Once you have a collection
ID (from your own knowledge or from the tool), you MUST still provide correct band names in
band_override, correct scale_factor/scale_offset, and is_temporal. If the tool call fails or
returns nothing useful, fall back to your best-effort knowledge rather than blocking the request.

Examples:

NDVI via MODIS (precomputed):
{{"collection":"MODIS/061/MOD13Q1","index":"","map_type":"PRECOMPUTED","precomputed_band":"NDVI","precomputed_scale":0.0001,"region":"Sri Lanka","country":"Sri Lanka","country_iso3":"LKA","region_aliases":[],"admin_level":0,"bbox":[79.5,5.9,81.9,9.9],"date_start":"2024-01-01","date_end":"2024-03-31","temporal_reducer":"median","series":"none","panels":[],"cloud_cover":85,"band_override":{{}},"is_temporal":true,"scale_factor":0.0001,"scale_offset":0.0,"notes":"MOD13Q1 has precomputed NDVI; used directly."}}

NDVI via Sentinel-2 (spyndex):
{{"collection":"COPERNICUS/S2_SR_HARMONIZED","index":"NDVI","map_type":"SPYNDEX","precomputed_band":"","precomputed_scale":1.0,"region":"Germany","country":"Germany","country_iso3":"DEU","region_aliases":[],"admin_level":0,"bbox":[5.8,47.2,15.1,55.1],"date_start":"2024-06-01","date_end":"2024-08-31","temporal_reducer":"median","series":"none","panels":[],"cloud_cover":20,"band_override":{{"N":"B8","R":"B4"}},"is_temporal":true,"scale_factor":0.0001,"scale_offset":0.0,"notes":"Sentinel-2 has no precomputed NDVI; computing via spyndex."}}

ET via MODIS (precomputed):
{{"collection":"MODIS/061/MOD16A2GF","index":"","map_type":"PRECOMPUTED","precomputed_band":"ET","precomputed_scale":0.1,"region":"India","country":"India","country_iso3":"IND","region_aliases":[],"admin_level":0,"bbox":[68.1,6.5,97.4,35.7],"date_start":"2024-01-01","date_end":"2024-12-31","temporal_reducer":"sum","series":"none","panels":[],"cloud_cover":85,"band_override":{{}},"is_temporal":true,"scale_factor":1.0,"scale_offset":0.0,"notes":"MOD16A2GF provides precomputed ET."}}

Monthly ET maps for one year (12 maps in one figure, each a monthly total):
{{"collection":"MODIS/061/MOD16A2GF","index":"","map_type":"PRECOMPUTED","precomputed_band":"ET","precomputed_scale":0.1,"region":"Sri Lanka","country":"Sri Lanka","country_iso3":"LKA","region_aliases":[],"admin_level":0,"bbox":[79.5,5.9,81.9,9.9],"date_start":"2025-01-01","date_end":"2025-12-31","temporal_reducer":"sum","series":"monthly","panels":[],"cloud_cover":85,"band_override":{{}},"is_temporal":true,"scale_factor":1.0,"scale_offset":0.0,"notes":"Monthly ET totals from the precomputed MOD16A2GF ET band, one map per month."}}

Long-term monthly average ET over several years (12 maps: all Januaries averaged, all Februaries averaged, ...):
{{"collection":"MODIS/061/MOD16A2GF","index":"","map_type":"PRECOMPUTED","precomputed_band":"ET","precomputed_scale":0.1,"region":"Jaffna","country":"Sri Lanka","country_iso3":"LKA","region_aliases":[],"admin_level":2,"bbox":[79.8,9.4,80.4,9.85],"date_start":"2020-01-01","date_end":"2025-12-31","temporal_reducer":"sum","series":"monthly_climatology","panels":[],"cloud_cover":85,"band_override":{{}},"is_temporal":true,"scale_factor":1.0,"scale_offset":0.0,"notes":"Monthly ET totals from MOD16A2GF, each calendar month averaged over 2020-2025 (climatology)."}}

Mean annual rainfall over several years (one map of the average yearly total):
{{"collection":"UCSB-CHG/CHIRPS/DAILY","index":"","map_type":"PRECIPITATION","precomputed_band":"precipitation","precomputed_scale":1.0,"region":"Sri Lanka","country":"Sri Lanka","country_iso3":"LKA","region_aliases":[],"admin_level":0,"bbox":[79.5,5.9,81.9,9.9],"date_start":"2001-01-01","date_end":"2020-12-31","temporal_reducer":"sum","series":"annual_climatology","panels":[],"cloud_cover":85,"band_override":{{}},"is_temporal":true,"scale_factor":1.0,"scale_offset":0.0,"notes":"Annual CHIRPS totals averaged over 2001-2020 (mean annual precipitation)."}}

RGB Sentinel-2:
{{"collection":"COPERNICUS/S2_SR_HARMONIZED","index":"","map_type":"RGB","precomputed_band":"","precomputed_scale":1.0,"region":"Tokyo","country":"Japan","country_iso3":"JPN","region_aliases":[],"admin_level":1,"bbox":[138.9,35.5,139.95,35.9],"date_start":"2024-03-01","date_end":"2024-04-01","temporal_reducer":"median","series":"none","panels":[],"cloud_cover":20,"band_override":{{"red":"B4","green":"B3","blue":"B2","nir":"B8","swir1":"B11","swir2":"B12"}},"is_temporal":true,"scale_factor":0.0001,"scale_offset":0.0,"notes":"Sentinel-2 true-color composite."}}
""",
            agent=agent,
            expected_output="Valid JSON only",
        )

        crew   = Crew(agents=[agent], tasks=[task], verbose=False, process="sequential")
        result = crew.kickoff()

    # A failed parse must stop here: substituting a default map would hand the
    # user a plausible-looking map of something they did not ask for.
    raw = (getattr(result, "raw", "") or "").strip()
    try:
        params = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        if not isinstance(params, dict):
            raise ValueError("not a JSON object")
    except Exception:
        ui.error(
            "The AI agent's answer could not be read, so no map was generated. "
            "Please try again, or rephrase the request."
        )
        with ui.expander("Agent's raw answer"):
            ui.code(raw or "(empty)")
        ui.stop()

    missing = [f for f in ("collection", "map_type") if not str(params.get(f) or "").strip()]
    if uploaded_region_geojson is None and not str(params.get("region") or "").strip():
        missing.append("region")
    if missing:
        ui.error(
            f"The AI agent could not work out the **{', '.join(missing)}** from your request, "
            "so no map was generated. Please state it explicitly and try again."
        )
        with ui.expander("Agent Decision"):
            ui.json(params)
        ui.stop()

    cid = COLLECTION_ALIASES.get(params["collection"], params["collection"])
    if chosen_dataset and cid != chosen_dataset:
        # The person's choice stands, even where the agent preferred another dataset.
        cid = chosen_dataset
    params["collection"] = cid

    with ui.expander("Agent Decision", expanded=False):
        ui.caption(params.get("notes", ""))
        ui.json(params)

    try:
        region_name       = str(params.get("region") or "").strip()
        if region_name.islower():
            region_name = region_name.title()
        index_name        = str(params.get("index") or "").upper()
        map_type          = str(params["map_type"]).upper()
        today             = date.today()
        date_start        = str(params.get("date_start") or "").strip()
        date_end          = str(params.get("date_end") or "").strip()
        if not date_start or not date_end:
            date_end   = today.isoformat()
            date_start = (today - timedelta(days=365)).isoformat()
            if bool(params.get("is_temporal", True)):
                ui.info(f"No period was given, so the last 12 months are used ({date_start} to {date_end}).")
        if date_end > today.isoformat():
            date_end = today.isoformat()
        # ---------------- ONE MAP OR SEVERAL ----------------
        # A series is split into its maps here; each entry of `panels` becomes
        # one map of the figure. An empty list means the usual single map.
        series_kind = normalise_series(params.get("series")) or infer_series_from_prompt(user_prompt)
        series_kind, series_note = refine_series(series_kind, user_prompt, date_start, date_end)
        if series_note:
            ui.info(series_note)
        panels, span_end = [], date_end
        # Mean annual value over several years (one map): the whole years of
        # the period, each composited on its own and then averaged.
        annual_ranges = []
        if series_kind == "annual_climatology":
            series_kind = None
            years = [p for p in build_panels("annual", date_start, date_end, None, today) if not p.get("partial")]
            if len(years) >= 2:
                annual_ranges = [r for p in years for r in p["ranges"]]
                date_start = annual_ranges[0][0]
                span_end = annual_ranges[-1][1]
                date_end = (date.fromisoformat(span_end) - timedelta(days=1)).isoformat()
        if series_kind:
            custom_periods = params.get("panels") if isinstance(params.get("panels"), list) else []
            panels = build_panels(series_kind, date_start, date_end, custom_periods, today)
            if len(panels) > MAX_PANELS:
                ui.error(
                    f"This request would need **{len(panels)} maps** in one figure; more than {MAX_PANELS} "
                    "are too small to read. No map was generated. Ask for a shorter period, for "
                    "seasonal or annual maps, or for a long-term monthly average (12 maps, each "
                    "calendar month averaged over the years)."
                )
                ui.stop()
            if len(panels) < 2:
                panels = []         # a "series" of one period is an ordinary map
            else:
                date_start = min(a for p in panels for a, _b in p["ranges"])
                span_end = max(b for p in panels for _a, b in p["ranges"])      # exclusive
                date_end = (date.fromisoformat(span_end) - timedelta(days=1)).isoformat()
                for p in panels:
                    if p.get("partial"):
                        ui.info(f"**{p['label']}** is not over yet: its map covers the period up to today.")
        cloud_cover       = int(params.get("cloud_cover", 85))
        band_override     = params.get("band_override", {}) or {}
        agent_scale_f     = float(params.get("scale_factor", 1.0))
        agent_scale_o     = float(params.get("scale_offset", 0.0))
        agent_is_temporal = bool(params.get("is_temporal", True))

        region_is_bbox = False
        if uploaded_region_geojson is not None:
            display_region_name = uploaded_region_label or region_name
            status_region = ui.status(f"Using uploaded region: **{ascii_label(display_region_name)}**", expanded=True)
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
            status_region = ui.status(f"Resolving boundary for **{ascii_label(region_name)}**", expanded=True)
            try:
                agent_level = params.get("admin_level")
                agent_level = agent_level if agent_level in (0, 1, 2) else None
                found = BoundaryAgent.resolve(
                    region_name,
                    country_name=str(params.get("country") or "").strip() or None,
                    admin_level=agent_level,
                    country_iso3=str(params.get("country_iso3") or "").strip() or None,
                    aliases=params.get("region_aliases") if isinstance(params.get("region_aliases"), list) else None,
                )
                if found is not None:
                    region_geom = found["geometry"]
                    status_region.update(
                        label=f"Region resolved: {ascii_label(region_name)} ({found['admin_type']})",
                        state="complete",
                    )
                else:
                    # Not an administrative unit (continent, basin, ...): use the
                    # agent's approximate bounding box rather than failing.
                    bbox = params.get("bbox")
                    try:
                        west, south, east, north = (float(v) for v in bbox)
                        bbox_ok = (-180 <= west < east <= 180) and (-90 <= south < north <= 90)
                    except Exception:
                        bbox_ok = False
                    if not bbox_ok:
                        raise ValueError(
                            f"No boundary found for '{region_name}' in the geoBoundaries dataset."
                        )
                    region_geom = ee.Geometry.Rectangle([west, south, east, north], None, False)
                    region_is_bbox = True
                    status_region.update(
                        label=f"No administrative boundary for {ascii_label(region_name)} - "
                              "using an approximate bounding box",
                        state="complete",
                    )
            except Exception as e:
                status_region.update(label=f"Could not resolve '{ascii_label(region_name)}'", state="error")
                ui.error(
                    f"Could not automatically find a boundary for **{ascii_label(region_name)}**. "
                    f"({e})\n\n"
                    "Try naming a country, province, or district, or upload a custom AOI "
                    "(GeoJSON) in the sidebar instead."
                )
                ui.stop()

        try:
            bounds     = region_geom.bounds().getInfo()
            coords     = bounds["coordinates"][0]
            all_lons   = [c[0] for c in coords]
            all_lats   = [c[1] for c in coords]
            geo_bounds = {
                "lon_min": min(all_lons), "lon_max": max(all_lons),
                "lat_min": min(all_lats), "lat_max": max(all_lats),
            }
        except Exception as e:
            ui.error(f"Could not work out the extent of **{ascii_label(region_name)}** ({e}). No map was generated.")
            ui.stop()

        # Outline drawn on the map: the same boundary the data is clipped to.
        boundary_geojson = None
        if uploaded_region_geojson is None and not region_is_bbox:
            boundary_geojson = BoundaryAgent.outline_geojson(region_geom, geo_bounds)

        # ---------------- DATASET ----------------
        # Two sources describe the dataset: the catalog record (scale, units,
        # class names, coverage - official datasets only) and a live query of
        # Earth Engine (the bands that really exist - any dataset).
        status_intro = ui.status(f"Inspecting dataset `{cid}`", expanded=False)
        meta = fetch_dataset_metadata(cid)
        if meta and meta["type"] == "table":
            status_intro.update(label=f"`{cid}` is a vector table, not imagery", state="error")
            ui.error(
                f"`{cid}` ({meta['title']}) is a vector table dataset. Gee-Luma maps image datasets; "
                "tables cannot be rendered yet. Try asking for an image dataset on the same theme."
            )
            ui.stop()
        col_info = introspect_collection(cid)
        bands = col_info["bands"]
        n_bands = len(bands)
        if col_info["error"] or n_bands == 0:
            # The agent named a dataset that cannot be opened as imagery.
            # Continuing would only fail later with an unrelated-looking error.
            status_intro.update(label=f"Dataset `{cid}` could not be opened", state="error")
            ui.error(
                f"The dataset the AI agent chose, `{cid}`, could not be opened as imagery "
                f"({col_info['error'] or 'it has no image bands'}). No map was generated. "
                "Try naming the dataset in your request, e.g. 'using ESA WorldCover' or 'using MODIS'."
            )
            ui.stop()
        dataset_title = meta["title"] if meta else cid
        status_intro.update(
            label=f"Dataset: {ascii_label(dataset_title)} ({n_bands} band{'s' if n_bands != 1 else ''})",
            state="complete"
        )
        with ui.expander("Dataset details"):
            ui.markdown(f"**ID:** `{cid}`")
            if meta:
                ui.markdown(f"**Title:** {meta['title']}")
                if meta["provider"]:
                    ui.markdown(f"**Provider:** {meta['provider']}")
                if meta["date_start"]:
                    ui.markdown(f"**Coverage:** {meta['date_start']} to {meta['date_end']}"
                                + (f" ({meta['cadence']})" if meta["cadence"] else ""))
                if meta["gsd"]:
                    ui.markdown(f"**Native resolution:** {meta['gsd']:g} m")
            else:
                ui.caption("Not in the official Earth Engine catalog - band details come from a live query only.")
            ui.markdown(f"**Bands:** `{', '.join(bands)}`")

        is_static  = resolve_is_static(cid, col_info, agent_is_temporal)
        if is_static:
            annual_ranges = []      # one undated image: nothing to average over years
        cloud_prop = detect_cloud_prop(cid, col_info)
        band_map   = get_dataset_band_map(cid, band_override, col_info)
        scale_cfg  = get_scale_config(cid, agent_scale_f, agent_scale_o)
        if cid not in DATASET_SENSOR and meta:
            # Sensor without a built-in profile: the catalog's own scale factor
            # for its spectral bands is more reliable than the agent's recollection.
            for mapped_band in band_map.values():
                band_meta = meta["bands"].get(mapped_band)
                if band_meta and band_meta["scale"] is not None:
                    scale_cfg = {"factor": float(band_meta["scale"]), "offset": float(band_meta["offset"] or 0.0)}
                    break

        # ---------------- WHICH BAND ----------------
        requested_band = str(params.get("precomputed_band") or "").strip()
        if requested_band and requested_band not in bands:
            by_lower = {b.lower(): b for b in bands}
            if requested_band.lower() in by_lower:
                requested_band = by_lower[requested_band.lower()]
            elif map_type == "PRECOMPUTED":
                ui.error(
                    f"The AI agent asked for band `{requested_band}`, which `{cid}` does not have. "
                    f"No map was generated. Available bands: `{', '.join(bands)}`. "
                    "Try naming the variable you want more specifically."
                )
                ui.stop()
            else:
                requested_band = ""

        # A thematic map type with an explicit band is drawn from that band, so
        # any dataset on the theme works - not only the one the type was written for.
        theme_key = None
        if map_type in THEMATIC_MAP_TYPES and requested_band:
            theme_key = map_type
            map_type = "PRECOMPUTED"
        if map_type == "PRECOMPUTED" and not requested_band:
            default_vis = [v["bands"][0] for v in (meta or {}).get("visualizations", [])
                           if len(v["bands"]) == 1 and v["bands"][0] in bands]
            data_bands = [b for b in bands
                          if not ((meta or {}).get("bands", {}).get(b) or {}).get("is_bitmask")]
            requested_band = (default_vis or data_bands or bands)[0]
            ui.info(f"No band was specified - showing `{requested_band}`.")

        # Categorical band (land cover and any other classified product)?
        class_band = None
        if map_type == "LANDCOVER":
            for candidate in (requested_band, LULC_BAND_LUT.get(cid), first_categorical_band(meta), "Map"):
                if candidate and candidate in bands:
                    class_band = candidate
                    break
            class_band = class_band or bands[0]
        elif map_type == "PRECOMPUTED":
            band_meta = (meta or {}).get("bands", {}).get(requested_band) or {}
            if band_meta.get("classes") or PRECOMPUTED_PALETTE_MAP.get(requested_band) == "LANDCOVER":
                class_band = requested_band
            elif is_class_candidate(band_meta, (col_info.get("band_types") or {}).get(requested_band),
                                    requested_band):
                # The catalog lists no classes for this band, but it may still
                # be a classification (mask, flag, class codes). The data
                # decides: a handful of whole-number values means classes.
                try:
                    if col_info["is_image_collection"]:
                        sample_col = ee.ImageCollection(cid).filterBounds(region_geom)
                        if not is_static:
                            sample_col = sample_col.filterDate(date_start, date_end)
                        sample = sample_col.select(requested_band).mosaic()
                    else:
                        sample = ee.Image(cid)
                    if distinct_values(sample, requested_band, region_geom, (meta or {}).get("gsd")):
                        class_band = requested_band
                except Exception:
                    pass
        is_categorical = class_band is not None
        has_class_schema = is_categorical and register_stac_classes(cid, class_band, meta)
        schema_key = cid          # where this band's classes are registered

        # ---------------- CLOUD MASKING ----------------
        # Applied by default wherever a per-pixel method exists: an unmasked
        # composite of optical imagery shows clouds and haze.
        mask_method           = cloud_mask_method(cid)
        cloud_removal_applied = (mask_method is not None) and (not is_static) and (not cloud_masking_declined)
        cloud_mask_desc       = mask_method[1] if cloud_removal_applied else None

        # How the images in the period are combined. Categorical data must never
        # be averaged, so classified products always use the most common class.
        reducer_name = str(params.get("temporal_reducer") or "").lower()
        if reducer_name not in TEMPORAL_REDUCERS:
            reducer_name = DEFAULT_REDUCER_BY_MAP_TYPE.get(theme_key or map_type, "median")
        if is_categorical:
            reducer_name = "mode"

        # Single-band maps only need that band. Selecting it first also avoids
        # failures on collections whose band list changes from image to image.
        single_band = class_band if is_categorical else (requested_band if map_type == "PRECOMPUTED" else None)

        status_col = ui.status(f"Loading dataset `{cid}`", expanded=True)
        period_note = None
        gap_fill = None           # details of gap filling, when it was applied
        original_mask = None      # where the requested period itself had data

        if is_static:
            try:
                if col_info["is_image_collection"]:
                    static_col = ee.ImageCollection(cid).filterBounds(region_geom)
                    if single_band:
                        static_col = static_col.select(single_band)
                    img = static_col.mosaic()
                else:
                    img = ee.Image(cid)
            except Exception:
                img = ee.Image(cid)
            n_images = 1
            if panels:
                ui.info(f"`{cid}` is a single, undated dataset, so one map is shown instead of a series.")
                panels = []
            if apply_cloud_removal:
                ui.info("Cloud removal is not applicable to static datasets - skipped.")
        else:
            base_col = ee.ImageCollection(cid).filterBounds(region_geom)
            if "S1_GRD" in cid:
                base_col = base_col.filter(ee.Filter.eq("instrumentMode", "IW"))
            col = base_col.filterDate(date_start, span_end if panels or annual_ranges else date_end)
            if cloud_prop:
                col = col.filter(ee.Filter.lt(cloud_prop, cloud_cover))

            if apply_cloud_removal and mask_method is None:
                ui.warning(
                    f"Pixel-level cloud masking is not available for `{cid}`. "
                    + ("Cloud filtering by scene percentage is still applied." if cloud_prop else "")
                )
            if cloud_removal_applied:
                status_col.update(label=f"Applying pixel-level cloud mask for `{cid}`")
                col = apply_cloud_mask(col, cid)

            n_images = col.size().getInfo()
            if n_images == 0 and base_col.filterDate(date_start, date_end).size().getInfo() == 0:
                # The dataset has nothing at all in this period (typical for
                # yearly products asked for "recent months"). Use its most
                # recent release up to the end of the period, and say so.
                latest_time = (base_col.filterDate("1900-01-01", date_end)
                               .aggregate_max("system:time_start").getInfo())
                if latest_time is not None:
                    col = base_col.filter(ee.Filter.eq("system:time_start", latest_time))
                    if cloud_removal_applied:
                        col = apply_cloud_mask(col, cid)
                    n_images = col.size().getInfo()
                    latest_day = ee.Date(latest_time).format("YYYY-MM-dd").getInfo()
                    period_note = (f"`{cid}` has no images between {date_start} and {date_end}; "
                                   f"the most recent one before that ({latest_day}) is shown instead.")
                    ui.info(period_note)
                    date_start = date_end = latest_day
            if n_images == 0:
                ui.error(
                    f"**No usable imagery found** for **{ascii_label(region_name)}** "
                    f"between {date_start} and {date_end}."
                )
                hints = []
                if base_col.size().getInfo() == 0:
                    hints.append(f"`{cid}` ({ascii_label(dataset_title)}) has no images over this region at all - "
                                 "it probably covers a different part of the world. Try naming another dataset.")
                elif meta and meta["date_start"]:
                    hints.append(f"`{cid}` covers {meta['date_start']} to {meta['date_end']}.")
                if cloud_prop:
                    hints.append(f"Scenes were limited to under {cloud_cover}% cloud - "
                                 "widen the period or allow more cloud.")
                ui.warning(" ".join(hints) or "Try a different period.")
                ui.stop()
            if single_band:
                col = col.select(single_band)
            composite_bands = col.first().bandNames()

            def reduce_images(images):
                return images.reduce(TEMPORAL_REDUCERS[reducer_name]()).rename(composite_bands)

            if panels and period_note is None:
                # How many images each map has (one request for all of them).
                # Periods without any are left out rather than drawn empty.
                counts = ee.List([[col.filterDate(a, b).size() for a, b in p["ranges"]]
                                  for p in panels]).getInfo()
                for p, per_range in zip(panels, counts):
                    p["ranges"] = [r for r, n in zip(p["ranges"], per_range) if n > 0]
                    p["n_images"] = sum(per_range)
                empty = [p["label"] for p in panels if not p["ranges"]]
                panels = [p for p in panels if p["ranges"]]
                if empty:
                    ui.info(f"`{cid}` has no images for {', '.join(empty)} - left out of the figure.")
                if len(panels) < 2:
                    ui.info("Only one of the requested periods has images, so a single map is shown.")
                    panels = []
            else:
                panels = []

            if annual_ranges and (period_note is not None or reducer_name != "sum"):
                # Only a total needs the years composited one by one; the
                # mean (median, ...) of all the images already is the long-term one.
                annual_ranges = [] if period_note is not None else annual_ranges
            elif annual_ranges:
                counts = ee.List([col.filterDate(a, b).size() for a, b in annual_ranges]).getInfo()
                annual_ranges = [r for r, n in zip(annual_ranges, counts) if n > 0]

            image_periods = None      # set when totals are divided between periods by days
            if panels or (annual_ranges and reducer_name == "sum"):
                if reducer_name == "sum":
                    # An image that starts just before the first period may
                    # still reach into it.
                    lead = base_col.filterDate(
                        (date.fromisoformat(date_start) - timedelta(days=32)).isoformat(), date_start)
                    if cloud_prop:
                        lead = lead.filter(ee.Filter.lt(cloud_prop, cloud_cover))
                    if cloud_removal_applied:
                        lead = apply_cloud_mask(lead, cid)
                    if single_band:
                        lead = lead.select(single_band)
                    with_lead = lead.merge(col)
                    image_periods = multi_day_periods(with_lead)

                def period_composite(a, b):
                    total = (prorated_total(with_lead, image_periods, a, b, composite_bands)
                             if image_periods else None)
                    return total if total is not None else reduce_images(col.filterDate(a, b))

            if annual_ranges and reducer_name == "sum" and not panels:
                # Mean annual total: the total of each year, then the average
                # of those totals (not the multi-year sum).
                img = ee.ImageCollection.fromImages([period_composite(a, b) for a, b in annual_ranges]).mean()
            elif panels:
                for p in panels:
                    ranges = p["ranges"]
                    if len(ranges) == 1:
                        p["raw"] = period_composite(*ranges[0])
                    elif reducer_name == "sum":
                        # Climatology of a total: the total of each year's
                        # period, then the average of those totals. Summing
                        # all the years together would give a multi-year total.
                        p["raw"] = ee.ImageCollection.fromImages(
                            [period_composite(a, b) for a, b in ranges]).mean()
                    else:
                        p["raw"] = reduce_images(col.filter(ee.Filter.Or(*[ee.Filter.date(a, b) for a, b in ranges])))
                # Stand-in for "the image" wherever one is needed to describe
                # the data as a whole: it has data wherever any of the maps does.
                img = ee.ImageCollection.fromImages([p["raw"] for p in panels]).mosaic()
                n_images = sum(p["n_images"] for p in panels)
            else:
                img = reduce_images(col)

            # ---------------- GAP FILLING ----------------
            # Totals are not filled: adding rain from other months would change
            # what the number means. A period that was already replaced by the
            # nearest available image is left alone too.
            # Nor are the maps of a series: each must show its own period only,
            # or the comparison between them means nothing.
            fill_wanted = (fill_gaps_option and reducer_name != "sum" and period_note is None and not panels
                           and not any(k in user_prompt.lower() for k in GAP_FILL_OPT_OUT))
            if fill_wanted:
                try:
                    mask_band = single_band or next(
                        (b for b in (band_map.get("red"), band_map.get("nir"), band_map.get("vv")) if b in bands),
                        bands[0])
                    coverage_scale = max(float((meta or {}).get("gsd") or 30), 30)
                    original_cov = data_coverage_percent(img, mask_band, region_geom, coverage_scale)
                    if original_cov < GAP_FILL_BELOW_PERCENT:
                        status_fill = ui.status(
                            f"Only {original_cov:.0f}% of the region has data - filling gaps from nearby dates",
                            expanded=True)
                        start_day, end_day = date.fromisoformat(date_start), date.fromisoformat(date_end)
                        step_days = min(max((end_day - start_day).days, 30), 90)

                        def _composite_for(window_start, window_end):
                            window = base_col.filterDate(window_start, window_end)
                            if cloud_prop:
                                window = window.filter(ee.Filter.lt(cloud_prop, cloud_cover))
                            if cloud_removal_applied:
                                window = apply_cloud_mask(window, cid)
                            if single_band:
                                window = window.select(single_band)
                            return window.reduce(TEMPORAL_REDUCERS[reducer_name]()).rename(composite_bands)

                        wider, filled, filled_cov, days_used = [], img, original_cov, 0
                        for k in range(1, GAP_FILL_STEPS + 1):
                            window_start = (start_day - timedelta(days=k * step_days)).isoformat()
                            window_end = min(end_day + timedelta(days=k * step_days), today).isoformat()
                            wider.append(_composite_for(window_start, window_end))
                            # Later images in a mosaic win, so the order is: widest
                            # window at the bottom, nearer windows above it, and the
                            # requested period on top - every pixel comes from the
                            # nearest dates that have data for it.
                            filled = ee.ImageCollection.fromImages(list(reversed(wider)) + [img]).mosaic()
                            filled_cov = data_coverage_percent(filled, mask_band, region_geom, coverage_scale)
                            days_used = k * step_days
                            status_fill.update(
                                label=f"Gap filling: {filled_cov:.0f}% of the region covered using "
                                      f"{days_used} days before and after")
                            if filled_cov >= GAP_FILL_BELOW_PERCENT:
                                break
                        if filled_cov - original_cov >= 1.0:
                            original_mask = img.select([mask_band]).mask()
                            img = filled
                            gap_fill = {"original_percent": original_cov, "filled_percent": filled_cov,
                                        "days": days_used, "window_start": window_start, "window_end": window_end}
                            status_fill.update(
                                label=f"Gaps filled: {original_cov:.0f}% -> {filled_cov:.0f}% of the region "
                                      f"(imagery from {window_start} to {window_end})",
                                state="complete")
                        else:
                            status_fill.update(
                                label="No extra data found in nearby dates - map left as it is", state="complete")
                except Exception as e:
                    print(f"Gap filling skipped: {e}")
                    ui.caption(gap_fill_skipped_note(e))

        status_col.update(
            label=(f"Dataset loaded ({n_images} image{'s' if n_images != 1 else ''}"
                   + (f", {len(panels)} maps" if panels else
                      "" if is_static or n_images == 1 else f", {reducer_name} composite") + ")"
                   + (" - Cloud masked" if cloud_removal_applied else "")),
            state="complete"
        )

        status_compute = ui.status(f"Computing **{map_type}** ({index_name or class_band or requested_band or 'none'})", expanded=True)

        # Admin and uploaded regions are cut out along their boundary. A
        # bounding-box region (continent, basin) instead fills the map frame;
        # cutting it to a lat/lon box would leave a wedge shape once projected.
        def clip_to_region(image):
            return image if region_is_bbox else image.clip(region_geom)

        lulc_legend: list | None = None
        auto_range = False          # stretch the colour range to the data in this region?

        if is_categorical:
            class_img = img.select(class_band)
            class_meta = (meta or {}).get("bands", {}).get(class_band) or {}
            # A land cover band is a land cover map however the agent labelled the request.
            class_text = f"{class_band} {class_meta.get('description', '')}".lower().replace(" ", "")
            is_landcover = (map_type == "LANDCOVER" or "landcover" in class_text or "landuse" in class_text
                            or PRECOMPUTED_PALETTE_MAP.get(class_band) == "LANDCOVER")
            if is_landcover:
                display_label = MAP_TYPE_TITLES["LANDCOVER"]
            else:
                display_label = band_display_label(meta, class_band) if class_meta else class_band
            title_label = display_label
            class_filter_applied = False
            snap_values = None
            if not has_class_schema:
                # No class list in the catalog: build one from the values in
                # the data, named from the band description where it spells
                # them out and by number otherwise.
                found = distinct_values(class_img, class_band, region_geom, (meta or {}).get("gsd"),
                                        max_classes=60 if is_landcover else MAX_DETECTED_CLASSES)
                if found:
                    schema_key = register_detected_classes(cid, class_band, found, class_meta.get("text_classes"))
                    has_class_schema = True
                    snap_values = found
                    class_img = snap_to_values(class_img, found)
                    if any(entry["label"] == f"Class {value}"
                           for value, entry in LULC_CLASS_SCHEMAS[schema_key].items()):
                        ui.caption(f"`{cid}` publishes no class names for `{class_band}` - "
                                   "classes are labelled by their value.")

            def class_codes(raw):
                """The dataset's own class codes of a composite."""
                codes = raw.select(class_band)
                return snap_to_values(codes, snap_values) if snap_values else codes

            if has_class_schema:
                lulc_class_values = detect_lulc_class_filter(user_prompt, schema_key,
                                                             require_only=not is_landcover)
                if lulc_class_values:
                    class_filter_applied = True
                    if len(lulc_class_values) <= 2:
                        # A map of one or two classes is titled after them.
                        title_label = " and ".join(
                            LULC_CLASS_SCHEMAS[schema_key][v]["label"] for v in lulc_class_values)
                    ui.info("Showing only: **" + ", ".join(
                        LULC_CLASS_SCHEMAS[schema_key][v]["label"] for v in lulc_class_values) + "**")
                else:
                    # Legend lists only the classes that occur in this region
                    # (in any of the maps, for a series).
                    try:
                        counted = (ee.Image.cat([class_codes(p["raw"]).rename([f"p{i}"])
                                                 for i, p in enumerate(panels)]) if panels else class_img)
                        hists = counted.reduceRegion(
                            reducer=ee.Reducer.frequencyHistogram(), geometry=region_geom,
                            scale=max(float((meta or {}).get("gsd") or 100), 100),
                            bestEffort=True, maxPixels=1e9,
                        ).getInfo() or {}
                        present = {int(float(k)) for hist in hists.values() for k in (hist or {})}
                        lulc_class_values = [v for v in LULC_CLASS_SCHEMAS[schema_key] if v in present]
                    except Exception:
                        lulc_class_values = []
                display_classes = lulc_classes_for_display(schema_key, lulc_class_values)
                result_img = class_img.remap(
                    display_classes, list(range(len(display_classes)))).rename("LANDCOVER")
                vis_params_gee = {k: v for k, v in lulc_vis_for_classes(schema_key, display_classes).items()
                                  if k != "label"}
                lulc_legend = build_lulc_class_legend(schema_key, display_classes)
            else:
                # No published class list (community dataset): colour by value
                # and label the classes by their numbers.
                result_img = class_img.rename("LANDCOVER")
                rng = auto_vis_params(result_img, "LANDCOVER", region_geom, percentile=0)
                vis_params_gee = {"min": rng["min"], "max": rng["max"], "bands": ["LANDCOVER"],
                                  "palette": INDEX_PALETTES["LANDCOVER"]["palette"]}
                lulc_legend = generic_discrete_legend(
                    clip_to_region(result_img), "LANDCOVER", region_geom,
                    vis_params_gee["palette"], vis_params_gee["min"], vis_params_gee["max"]) or None
                ui.caption(f"`{cid}` publishes no class names - classes are labelled by their numeric value.")

            def to_display(raw):
                """The image drawn on the map, from a composite of the dataset's bands."""
                if has_class_schema:
                    return class_codes(raw).remap(
                        display_classes, list(range(len(display_classes)))).rename("LANDCOVER")
                return class_codes(raw).rename("LANDCOVER")

            final_img = clip_to_region(result_img)
            map_label = "LANDCOVER" if is_landcover else class_band

        elif map_type == "PRECOMPUTED":
            band_meta = (meta or {}).get("bands", {}).get(requested_band) or {}
            if band_meta.get("scale") is not None or band_meta.get("offset") is not None:
                band_scale  = float(band_meta.get("scale") if band_meta.get("scale") is not None else 1.0)
                band_offset = float(band_meta.get("offset") or 0.0)
            else:
                band_scale, band_offset = float(params.get("precomputed_scale") or 1.0), 0.0
            # Temperatures are published in kelvin; maps read better in Celsius.
            band_units = band_meta.get("units", "")
            kelvin = band_units in ("K", "Kelvin", "kelvin")
            if kelvin:
                band_units = "deg C"

            def to_display(raw):
                """The image drawn on the map, from a composite of the dataset's bands."""
                out = raw.select(requested_band)
                if band_scale != 1.0:
                    out = out.multiply(band_scale)
                if band_offset != 0.0:
                    out = out.add(band_offset)
                if kelvin:
                    out = out.subtract(273.15)
                return out.rename(requested_band)

            result_img = to_display(img)

            palette_key = (theme_key or PRECOMPUTED_PALETTE_MAP.get(requested_band)
                           or (requested_band.upper() if requested_band.upper() in INDEX_PALETTES else None)
                           or infer_theme(requested_band, band_meta.get("description", ""))
                           or requested_band.upper())
            themed = theme_key or (palette_key if palette_key in MAP_TYPE_TITLES else None)
            if palette_key in INDEX_PALETTES:
                vis_params = dict(INDEX_PALETTES[palette_key])
                auto_range = palette_key not in FIXED_RANGE_KEYS
                title_label = MAP_TYPE_TITLES.get(palette_key, vis_params["label"])
            else:
                vis_params = dict(INDEX_PALETTES["GENERIC"])
                catalog_palette = stac_palette_for_band(meta, requested_band)
                if catalog_palette:
                    vis_params["palette"] = catalog_palette
                auto_range = True
                title_label = band_display_label(meta, requested_band).split(" (")[0] if band_meta else requested_band
            # The palette's own label carries units that are only right for the
            # dataset it was written for; prefer the catalog's description.
            if band_meta and (auto_range or palette_key not in INDEX_PALETTES):
                display_label = band_display_label(meta, requested_band).split(" (")[0]
                if themed:
                    display_label = MAP_TYPE_TITLES[themed]
                if band_units:
                    display_label = f"{display_label} ({band_units})"
            else:
                display_label = vis_params.get("label", requested_band)
            vis_params_gee = {k: v for k, v in vis_params.items() if k != "label"}
            final_img      = clip_to_region(result_img)
            map_label      = requested_band

        elif map_type == "SPYNDEX" and index_name:
            def to_display(raw):
                return compute_spyndex_on_gee(
                    raw, cid, index_name, band_map, scale_cfg,
                    band_override=band_override or None
                )

            result_img = to_display(img)
            if result_img is None:
                ui.error(
                    f"**{index_name}** could not be computed from `{cid}`: the index is unknown or the "
                    f"dataset lacks a band it needs. Available bands: `{', '.join(bands)}`. No map was generated."
                )
                ui.stop()
            vis_params     = get_palette(index_name)
            vis_params_gee = {k: v for k, v in vis_params.items() if k != "label"}
            display_label  = vis_params.get("label", index_name)
            auto_range     = index_name not in INDEX_PALETTES
            long_name      = spyndex.indices[index_name].long_name if SPYNDEX_AVAILABLE and index_name in spyndex.indices else ""
            title_label    = f"{long_name} ({index_name})" if long_name and len(long_name) < 48 else index_name
            final_img      = clip_to_region(result_img)
            map_label      = index_name

        else:
            def special_map(raw):
                return compute_special_map(
                    raw, map_type, cid, band_map, scale_cfg,
                    available_bands=bands,
                    preferred_band=requested_band or None,
                )

            def to_display(raw):
                return special_map(raw)[0]

            result_img, vis_params_raw = special_map(img)
            display_label  = INDEX_PALETTES.get(map_type, {}).get("label", map_type)
            title_label    = MAP_TYPE_TITLES.get(map_type, map_type)
            vis_params_gee = {k: v for k, v in vis_params_raw.items() if k != "label"}
            auto_range     = "palette" in vis_params_gee and map_type not in FIXED_RANGE_KEYS
            final_img      = clip_to_region(result_img)
            map_label      = map_type

        is_rgb = "bands" in vis_params_gee and len(vis_params_gee["bands"]) == 3
        value_band = vis_params_gee.get("bands", [map_label])[0]

        # Every map of a series is computed exactly as the single map is.
        for p in panels:
            p["image"] = clip_to_region(to_display(p["raw"]))

        # Fit the display range to the data in this region. Fixed ranges are kept
        # only where the range is physically meaningful (indices, percentages).
        if is_rgb:
            stretch = auto_rgb_stretch(final_img, vis_params_gee["bands"], region_geom,
                                       per_band=(map_type == "SAR_RGB"))
            if stretch:
                vis_params_gee["min"], vis_params_gee["max"] = stretch["min"], stretch["max"]
        elif auto_range or (reducer_name == "sum" and not is_static and not is_categorical):
            # One range for all the maps of a series, so that a colour means
            # the same value on each of them.
            auto = ((shared_vis_range([p["image"] for p in panels], value_band, region_geom) if panels else None)
                    or auto_vis_params(final_img, value_band, region_geom))
            if auto["max"] > auto["min"]:
                vis_params_gee["min"], vis_params_gee["max"] = auto["min"], auto["max"]
        # Units of the legend. The dataset's units describe one image; a map
        # of totals is per month, season or year (or simply the total of some
        # other period), and water depths read in mm.
        if not is_static and not is_categorical and not is_rgb:
            if panels:
                unit_period = {"monthly": "month", "monthly_climatology": "month", "seasonal": "season",
                               "seasonal_climatology": "season", "annual": "year"}.get(series_kind)
            elif annual_ranges:
                unit_period = "year"
            else:
                unit_period = whole_period(date_start, date_end)
            display_label = relabel_units(
                str(display_label), reducer_name if n_images > 1 else None, unit_period,
                hint=f"{title_label} {map_label} {theme_key or ''}")
        if reducer_name == "sum" and not is_static and not is_categorical and n_images > 1:
            display_label = "Total " + str(display_label)
            if annual_ranges:
                display_label = "Mean t" + display_label[1:]
            elif not panels:
                title_label = "Total " + title_label[0].lower() + title_label[1:]
            elif series_kind in CLIMATOLOGIES:
                display_label = "Mean t" + display_label[1:]
        # The title of a series says what each map is (monthly total, annual
        # mean, long-term monthly mean, ...); colour composites and class
        # maps have no such statistic to name.
        plain_series = is_rgb or is_categorical
        if panels:
            title_label = series_title(series_kind, reducer_name, title_label, plain_series)
        elif annual_ranges:
            title_label = series_title("annual_climatology", reducer_name, title_label, plain_series)

        # Apply sidebar palette override
        palette_override = PALETTE_PRESETS.get(selected_palette)
        if palette_override and "palette" in vis_params_gee and not is_categorical:
            vis_params_gee["palette"] = palette_override

        # The dataset must actually have data here: a regional dataset used
        # outside its area, or a period with every pixel masked, would
        # otherwise produce an empty map that looks like a result.
        try:
            first_band = final_img.bandNames().get(0)
            valid_pixels = ee.Number(final_img.select([first_band]).reduceRegion(
                reducer=ee.Reducer.count(), geometry=region_geom,
                scale=max(float((meta or {}).get("gsd") or 30), 30),
                bestEffort=True, maxPixels=1e6,
            ).values().get(0)).getInfo()
        except Exception:
            valid_pixels = None     # could not check; let the render decide
        if valid_pixels == 0:
            status_compute.update(label="No data in this region", state="error")
            ui.error(
                f"`{cid}` ({ascii_label(dataset_title)}) has **no data over {ascii_label(region_name)}**"
                + ("" if is_static else f" between {date_start} and {date_end}")
                + ". No map was generated. The dataset may cover a different part of the world, "
                "or every pixel was masked (cloud). Try naming another dataset or a longer period."
            )
            ui.stop()

        status_compute.update(label=f"{map_type} computed", state="complete")

        # ---------------- STATISTICS ----------------
        # Computed from the same image that is drawn, so numbers and map agree.
        stats, stats_lines, class_shares = None, None, None
        legend_without_shares = [dict(entry) for entry in lulc_legend] if lulc_legend else None
        if panels:
            # The same figures for every map, side by side.
            if not is_rgb:
                status_stats = ui.status(f"Computing statistics for {len(panels)} maps", expanded=False)
                stats_scale = max(float((meta or {}).get("gsd") or 30), 10)
                panel_images = [p["image"] for p in panels]
                panel_labels = [ascii_label(p["label"]) for p in panels]
                if is_categorical:
                    position_labels = ({i: LULC_CLASS_SCHEMAS[schema_key][v]["label"]
                                        for i, v in enumerate(display_classes)} if has_class_schema else None)
                    stats = series_class_stats(panel_images, panel_labels, "LANDCOVER", region_geom,
                                               position_labels, stats_scale, share_of_region=class_filter_applied)
                    if stats:
                        if has_class_schema:
                            for row in stats["rows"]:
                                row["value"] = display_classes[row["value"]]
                                row["color"] = LULC_CLASS_SCHEMAS[schema_key][row["value"]]["color"]
                        class_shares = {row["class"]: sum(row["percent"]) / len(row["percent"])
                                        for row in stats["rows"]}
                else:
                    stats = series_stats(panel_images, panel_labels, value_band, region_geom, stats_scale)
                    for p, row in zip(panels, (stats or {}).get("rows", [])):
                        if row["mean"] is not None:
                            p["note"] = f"mean {format_value(row['mean'])}"
                status_stats.update(
                    label="Statistics computed" if stats else "Statistics could not be computed",
                    state="complete" if stats else "error")
        elif not is_rgb:
            status_stats = ui.status("Computing statistics for the region", expanded=False)
            stats_scale = max(float((meta or {}).get("gsd") or 30), 10)
            if is_categorical:
                # final_img holds legend positions (0, 1, 2, ...) when the dataset
                # publishes its classes, otherwise the raw class values.
                position_labels = ({i: LULC_CLASS_SCHEMAS[schema_key][v]["label"]
                                    for i, v in enumerate(display_classes)} if has_class_schema else None)
                stats = class_stats(final_img, "LANDCOVER", region_geom, position_labels, stats_scale,
                                    share_of_region=class_filter_applied)
                if stats:
                    if has_class_schema:
                        for row in stats["rows"]:
                            row["value"] = display_classes[row["value"]]    # report the dataset's own codes
                            row["color"] = LULC_CLASS_SCHEMAS[schema_key][row["value"]]["color"]
                    class_shares = {row["class"]: row["percent"] for row in stats["rows"]}
                    for entry in (lulc_legend or []):
                        pct = class_shares.get(entry["label"])
                        if pct is not None:
                            entry["label"] += f" ({pct:.1f}%)" if pct >= 0.05 else " (<0.1%)"
            else:
                stats = continuous_stats(
                    final_img, value_band, region_geom,
                    float(vis_params_gee.get("min", 0)), float(vis_params_gee.get("max", 1)), stats_scale)
                if stats:
                    s = dict(stats["rows"])
                    stats_lines = [
                        f"Mean {format_value(s.get('Mean'))}  |  Median {format_value(s.get('Median'))}",
                        f"Min {format_value(s.get('Minimum'))}  |  Max {format_value(s.get('Maximum'))}",
                        f"Std dev {format_value(s.get('Standard deviation'))}",
                    ]
            if stats and stats.get("area_km2") and stats_lines is not None:
                stats_lines.append(f"Region area {stats['area_km2']:,.0f} km2")
                if stats.get("coverage_percent") is not None:
                    stats_lines.append(f"Valid data over {stats['coverage_percent']:.0f}% of region")
                if gap_fill:
                    stats_lines.append(f"({gap_fill['original_percent']:.0f}% from the period, rest gap-filled)")
            status_stats.update(
                label="Statistics computed" if stats else "Statistics could not be computed",
                state="complete" if stats else "error")

        # A region with more classes than fit the legend panel lists the
        # largest ones; the statistics table and CSV still hold every class.
        if lulc_legend:
            lulc_legend = shorten_legend(lulc_legend, class_shares)
            legend_without_shares = shorten_legend(legend_without_shares, class_shares)

        # ---------------- RENDER ----------------
        projection = choose_map_projection(geo_bounds)
        extent = projected_extent(projection, geo_bounds, uploaded_region_geojson or boundary_geojson)

        status_thumb = ui.status("Rendering map image on Earth Engine", expanded=True)
        # Composites of many hundreds of images are too slow at full size.
        target_px = 2048 if n_images <= 400 else 1024
        if panels:
            # The grid is chosen from the shape of the region, and each map is
            # rendered at the size it will be printed at.
            layout = choose_grid_layout(len(panels), (extent[1] - extent[0]) / max(extent[3] - extent[2], 1e-9))
            target_px = layout["panel_px"]
            status_thumb.update(label=f"Rendering {len(panels)} maps on Earth Engine")
            panel_pils = fetch_panel_thumbnails(
                [p["image"] for p in panels], vis_params_gee, extent, projection["crs"], target_px,
                on_panel=lambda done, total: status_thumb.update(
                    label=f"Rendering maps on Earth Engine ({done} of {total})"))
            status_thumb.update(
                label=f"{len(panels)} maps rendered ({layout['cols']} x {layout['rows']} grid, {target_px}px each)",
                state="complete")
        else:
            map_pil, final_dim = fetch_thumbnail_with_retry(
                final_img, vis_params_gee, extent, projection["crs"], target_long_side=target_px)
            status_thumb.update(label=f"Map image rendered at {final_dim}px", state="complete")

        if cloud_removal_applied:
            engine_lbl = "Cloud masked"
        elif map_type == "PRECOMPUTED" or is_categorical:
            engine_lbl = "Precomputed"
        elif map_type == "SPYNDEX":
            engine_lbl = "Spyndex"
        else:
            engine_lbl = "Built-in"

        status_render = ui.status("Rendering cartographic layout", expanded=True)

        # Title, period line and credit block
        if panels:
            subtitle = series_subtitle(series_kind, panels)
            processing = (series_processing(series_kind, reducer_name, n_images, plain_series)
                          + (": " + ", ".join(ascii_label(p["label"]) for p in panels) if series_kind == "custom"
                             else f", {date_start} to {date_end}"))
        elif annual_ranges:
            n_years = len(annual_ranges)
            subtitle = f"Average over {date_start[:4]} to {date_end[:4]} ({n_years} years)"
            processing = (series_processing("annual_climatology", reducer_name, n_images, plain_series)
                          + f", {date_start} to {date_end}")
        elif is_static:
            if meta and meta["date_start"]:
                y0, y1 = meta["date_start"][:4], meta["date_end"][:4]
                # A period ending on 1 January belongs to the year before.
                if meta["date_end"][5:10] == "01-01" and int(y1) > int(y0):
                    y1 = str(int(y1) - 1)
                subtitle = f"Dataset year {y0}" if y0 == y1 else f"Dataset period {y0} to {y1}"
            else:
                subtitle = None
            processing = "Static dataset, no compositing"
        elif date_start == date_end or n_images == 1:
            subtitle = f"{date_start}" if date_start == date_end else f"{date_start} to {date_end}"
            processing = f"Single image, {subtitle}"
        else:
            subtitle = f"{date_start} to {date_end}"
            processing = f"{reducer_name.capitalize()} composite of {n_images} images, {date_start} to {date_end}"
        if cloud_removal_applied:
            processing += f"; cloud masking: {cloud_mask_desc}"
        if cloud_prop and not is_static:
            processing += f"; scenes under {cloud_cover}% cloud"
        if panels:
            if image_periods:
                processing += "; images spanning two periods are divided between them by days"
            processing += "; all maps share one extent and one colour scale"
        processing_original = processing
        if gap_fill:
            processing += (f"; cloud gaps filled with imagery from {gap_fill['window_start']} to "
                           f"{gap_fill['window_end']} (the period alone covers "
                           f"{gap_fill['original_percent']:.0f}% of the region)")

        credit_lines = [
            f"Data: {dataset_title}" + (f" ({meta['provider']})" if meta and meta["provider"] else "")
            + f" | Earth Engine ID: {cid}",
            f"Processing: {processing}.",
            f"Projection: {projection['name']}."
            + (f" Native resolution: {meta['gsd']:g} m." if meta and meta["gsd"] else "")
            + f" Map produced {date.today().isoformat()} with Gee-Luma on Google Earth Engine.",
        ]

        render_kwargs = dict(
            extent           = extent,
            projection       = projection,
            title            = map_title_override.strip() or f"{title_label} - {region_name}",
            subtitle         = subtitle,
            region_name      = region_name,
            vis_params_gee   = vis_params_gee,
            display_label    = display_label,
            is_rgb           = is_rgb,
            geo_bounds       = geo_bounds,
            lulc_legend      = lulc_legend,
            uploaded_geojson = uploaded_region_geojson,
            boundary_geojson = boundary_geojson,
            credit_lines     = credit_lines,
            stats_lines      = stats_lines,
        )
        if panels:
            rendered = render_composite_figure(
                panels=[{"image": pil, "label": p["label"], "note": p.get("note")}
                        for p, pil in zip(panels, panel_pils)],
                layout=layout, **render_kwargs)
        else:
            rendered = render_cartographic_figure(map_pil_image=map_pil, **render_kwargs)

        # The original, unfilled map: the same result with the filled pixels
        # masked out again. It is rendered only if the user asks for it.
        original_job = None
        if gap_fill:
            original_credit = list(credit_lines)
            original_credit[1] = f"Processing: {processing_original}. No gap filling."
            original_job = {
                "image": final_img.updateMask(original_mask),
                "vis_params": vis_params_gee,
                "target_px": target_px,
                "render_kwargs": {
                    **render_kwargs,
                    "lulc_legend": legend_without_shares,
                    "credit_lines": original_credit,
                    "stats_lines": [f"Valid data over {gap_fill['original_percent']:.0f}% of region",
                                    "(no gap filling)"] if stats_lines else None,
                },
            }
        status_render.update(label="Cartographic layout rendered", state="complete")

        # A continuous map can be given another colour ramp and legend range
        # later: its values are prepared for download on the picture's grid.
        restyle_job = None
        if not is_rgb and not is_categorical and vis_params_gee.get("palette"):
            restyle_job = prepare_restyle(
                [p["image"] for p in panels] if panels else [final_img], value_band, extent, projection["crs"],
                panel_pils[0].size if panels else map_pil.size, render_kwargs,
                panels=[{"label": p["label"], "note": p.get("note")} for p in panels] if panels else None,
                layout=layout if panels else None)

        # GeoTIFF of the data itself: real values (or the dataset's class
        # codes), in the map projection. Only the link is prepared here; the
        # file is downloaded when the user asks for it.
        export_img = clip_to_region(class_img) if is_categorical else final_img.toFloat()
        if panels:
            # One band per map (three for colour composites), named after it.
            out_bands = vis_params_gee["bands"] if is_rgb else [None]
            export_img = ee.Image.cat([
                (clip_to_region(class_codes(p["raw"])) if is_categorical
                 else p["image"].select(vis_params_gee["bands"] if is_rgb else [value_band]).toFloat()
                 ).rename(["_".join(filter(None, (re.sub(r"[^A-Za-z0-9]+", "_", ascii_label(p["label"])).strip("_"), b)))
                           for b in out_bands])
                for p in panels])
        geotiff = geotiff_download(
            export_img, extent, projection, n_bands=(3 if is_rgb else 1) * max(len(panels), 1),
            native_scale_m=(meta or {}).get("gsd"),
            lat_mid=(geo_bounds["lat_min"] + geo_bounds["lat_max"]) / 2.0)

        # Keep the finished map in the session: Streamlit reruns this script on
        # every click (including "Download"), and the map must survive that.
        suffix = (f"_{series_kind}" if panels else "") + ("_cloudmasked" if cloud_removal_applied else "")
        result_data = {
            "png_bytes":  rendered["png"],
            "pdf_bytes":  rendered["pdf"],
            "stats":      stats,
            "stats_csv":  stats_to_csv(stats, {
                "Map": ascii_label(title_label), "Region": ascii_label(region_name),
                "Dataset": f"{ascii_label(dataset_title)} ({cid})",
                "Period": subtitle or "", "Values": ascii_label(display_label),
            }) if stats else None,
            "value_label": ascii_label(display_label),
            "geotiff":    geotiff,
            "gap_fill":   gap_fill,
            "title":      ascii_label(render_kwargs["title"]),
            "period":     subtitle or "",
            "dataset_title": ascii_label(dataset_title),
            "provider":   (meta or {}).get("provider", ""),
            "dataset_coverage": (f"{meta['date_start']} to {meta['date_end']}" if meta and meta.get("date_start") else ""),
            "resolution_m": (meta or {}).get("gsd"),
            "bands":      bands,
            "projection": projection["name"],
            "processing": processing,
            "agent":      params,
            "is_rgb":     is_rgb,
            "original_job": original_job,
            "restyle":    restyle_job,
            # The style the map was made with: colour ramp and legend range.
            "style":      ({"palette": list(vis_params_gee["palette"]), "min": float(vis_params_gee.get("min", 0)),
                            "max": float(vis_params_gee.get("max", 1))} if restyle_job else None),
            "map_label":  ascii_label(map_label),
            "region":     ascii_label(region_name),
            "n_images":   n_images,
            "engine":     engine_lbl,
            "collection": cid,
            "cloud_removal_applied": cloud_removal_applied,
            "file_name":  f"{ascii_label(map_label)}_{ascii_label(region_name).replace(' ','_')}_{date_start[:4]}{suffix}.png",
            "index_info": None,
            "cloud_mask_desc": cloud_mask_desc,
            # Multi-map figures: the kind of series and its maps, in reading order.
            "series":     series_kind if panels else ("annual_climatology" if annual_ranges else None),
            "panels":     [{"label": ascii_label(p["label"]), "images": p["n_images"]} for p in panels],
            "grid":       f"{layout['cols']} x {layout['rows']}" if panels else None,
        }
        if map_type == "SPYNDEX" and SPYNDEX_AVAILABLE and index_name in spyndex.indices:
            idx_info = spyndex.indices[index_name]
            result_data["index_info"] = {
                "name": index_name, "long_name": idx_info.long_name,
                "formula": idx_info.formula, "domain": idx_info.application_domain,
                "bands": list(idx_info.bands), "reference": idx_info.reference,
                "available_bands": col_info["bands"], "band_override": band_override,
            }
        return result_data

    except Exception as e:
        ui.error(f"Map generation failed: {e}")
        ui.info(
            "Tips:\n"
            "- Cloudy tropical regions - prefer MODIS or Landsat over Sentinel-2\n"
            "- Check that spyndex is installed: pip install spyndex\n"
            "- Try expanding the date range for more images\n"
            "- Some indices require bands not present in every dataset\n"
            "- If cloud removal left no valid pixels, try a longer date range\n"
            "- For unlisted datasets, verify the collection ID in the GEE catalog"
        )

    return None

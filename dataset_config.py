"""
dataset_config.py
-----------------
Static lookup tables for GEE datasets:
  - Band role maps (spectral role -> actual band name per collection)
  - Scale / offset config per sensor type
  - Dataset-to-sensor mapping
  - Collection ID aliases (legacy -> canonical)
  - Cloud-cover metadata property names
  - Known static (non-temporal) datasets
  - LULC class schemas, keywords, and band lookup
"""

import ee
import streamlit as st

# ---------------------------------------------------------------------------
# Spyndex variable -> spectral role
# ---------------------------------------------------------------------------

SPYNDEX_VAR_ROLE: dict[str, str] = {
    "A": "coastal", "B": "blue",   "G": "green",  "R": "red",
    "RE1": "red_edge1", "RE2": "red_edge2", "RE3": "red_edge3",
    "N":  "nir",   "N2": "nir_narrow",
    "S1": "swir1", "S2": "swir2",
    "T1": "thermal1", "T2": "thermal2",
    "VV": "vv", "VH": "vh", "HH": "hh", "HV": "hv",
}

# ---------------------------------------------------------------------------
# Per-collection band role maps
# ---------------------------------------------------------------------------

DATASET_BAND_MAP: dict[str, dict] = {
    "COPERNICUS/S2_SR_HARMONIZED": {
        "coastal": "B1", "blue": "B2", "green": "B3", "red": "B4",
        "red_edge1": "B5", "red_edge2": "B6", "red_edge3": "B7",
        "nir": "B8", "nir_narrow": "B8A", "swir1": "B11", "swir2": "B12",
    },
    "COPERNICUS/S2_HARMONIZED": {
        "coastal": "B1", "blue": "B2", "green": "B3", "red": "B4",
        "nir": "B8", "nir_narrow": "B8A", "swir1": "B11", "swir2": "B12",
    },
    "LANDSAT/LC09/C02/T1_L2": {
        "coastal": "SR_B1", "blue": "SR_B2", "green": "SR_B3", "red": "SR_B4",
        "nir": "SR_B5", "swir1": "SR_B6", "swir2": "SR_B7", "thermal1": "ST_B10",
    },
    "LANDSAT/LC08/C02/T1_L2": {
        "coastal": "SR_B1", "blue": "SR_B2", "green": "SR_B3", "red": "SR_B4",
        "nir": "SR_B5", "swir1": "SR_B6", "swir2": "SR_B7", "thermal1": "ST_B10",
    },
    "LANDSAT/LE07/C02/T1_L2": {
        "blue": "SR_B1", "green": "SR_B2", "red": "SR_B3",
        "nir": "SR_B4", "swir1": "SR_B5", "swir2": "SR_B7",
    },
    "LANDSAT/LT05/C02/T1_L2": {
        "blue": "SR_B1", "green": "SR_B2", "red": "SR_B3",
        "nir": "SR_B4", "swir1": "SR_B5", "swir2": "SR_B7",
    },
    "MODIS/061/MOD09GA": {
        "red": "sur_refl_b01", "nir": "sur_refl_b02",
        "blue": "sur_refl_b03", "green": "sur_refl_b04",
        "swir1": "sur_refl_b06", "swir2": "sur_refl_b07",
    },
    "NOAA/VIIRS/001/VNP09GA": {
        "red": "I1", "nir": "I2", "swir1": "I3",
        "blue": "M3", "green": "M4",
    },
    "COPERNICUS/S1_GRD":                         {"vv": "VV", "vh": "VH"},
    "JAXA/ALOS/PALSAR/YEARLY/SAR":               {"hh": "HH", "hv": "HV"},
    "JAXA/ALOS/PALSAR-2/Level2_2/ScanSAR":       {"hh": "HH", "hv": "HV"},
}

# ---------------------------------------------------------------------------
# Scale / offset configs
# ---------------------------------------------------------------------------

SCALE_CONFIG: dict[str, dict] = {
    "sentinel2":      {"factor": 0.0001,    "offset": 0.0},
    "sentinel2_toa":  {"factor": 0.0001,    "offset": 0.0},
    "landsat_c2":     {"factor": 0.0000275, "offset": -0.2},
    "landsat_c2_etm": {"factor": 0.0000275, "offset": -0.2},
    "landsat_c2_tm":  {"factor": 0.0000275, "offset": -0.2},
    "modis_sr":       {"factor": 0.0001,    "offset": 0.0},
    "viirs_sr":       {"factor": 0.0001,    "offset": 0.0},
    "sar":            {"factor": 1.0,       "offset": 0.0},
    "s1_sar":         {"factor": 1.0,       "offset": 0.0},
    "generic":        {"factor": 1.0,       "offset": 0.0},
}

DATASET_SENSOR: dict[str, str] = {
    "COPERNICUS/S2_SR_HARMONIZED": "sentinel2",
    "COPERNICUS/S2_HARMONIZED":    "sentinel2_toa",
    "LANDSAT/LC09/C02/T1_L2":      "landsat_c2",
    "LANDSAT/LC08/C02/T1_L2":      "landsat_c2",
    "LANDSAT/LE07/C02/T1_L2":      "landsat_c2_etm",
    "LANDSAT/LT05/C02/T1_L2":      "landsat_c2_tm",
    "MODIS/061/MOD09GA":           "modis_sr",
    "NOAA/VIIRS/001/VNP09GA":      "viirs_sr",
    "COPERNICUS/S1_GRD":           "s1_sar",
    "JAXA/ALOS/PALSAR/YEARLY/SAR": "sar",
    "JAXA/ALOS/PALSAR-2/Level2_2/ScanSAR": "sar",
}

COLLECTION_ALIASES: dict[str, str] = {
    "LANDSAT/LC08/C01/T1_L2":  "LANDSAT/LC08/C02/T1_L2",
    "LANDSAT/LC08/C01/T1_SR":  "LANDSAT/LC08/C02/T1_L2",
    "LANDSAT/LC09/C01/T1_L2":  "LANDSAT/LC09/C02/T1_L2",
    "LANDSAT/LE07/C01/T1_L2":  "LANDSAT/LE07/C02/T1_L2",
    "LANDSAT/LT05/C01/T1_L2":  "LANDSAT/LT05/C02/T1_L2",
    "COPERNICUS/S2_SR":         "COPERNICUS/S2_SR_HARMONIZED",
    "COPERNICUS/S2":            "COPERNICUS/S2_HARMONIZED",
    "MODIS/006/MOD13Q1":        "MODIS/061/MOD13Q1",
    "MODIS/006/MCD12Q1":        "MODIS/061/MCD12Q1",
    "MODIS/006/MOD11A2":        "MODIS/061/MOD11A2",
    "MODIS/061/MOD16A2":        "MODIS/061/MOD16A2GF",
}

CLOUD_PROP: dict[str, str] = {
    "COPERNICUS/S2_SR_HARMONIZED": "CLOUDY_PIXEL_PERCENTAGE",
    "COPERNICUS/S2_HARMONIZED":    "CLOUDY_PIXEL_PERCENTAGE",
    "LANDSAT/LC09/C02/T1_L2":      "CLOUD_COVER",
    "LANDSAT/LC08/C02/T1_L2":      "CLOUD_COVER",
    "LANDSAT/LE07/C02/T1_L2":      "CLOUD_COVER",
    "LANDSAT/LT05/C02/T1_L2":      "CLOUD_COVER",
}

KNOWN_STATIC_DATASETS: set[str] = {
    "USGS/SRTMGL1_003", "COPERNICUS/DEM/GLO30", "NASA/NASADEM_HGT/001",
    "JAXA/ALOS/AW3D30/V3_2", "ESA/WorldCover/v200", "ESA/WorldCover/v100",
    "COPERNICUS/Landcover/100m/Proba-V-C3/Global",
    "UMD/hansen/global_forest_change_2023_v1_11",
    "NASA/ORNL/biomass_carbon_density/v1", "JAXA/GEDI_TCH_V2",
    "JRC/GSW1_4/GlobalSurfaceWater",
}

# ---------------------------------------------------------------------------
# LULC schemas, keywords, and band names
# ---------------------------------------------------------------------------

# ESA WorldCover ships two product versions - v100 (2020 map) and v200 (2021 map).
# Both use the identical 11-class legend (same class codes and colors); only the
# underlying imagery year and retrieval algorithm differ. Define it once, reuse
# for both collection IDs so they never drift out of sync with each other.
_ESA_WORLDCOVER_CLASSES: dict = {
    10:  {"label": "Trees",         "color": "#025702"},
    20:  {"label": "Shrubland",     "color": "#FFBB22"},
    30:  {"label": "Grassland",     "color": "#FFFF4C"},
    40:  {"label": "Cropland",      "color": "#5BDA0C"},
    50:  {"label": "Built-up",      "color": "#FA0000"},
    60:  {"label": "Bare/Sparse",   "color": "#B4B4B4"},
    70:  {"label": "Snow/Ice",      "color": "#F0F0F0"},
    80:  {"label": "Open Water",    "color": "#0064C8"},
    90:  {"label": "Wetland",       "color": "#0EDDE4"},
    95:  {"label": "Mangroves",     "color": "#E70FC3"},
    100: {"label": "Moss/Lichen",   "color": "#FAE6A0"},
}

LULC_CLASS_SCHEMAS: dict[str, dict] = {
    "ESA/WorldCover/v200": _ESA_WORLDCOVER_CLASSES,
    "ESA/WorldCover/v100": _ESA_WORLDCOVER_CLASSES,
    "MODIS/061/MCD12Q1": {
        1:  {"label": "Evergreen Needleleaf",  "color": "#05450A"},
        2:  {"label": "Evergreen Broadleaf",   "color": "#086A10"},
        3:  {"label": "Deciduous Needleleaf",  "color": "#54A708"},
        4:  {"label": "Deciduous Broadleaf",   "color": "#78D203"},
        5:  {"label": "Mixed Forest",          "color": "#009900"},
        6:  {"label": "Closed Shrubland",      "color": "#C6B044"},
        7:  {"label": "Open Shrubland",        "color": "#DCD159"},
        8:  {"label": "Woody Savanna",         "color": "#DCD159"},
        9:  {"label": "Savanna",               "color": "#FBD040"},
        10: {"label": "Grassland",             "color": "#CE7233"},
        11: {"label": "Permanent Wetland",     "color": "#D4E792"},
        12: {"label": "Cropland",              "color": "#F0FF00"},
        13: {"label": "Urban",                 "color": "#C24F44"},
        14: {"label": "Crop/Natural Mosaic",   "color": "#A5A5A5"},
        15: {"label": "Snow/Ice",              "color": "#FFFFFF"},
        16: {"label": "Barren",                "color": "#F5F5F5"},
        17: {"label": "Water",                 "color": "#0046C8"},
    },
    "COPERNICUS/Landcover/100m/Proba-V-C3/Global": {
        0:   {"label": "Unknown",              "color": "#282828"},
        20:  {"label": "Shrubland",            "color": "#FFBB22"},
        30:  {"label": "Herbaceous",           "color": "#FFFF4C"},
        40:  {"label": "Cropland",             "color": "#F096FF"},
        50:  {"label": "Urban",                "color": "#FA0000"},
        60:  {"label": "Bare/Sparse",          "color": "#B4B4B4"},
        70:  {"label": "Snow/Ice",             "color": "#F0F0F0"},
        80:  {"label": "Water",                "color": "#0032C8"},
        90:  {"label": "Wetland",              "color": "#0096A0"},
        100: {"label": "Moss/Lichen",          "color": "#FAE6A0"},
        111: {"label": "Closed Evergreen Needle Forest", "color": "#003C00"},
        112: {"label": "Closed Evergreen Broad Forest",  "color": "#003C00"},
        121: {"label": "Open Evergreen Needle Forest",   "color": "#006400"},
        122: {"label": "Open Evergreen Broad Forest",    "color": "#006400"},
        125: {"label": "Open Mixed Forest",              "color": "#96BE82"},
    },
}

LULC_CLASS_KEYWORDS: dict[str, dict] = {
    "crop":       {"ESA/WorldCover/v200": [40], "ESA/WorldCover/v100": [40], "MODIS/061/MCD12Q1": [12, 14], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [40]},
    "agriculture":{"ESA/WorldCover/v200": [40], "ESA/WorldCover/v100": [40], "MODIS/061/MCD12Q1": [12, 14], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [40]},
    "cropland":   {"ESA/WorldCover/v200": [40], "ESA/WorldCover/v100": [40], "MODIS/061/MCD12Q1": [12, 14], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [40]},
    "farmland":   {"ESA/WorldCover/v200": [40], "ESA/WorldCover/v100": [40], "MODIS/061/MCD12Q1": [12, 14], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [40]},
    "forest":     {"ESA/WorldCover/v200": [10], "ESA/WorldCover/v100": [10], "MODIS/061/MCD12Q1": [1,2,3,4,5], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [111,112,121,122,125]},
    "water":      {"ESA/WorldCover/v200": [80], "ESA/WorldCover/v100": [80], "MODIS/061/MCD12Q1": [17], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [80]},
    "urban":      {"ESA/WorldCover/v200": [50], "ESA/WorldCover/v100": [50], "MODIS/061/MCD12Q1": [13], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [50]},
    "built":      {"ESA/WorldCover/v200": [50], "ESA/WorldCover/v100": [50], "MODIS/061/MCD12Q1": [13], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [50]},
    "grass":      {"ESA/WorldCover/v200": [30], "ESA/WorldCover/v100": [30], "MODIS/061/MCD12Q1": [10], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [30]},
    "shrub":      {"ESA/WorldCover/v200": [20], "ESA/WorldCover/v100": [20], "MODIS/061/MCD12Q1": [6,7], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [20]},
    "wetland":    {"ESA/WorldCover/v200": [90], "ESA/WorldCover/v100": [90], "MODIS/061/MCD12Q1": [11], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [90]},
    "bare":       {"ESA/WorldCover/v200": [60], "ESA/WorldCover/v100": [60], "MODIS/061/MCD12Q1": [16], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [60]},
    "snow":       {"ESA/WorldCover/v200": [70], "ESA/WorldCover/v100": [70], "MODIS/061/MCD12Q1": [15], "COPERNICUS/Landcover/100m/Proba-V-C3/Global": [70]},
    "mangrove":   {"ESA/WorldCover/v200": [95], "ESA/WorldCover/v100": [95], "MODIS/061/MCD12Q1": [],   "COPERNICUS/Landcover/100m/Proba-V-C3/Global": []},
}

LULC_BAND_LUT: dict[str, str] = {
    "ESA/WorldCover/v200":                         "Map",
    "ESA/WorldCover/v100":                         "Map",
    "MODIS/061/MCD12Q1":                           "LC_Type1",
    "COPERNICUS/Landcover/100m/Proba-V-C3/Global": "discrete_classification",
}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def detect_lulc_class_filter(prompt: str, cid: str) -> list[int]:
    """Parse user prompt for LULC class filter keywords. Returns class IDs or []."""
    lower = prompt.lower()
    for keyword, dataset_map in LULC_CLASS_KEYWORDS.items():
        if keyword in lower:
            return dataset_map.get(cid, [])
    return []


def apply_lulc_class_filter(img: ee.Image, lc_band: str, class_values: list[int]) -> ee.Image:
    """Mask all pixels whose land-cover value is NOT in class_values."""
    if not class_values:
        return img
    lc = img.select(lc_band)
    mask = lc.eq(class_values[0])
    for v in class_values[1:]:
        mask = mask.Or(lc.eq(v))
    return img.updateMask(mask)


def build_lulc_class_legend(cid: str, class_values: list[int]) -> list[dict]:
    """Return [{label, color}] for the given class_values and collection."""
    schema = LULC_CLASS_SCHEMAS.get(cid, {})
    legend = [{"label": schema[v]["label"], "color": schema[v]["color"]}
              for v in class_values if v in schema]
    if not legend and class_values:
        legend.append({"label": f"Class {class_values}", "color": "#F096FF"})
    return legend


def full_lulc_legend(cid: str) -> list[dict]:
    """Return the full class legend for a LULC collection (all classes)."""
    schema = LULC_CLASS_SCHEMAS.get(cid, {})
    return [{"label": v["label"], "color": v["color"]} for v in schema.values()]


def lulc_classes_for_display(cid: str, class_values: list[int] | None = None) -> list[int]:
    """Return ordered LULC class values to draw."""
    schema = LULC_CLASS_SCHEMAS.get(cid, {})
    if class_values:
        return [v for v in class_values if v in schema]
    return list(schema.keys())


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(round(min(max(c, 0), 255)) for c in rgb))


def generic_discrete_legend(
    img: "ee.Image", band: str, region_geom, palette: list[str],
    vmin: float, vmax: float, max_classes: int = 15,
) -> list[dict]:
    """
    Build a discrete class legend for a categorical band whose collection ID
    is NOT in LULC_CLASS_SCHEMAS - e.g. a land-cover dataset the live catalog
    search surfaced that we don't have a hand-authored class list for yet.

    Reads the ACTUAL distinct pixel values present in the AOI and colors each
    swatch by sampling the same continuous palette used to render the map, so
    legend colors always match what's on the map. Labels are generic
    ("Class 10") since the true class names aren't known for an unregistered
    dataset - still far better than a continuous colorbar on categorical data.

    Returns [] on any failure (network hiccup, empty region, etc.) so callers
    can fall back gracefully rather than crashing the map generation.
    """
    if not palette:
        return []
    try:
        hist = (
            img.select(band)
            .reduceRegion(
                reducer=ee.Reducer.frequencyHistogram(),
                geometry=region_geom,
                scale=100,
                bestEffort=True,
                maxPixels=1e9,
            )
            .get(band)
            .getInfo()
        )
    except Exception:
        return []

    if not hist:
        return []

    values = sorted(float(v) for v in hist.keys())[:max_classes]
    if not values:
        return []

    span = max(vmax - vmin, 1e-9)
    n = len(palette) - 1
    legend = []
    for v in values:
        t = min(max((v - vmin) / span, 0.0), 1.0)
        idx = t * n
        lo, hi = int(idx), min(int(idx) + 1, n)
        frac = idx - lo
        c0, c1 = _hex_to_rgb(palette[lo]), _hex_to_rgb(palette[hi])
        blended = tuple(c0[i] + (c1[i] - c0[i]) * frac for i in range(3))
        legend.append({"label": f"Class {int(v)}", "color": _rgb_to_hex(blended)})
    return legend


def lulc_vis_for_classes(cid: str, class_values: list[int]) -> dict:
    """Build discrete visualization params after class remapping."""
    schema = LULC_CLASS_SCHEMAS.get(cid, {})
    palette = [schema[v]["color"] for v in class_values if v in schema]
    if not palette:
        palette = ["#006400","#FFBB22","#FFFF4C","#F096FF","#FA0000","#B4B4B4","#0064C8"]
    return {
        "min": 0,
        "max": max(len(palette) - 1, 1),
        "palette": palette,
        "bands": ["LANDCOVER"],
        "label": "Land Use / Land Cover",
    }


@st.cache_data(ttl=3600, show_spinner=False)
def introspect_collection(cid: str) -> dict:
    """Query GEE at runtime to determine band names, cloud property, and static/dynamic status."""
    result = {"is_image_collection": True, "bands": [], "cloud_prop": None, "is_static": False, "error": None}
    try:
        col  = ee.ImageCollection(cid).limit(2)
        size = col.size().getInfo()
        if size == 0:
            raise ValueError("Empty collection")
        first = col.first()
        result["is_image_collection"] = True
        result["bands"] = first.bandNames().getInfo()
        props = first.propertyNames().getInfo()
        if "system:time_start" not in props:
            result["is_static"] = True
        for prop in ("CLOUDY_PIXEL_PERCENTAGE", "CLOUD_COVER",
                     "CLOUD_COVER_LAND", "cloud_fraction", "CLOUD_SHADOW_PERCENTAGE"):
            if prop in props:
                result["cloud_prop"] = prop
                break
    except Exception:
        try:
            img = ee.Image(cid)
            result["bands"] = img.bandNames().getInfo()
            result["is_image_collection"] = False
            result["is_static"] = True
        except Exception as exc:
            result["error"] = str(exc)
    return result


def get_dataset_band_map(cid: str, band_override: dict, col_info: dict) -> dict:
    """Build a role->band_name mapping for cid."""
    if cid in DATASET_BAND_MAP:
        base = dict(DATASET_BAND_MAP[cid])
    else:
        base = {}
        bands = col_info.get("bands", [])
        heuristics = {
            "red": ["B4","SR_B4","sur_refl_b01","I1","Red","red"],
            "green": ["B3","SR_B3","sur_refl_b04","M4","Green","green"],
            "blue": ["B2","SR_B2","sur_refl_b03","M3","Blue","blue"],
            "nir": ["B8","SR_B5","sur_refl_b02","I2","NIR","nir"],
            "nir_narrow": ["B8A"],
            "swir1": ["B11","SR_B6","sur_refl_b06","I3","SWIR1","swir1"],
            "swir2": ["B12","SR_B7","sur_refl_b07","SWIR2","swir2"],
            "coastal": ["B1","SR_B1","coastal"],
            "red_edge1": ["B5","RE1"],
            "red_edge2": ["B6","RE2"],
            "red_edge3": ["B7","RE3"],
            "thermal1": ["ST_B10","B10","TIR1"],
            "vv": ["VV","vv"], "vh": ["VH","vh"],
            "hh": ["HH","hh"], "hv": ["HV","hv"],
        }
        band_set = set(bands)
        for role, candidates in heuristics.items():
            for c in candidates:
                if c in band_set:
                    base[role] = c
                    break
    for key, band in (band_override or {}).items():
        role = SPYNDEX_VAR_ROLE.get(key, key.lower())
        base[role] = band
    return base


def get_scale_config(cid: str, agent_scale_f: float, agent_scale_o: float) -> dict:
    """Return scale/offset. Known collections use hardcoded values; others use agent-supplied."""
    sensor = DATASET_SENSOR.get(cid, "generic")
    cfg    = SCALE_CONFIG.get(sensor)
    return cfg if cfg else {"factor": agent_scale_f, "offset": agent_scale_o}


def resolve_is_static(cid: str, col_info: dict, agent_is_temporal: bool) -> bool:
    if cid in KNOWN_STATIC_DATASETS or not agent_is_temporal:
        return True
    return col_info.get("is_static", False)


def detect_cloud_prop(cid: str, col_info: dict) -> str | None:
    if cid in CLOUD_PROP:
        return CLOUD_PROP[cid]
    return col_info.get("cloud_prop")


def is_sar_collection(cid: str) -> bool:
    return DATASET_SENSOR.get(cid, "generic") in ("sar", "s1_sar")


def auto_vis_params(img: ee.Image, band: str, region_geom, percentile: int = 2) -> dict:
    """Compute min/max from image percentiles for auto-ranging."""
    try:
        stats = img.select(band).reduceRegion(
            reducer=ee.Reducer.percentile([percentile, 100 - percentile]),
            geometry=region_geom,
            scale=500,
            maxPixels=1e8,
            bestEffort=True,
        ).getInfo()
        lo = stats.get(f"{band}_p{percentile}", 0)
        hi = stats.get(f"{band}_p{100 - percentile}", 1)
        return {"min": lo or 0, "max": hi or 1}
    except Exception:
        return {"min": 0, "max": 1}

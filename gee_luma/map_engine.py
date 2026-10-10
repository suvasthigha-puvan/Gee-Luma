"""
map_engine.py
-------------
GEE image computation:
  - compute_spyndex_on_gee(): compute any spyndex spectral index
  - compute_special_map(): compute non-spyndex map types (RGB, LULC, LST, etc.)
"""

import ee
try:
    import spyndex
    SPYNDEX_AVAILABLE = True
except ImportError:
    SPYNDEX_AVAILABLE = False

from gee_luma.dataset_config import (
    SPYNDEX_VAR_ROLE, LULC_BAND_LUT,
    is_sar_collection, lulc_classes_for_display,
    apply_lulc_class_filter, lulc_vis_for_classes, auto_vis_params,
)
from gee_luma.palettes import get_palette, INDEX_PALETTES

# ====================== SPYNDEX INDEX COMPUTATION ======================

def compute_spyndex_on_gee(img, cid, index_name, band_map, scale_cfg, band_override=None):
    """
    Compute a spyndex index on a GEE image.
    band_map and scale_cfg are pre-resolved by the caller, so this works
    for any collection  both known and unknown.
    """
    if not SPYNDEX_AVAILABLE or index_name not in spyndex.indices:
        return None
    idx_info = spyndex.indices[index_name]
    formula  = idx_info.formula
    required = list(idx_info.bands)
    sf, offset = scale_cfg["factor"], scale_cfg["offset"]
    sar = is_sar_collection(cid)
    expr_map = {}
    def _prepared(band_name, var):
        b = img.select(band_name)
        if sar:
            return b
        b = b.multiply(sf).add(offset)
        if var not in ("T1", "T2"):
            # Surface reflectance cannot be negative, but atmospheric correction
            # produces slightly negative values over water and deep shadow.
            # Left in, they make ratio indices explode: with N + R close to
            # zero, (N - R) / (N + R) reaches hundreds or thousands instead of
            # staying within -1..1.
            b = b.max(0)
        return b

    for var in required:
        if band_override and var in band_override:
            expr_map[var] = _prepared(band_override[var], var)
            continue
        # 2. Role-based lookup in band_map
        role = SPYNDEX_VAR_ROLE.get(var)
        if role and role in band_map:
            expr_map[var] = _prepared(band_map[role], var)
            continue
        # 3. Spyndex constant
        if var in spyndex.constants:
            expr_map[var] = float(spyndex.constants[var].default)
            continue
        return None
    return img.expression(formula, expr_map).rename(index_name)


# ====================== SPECIAL MAP TYPE COMPUTATION ======================

# Candidate band names per map type, in order of preference. Different
# datasets for the same theme name the band differently (e.g. WorldPop
# "population" vs GPW "population_density"), so the first one actually
# present in the dataset is used.
_SPECIAL_BAND_CANDIDATES: dict[str, list[str]] = {
    "WATER":         ["occurrence"],
    "SOIL_MOISTURE": ["sm_surface", "ssm", "volumetric_soil_water_layer_1", "soil"],
    "TREECOVER":     ["treecover2000"],
    "FOREST_LOSS":   ["loss"],
    "BIOMASS":       ["agb"],
    "CANOPY_HEIGHT": ["canopy_height"],
    "FIRE":          ["FireMask"],
    "NO2":           ["tropospheric_NO2_column_number_density", "NO2_column_number_density"],
    "CO":            ["CO_column_number_density"],
    "AEROSOL":       ["absorbing_aerosol_index"],
    "CH4":           ["CH4_column_volume_mixing_ratio_dry_air"],
    "SO2":           ["SO2_column_number_density"],
    "POPULATION":    ["population_density", "population"],
}


def _pick_band(candidates, available_bands=None, preferred_band=None):
    """Choose the band to display: agent's choice, else first known candidate present."""
    available = list(available_bands or [])
    if preferred_band and (not available or preferred_band in available):
        return preferred_band
    for c in candidates:
        if c in available:
            return c
    if available:
        return available[0]
    return candidates[0]


def compute_special_map(img, map_type, cid, band_map, scale_cfg, lulc_class_values=None,
                        available_bands=None, preferred_band=None):
    """
    Compute non-spyndex map types.
    band_map and scale_cfg are pre-resolved so unknown collections work.
    lulc_class_values: optional list of int class values to keep (LANDCOVER only).
    available_bands: band names actually present in the dataset (from introspection).
    preferred_band: band the agent asked for, used when it exists in the dataset.
    """
    sf, offset = scale_cfg["factor"], scale_cfg["offset"]
    sar = is_sar_collection(cid)

    def scaled(band_name):
        b = img.select(band_name)
        if not sar and map_type not in ("ELEVATION", "SLOPE", "ASPECT", "HILLSHADE"):
            b = b.multiply(sf).add(offset)
        return b

    # Elevation band name differs between DEM products.
    elev_band = _pick_band(["elevation", "DEM", "DSM", "AVE_DSM", "b1"], available_bands, preferred_band)

    if map_type == "RGB":
        r  = scaled(band_map.get("red",   "B4"))
        g  = scaled(band_map.get("green", "B3"))
        b_ = scaled(band_map.get("blue",  "B2"))
        return ee.Image.cat([r, g, b_]).rename(["R","G","B"]), {"min":0,"max":0.3,"bands":["R","G","B"]}

    elif map_type == "FALSE_COLOR":
        n = scaled(band_map.get("nir",   "B8"))
        r = scaled(band_map.get("red",   "B4"))
        g = scaled(band_map.get("green", "B3"))
        return ee.Image.cat([n, r, g]).rename(["N","R","G"]), {"min":0,"max":0.5,"bands":["N","R","G"]}

    elif map_type == "SWIR":
        s2 = scaled(band_map.get("swir2", "B12"))
        s1 = scaled(band_map.get("swir1", "B11"))
        r  = scaled(band_map.get("red",   "B4"))
        return ee.Image.cat([s2, s1, r]).rename(["S2","S1","R"]), {"min":0,"max":0.5,"bands":["S2","S1","R"]}

    elif map_type == "SAR_RGB":
        vv    = img.select(band_map.get("vv", "VV"))
        vh    = img.select(band_map.get("vh", "VH"))
        # Backscatter is in dB (logarithmic), so the VV/VH ratio is a difference.
        ratio = vv.subtract(vh).rename("ratio")
        return ee.Image.cat([vv, vh, ratio]).rename(["VV","VH","VVdVH"]), {"min":-25,"max":5,"bands":["VV","VH","VVdVH"]}

    elif map_type == "ELEVATION":
        return img.select(elev_band).rename("ELEVATION"), {**get_palette("ELEVATION"), "bands":["ELEVATION"]}

    elif map_type == "SLOPE":
        return ee.Terrain.slope(img.select(elev_band)).rename("SLOPE"), {**get_palette("SLOPE"), "bands":["SLOPE"]}

    elif map_type == "ASPECT":
        return ee.Terrain.aspect(img.select(elev_band)).rename("ASPECT"), {**get_palette("ASPECT"), "bands":["ASPECT"]}

    elif map_type == "HILLSHADE":
        return ee.Terrain.hillshade(img.select(elev_band)).rename("HILLSHADE"), {**get_palette("HILLSHADE"), "bands":["HILLSHADE"]}

    elif map_type == "LST":
        return img.select("LST_Day_1km").multiply(0.02).rename("LST"), {**get_palette("LST"), "bands":["LST"]}

    elif map_type == "NIGHTLIGHTS":
        rad_band = "avg_rad" if "VIIRS" in cid else "avg_vis"
        return img.select(rad_band).rename("NIGHTLIGHTS"), {**get_palette("NIGHTLIGHTS"), "bands":["NIGHTLIGHTS"]}

    elif map_type == "LANDCOVER":
        lc_band = LULC_BAND_LUT.get(cid, "Map")
        lc_img  = img.select(lc_band).rename("LANDCOVER")
        display_classes = lulc_classes_for_display(cid, lulc_class_values)
        if display_classes:
            if lulc_class_values:
                lc_img = apply_lulc_class_filter(lc_img, "LANDCOVER", display_classes)
            lc_img = lc_img.remap(display_classes, list(range(len(display_classes)))).rename("LANDCOVER")
            vis = lulc_vis_for_classes(cid, display_classes)
        else:
            vis = {**get_palette("LANDCOVER"), "bands": ["LANDCOVER"]}
        return lc_img, vis

    elif map_type == "PRECIPITATION":
        p_band = {"UCSB-CHG/CHIRPS/DAILY": "precipitation",
                  "NASA/GPM_L3/IMERG_V06": "precipitationCal",
                  "ECMWF/ERA5/DAILY": "total_precipitation"}.get(cid, "precipitation")
        return img.select(p_band).rename("PRECIPITATION"), {**get_palette("PRECIPITATION"), "bands":["PRECIPITATION"]}

    elif map_type == "TEMPERATURE":
        return img.select("maximum_2m_air_temperature").rename("TEMPERATURE"), {**get_palette("TEMPERATURE"), "bands":["TEMPERATURE"]}

    elif map_type in ("WATER","SOIL_MOISTURE","TREECOVER","FOREST_LOSS",
                      "BIOMASS","CANOPY_HEIGHT","FIRE","NO2","CO",
                      "AEROSOL","CH4","SO2","POPULATION"):
        band = _pick_band(_SPECIAL_BAND_CANDIDATES[map_type], available_bands, preferred_band)
        return img.select(band).rename(map_type), {**get_palette(map_type), "bands":[map_type]}

    else:
        raise ValueError(f"Unknown map_type: {map_type}")



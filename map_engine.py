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

from dataset_config import (
    SPYNDEX_VAR_ROLE, LULC_BAND_LUT,
    is_sar_collection, lulc_classes_for_display,
    apply_lulc_class_filter, lulc_vis_for_classes, auto_vis_params,
)
from palettes import get_palette, INDEX_PALETTES

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
    for var in required:
        if band_override and var in band_override:
            b = img.select(band_override[var])
            if not sar:
                b = b.multiply(sf).add(offset)
            expr_map[var] = b
            continue
        # 2. Role-based lookup in band_map
        role = SPYNDEX_VAR_ROLE.get(var)
        if role and role in band_map:
            b = img.select(band_map[role])
            if not sar:
                b = b.multiply(sf).add(offset)
            expr_map[var] = b
            continue
        # 3. Spyndex constant
        if var in spyndex.constants:
            expr_map[var] = float(spyndex.constants[var].default)
            continue
        return None
    return img.expression(formula, expr_map).rename(index_name)


# ====================== SPECIAL MAP TYPE COMPUTATION ======================

def compute_special_map(img, map_type, cid, band_map, scale_cfg, lulc_class_values=None):
    """
    Compute non-spyndex map types.
    band_map and scale_cfg are pre-resolved so unknown collections work.
    lulc_class_values: optional list of int class values to keep (LANDCOVER only).
    """
    sf, offset = scale_cfg["factor"], scale_cfg["offset"]
    sar = is_sar_collection(cid)

    def scaled(band_name):
        b = img.select(band_name)
        if not sar and map_type not in ("ELEVATION", "SLOPE", "ASPECT", "HILLSHADE"):
            b = b.multiply(sf).add(offset)
        return b

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
        ratio = vv.divide(vh).rename("ratio")
        return ee.Image.cat([vv, vh, ratio]).rename(["VV","VH","VVdVH"]), {"min":-25,"max":5,"bands":["VV","VH","VVdVH"]}

    elif map_type == "ELEVATION":
        elev_band = "DEM" if "GLO30" in cid else "elevation"
        return img.select(elev_band).rename("ELEVATION"), {**get_palette("ELEVATION"), "bands":["ELEVATION"]}

    elif map_type == "SLOPE":
        elev_band = "DEM" if "GLO30" in cid else "elevation"
        return ee.Terrain.slope(img.select(elev_band)).rename("SLOPE"), {**get_palette("SLOPE"), "bands":["SLOPE"]}

    elif map_type == "ASPECT":
        elev_band = "DEM" if "GLO30" in cid else "elevation"
        return ee.Terrain.aspect(img.select(elev_band)).rename("ASPECT"), {**get_palette("ASPECT"), "bands":["ASPECT"]}

    elif map_type == "HILLSHADE":
        elev_band = "DEM" if "GLO30" in cid else "elevation"
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
        p_band = {"UCSB-CHC/CHIRPS/DAILY": "precipitation",
                  "NASA/GPM_L3/IMERG_V06": "precipitationCal",
                  "ECMWF/ERA5/DAILY": "total_precipitation"}.get(cid, "precipitation")
        return img.select(p_band).rename("PRECIPITATION"), {**get_palette("PRECIPITATION"), "bands":["PRECIPITATION"]}

    elif map_type == "TEMPERATURE":
        return img.select("maximum_2m_air_temperature").rename("TEMPERATURE"), {**get_palette("TEMPERATURE"), "bands":["TEMPERATURE"]}

    elif map_type in ("WATER","SOIL_MOISTURE","TREECOVER","FOREST_LOSS",
                      "BIOMASS","CANOPY_HEIGHT","FIRE","NO2","CO",
                      "AEROSOL","CH4","SO2","POPULATION"):
        band_lut = {
            "WATER":        "occurrence",
    "SOIL_MOISTURE":{"min":0.0, "max":0.5, "palette":['#FF8C00','#FFD700','#ADFF2F','#006400','#00008B'],"label":"Soil Moisture (m3/m3)"},
            "TREECOVER":    "treecover2000",
            "FOREST_LOSS":  "loss",
            "BIOMASS":      "agb",
            "CANOPY_HEIGHT":"canopy_height",
            "FIRE":         "FireMask",
    "NO2":          {"min":0,   "max":0.0002,"palette":['#FFFFFF','#FFD700','#FF8C00','#FF0000','#8B0000'],"label":"NO2 (mol/m2)"},
    "CO":           {"min":0,   "max":0.05,"palette":['#FFFFFF','#FFD700','#FF4500','#8B0000'],"label":"CO (mol/m2)"},
            "AEROSOL":      "absorbing_aerosol_index",
    "CH4":          {"min":1700,"max":1900,"palette":['#000080','#4169E1','#00CED1','#ADFF2F','#FFFF00','#FF8C00','#FF0000'],"label":"CH4 (ppb)"},
    "SO2":          {"min":0,   "max":0.001,"palette":['#FFFFFF','#FFFF00','#FFA500','#FF0000'],"label":"SO2 (mol/m2)"},
    "POPULATION":   {"min":0,   "max":1000,"palette":['#FFFFE0','#FFD700','#FFA500','#FF4500','#8B0000'],"label":"Pop. Density (per km2)"},
        }
        band = band_lut.get(map_type, img.bandNames().get(0).getInfo())
        return img.select(band).rename(map_type), {**get_palette(map_type), "bands":[map_type]}

    else:
        raise ValueError(f"Unknown map_type: {map_type}")



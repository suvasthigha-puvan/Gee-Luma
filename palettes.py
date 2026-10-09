"""
palettes.py
-----------
Colour palette definitions for every supported map type and spectral index,
plus the PRECOMPUTED_PALETTE_MAP and the get_palette() helper.
"""

try:
    import spyndex
    _SPYNDEX_AVAILABLE = True
except ImportError:
    _SPYNDEX_AVAILABLE = False

INDEX_PALETTES = {
    "NDVI":   {"min":-1.0,"max":1.0, "palette":['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],"label":"NDVI"},
    "EVI":    {"min":-0.2,"max":1.0, "palette":['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],"label":"EVI"},
    "SAVI":   {"min":-0.5,"max":1.0, "palette":['#8B0000','#FF6347','#FFFF00','#7CFC00','#006400'],"label":"SAVI"},
    "GNDVI":  {"min":-0.2,"max":1.0, "palette":['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],"label":"GNDVI"},
    "NDRE":   {"min":-0.2,"max":1.0, "palette":['#8B0000','#FF6347','#FFFF00','#7CFC00','#006400'],"label":"NDRE"},
    "kNDVI":  {"min":-0.2,"max":1.0, "palette":['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],"label":"kNDVI"},
    "NDWI":   {"min":-1.0,"max":1.0, "palette":['#FF8C00','#FFFACD','#00BFFF','#0000CD'],"label":"NDWI"},
    "MNDWI":  {"min":-1.0,"max":1.0, "palette":['#FF8C00','#FFFACD','#00BFFF','#0000CD'],"label":"MNDWI"},
    "NBR":    {"min":-1.0,"max":1.0, "palette":['#006400','#ADFF2F','#FFFF00','#FF8C00','#8B0000'],"label":"NBR"},
    "NBR2":   {"min":-1.0,"max":1.0, "palette":['#006400','#ADFF2F','#FFFF00','#FF8C00','#8B0000'],"label":"NBR2"},
    "BAIS2":  {"min": 0.0,"max":5.0, "palette":['#FFFFFF','#FFFF00','#FFA500','#FF0000','#8B0000'],"label":"BAIS2"},
    "NDSI":   {"min":-1.0,"max":1.0, "palette":['#8B4513','#D2B48C','#FFFFFF','#ADD8E6','#0000CD'],"label":"NDSI"},
    "BSI":    {"min":-1.0,"max":1.0, "palette":['#006400','#FFFF00','#FF8C00','#8B4513','#3D1C02'],"label":"BSI"},
    "NDBI":   {"min":-1.0,"max":1.0, "palette":['#006400','#FFFFCC','#FFA500','#FF4500','#8B0000'],"label":"NDBI"},
    "SAR_RGB":{"min":-25, "max":5,   "palette":['#000000','#888888','#FFFFFF'],"label":"SAR dB"},
    "RVI":    {"min": 0.0,"max":1.0, "palette":['#FFFFFF','#90EE90','#006400'],"label":"RVI"},
    "RFDI":   {"min":-1.0,"max":1.0, "palette":['#0000CD','#FFFF00','#8B0000'],"label":"RFDI"},
    "ELEVATION":{"min":0,  "max":3000,"palette":['#006600','#FFFF00','#FF8C00','#8B4513','#FFFFFF'],"label":"Elevation (m)"},
    "SLOPE":    {"min":0,  "max":60,  "palette":['#FFFFFF','#A0A0A0','#404040','#000000'],"label":"Slope (deg)"},
    "ASPECT":   {"min":0,  "max":360, "palette":['#FF0000','#FFFF00','#00FF00','#00FFFF','#0000FF','#FF00FF','#FF0000'],"label":"Aspect (deg)"},
    "HILLSHADE":{"min":0,  "max":255, "palette":['#000000','#FFFFFF'],"label":"Hillshade"},
    "LANDCOVER":    {"min":0,   "max":100, "palette":['#006400','#FFBB22','#FFFF4C','#F096FF','#FA0000','#B4B4B4','#F0F0F0','#0064C8','#0096A0','#00CF75','#FAE6A0'],"label":"Land Cover"},
    "NIGHTLIGHTS":  {"min":0,   "max":60,  "palette":['#000000','#1A1A2E','#16213E','#0F3460','#533483','#E94560','#FFEB3B','#FFFFFF'],"label":"Radiance (nW/cm2/sr)"},
    "LST":          {"min":280, "max":320, "palette":['#040274','#0502CE','#0602FF','#235CB1','#269DB1','#3BE285','#86E26F','#FFF705','#FEDD09','#FDAD73','#DD4F2F','#AD2816'],"label":"LST (K)"},
    "PRECIPITATION":{"min":0,   "max":20,  "palette":['#FFFFFF','#C9C9C9','#ACD2EC','#3D8ECC','#3366AF','#1A339F','#041066'],"label":"Precipitation (mm/day)"},
    "TEMPERATURE":  {"min":250, "max":310, "palette":['#0000FF','#00FFFF','#00FF00','#FFFF00','#FF8C00','#FF0000'],"label":"Temperature (K)"},
    "WATER":        {"min":0,   "max":100, "palette":['#FFFFFF','#C9E8FF','#4499CC','#0000FF'],"label":"Water Occurrence (%)"},
    "SOIL_MOISTURE":{"min":0.0, "max":0.5, "palette":['#FF8C00','#FFD700','#ADFF2F','#006400','#00008B'],"label":"Soil Moisture (m3/m3)"},
    "TREECOVER":    {"min":0,   "max":100, "palette":['#FFFFE0','#ADFF2F','#228B22','#006400'],"label":"Tree Cover (%)"},
    "FOREST_LOSS":  {"min":0,   "max":1,   "palette":['#FFFFFF','#FF0000'],"label":"Forest Loss"},
    "BIOMASS":      {"min":0,   "max":200, "palette":['#FFFFE0','#ADFF2F','#228B22','#006400','#002800'],"label":"AGB (Mg C/ha)"},
    "CANOPY_HEIGHT":{"min":0,   "max":40,  "palette":['#FFFFFF','#ADFF2F','#228B22','#006400'],"label":"Canopy Height (m)"},
    "FIRE":         {"min":0,   "max":9,   "palette":['#FFFFFF','#FFFF00','#FFA500','#FF4500','#FF0000','#8B0000'],"label":"Fire Mask"},
    "NO2":          {"min":0,   "max":0.0002,"palette":['#FFFFFF','#FFD700','#FF8C00','#FF0000','#8B0000'],"label":"NO2 (mol/m2)"},
    "CO":           {"min":0,   "max":0.05,"palette":['#FFFFFF','#FFD700','#FF4500','#8B0000'],"label":"CO (mol/m2)"},
    "AEROSOL":      {"min":-1,  "max":5,   "palette":['#FFFFFF','#FFFF00','#FFA500','#FF0000','#800000'],"label":"Aerosol Index"},
    "CH4":          {"min":1700,"max":1900,"palette":['#000080','#4169E1','#00CED1','#ADFF2F','#FFFF00','#FF8C00','#FF0000'],"label":"CH4 (ppb)"},
    "SO2":          {"min":0,   "max":0.001,"palette":['#FFFFFF','#FFFF00','#FFA500','#FF0000'],"label":"SO2 (mol/m2)"},
    "POPULATION":   {"min":0,   "max":1000,"palette":['#FFFFE0','#FFD700','#FFA500','#FF4500','#8B0000'],"label":"Pop. Density (per km2)"},
    "ET":           {"min":0,   "max":100, "palette":['#FFFFF0','#C7E9B4','#7FCDBB','#41B6C4','#1D91C0','#225EA8','#0C2C84'],"label":"ET (kg/m2)"},
    "PET":          {"min":0,   "max":200, "palette":['#FFFFF0','#FEE5D9','#FCAE91','#FB6A4A','#DE2D26','#A50F15'],"label":"PET (kg/m2)"},
    "EVI2":         {"min":-0.2,"max":1.0, "palette":['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],"label":"EVI2"},
    "SPYNDEX_GENERIC":{"min":-1,"max":1,  "palette":['#8B0000','#FF4500','#FFFF00','#90EE90','#006400'],"label":"Index"},
}

PRECOMPUTED_PALETTE_MAP = {
    "NDVI": "NDVI", "EVI": "EVI", "EVI2": "EVI2",
    "ET": "ET", "PET": "PET",
    "LST_Day_1km": "LST", "LST_Night_1km": "LST",
    "elevation": "ELEVATION", "DEM": "ELEVATION", "DSM": "ELEVATION",
    "occurrence": "WATER", "sm_surface": "SOIL_MOISTURE", "sm_rootzone": "SOIL_MOISTURE",
    "avg_rad": "NIGHTLIGHTS", "avg_vis": "NIGHTLIGHTS",
    "agb": "BIOMASS", "bgb": "BIOMASS",
    "canopy_height": "CANOPY_HEIGHT", "treecover2000": "TREECOVER", "loss": "FOREST_LOSS",
    "Map": "LANDCOVER", "LC_Type1": "LANDCOVER", "discrete_classification": "LANDCOVER",
    "tropospheric_NO2_column_number_density": "NO2",
    "CO_column_number_density": "CO",
    "absorbing_aerosol_index": "AEROSOL",
    "CH4_column_volume_mixing_ratio_dry_air": "CH4",
    "SO2_column_number_density": "SO2",
    "FireMask": "FIRE",
    "population": "POPULATION", "population_density": "POPULATION",
}


def get_palette(index_name: str) -> dict:
    if index_name in INDEX_PALETTES:
        return INDEX_PALETTES[index_name]
    if _SPYNDEX_AVAILABLE and index_name in spyndex.indices:
        domain = spyndex.indices[index_name].application_domain
        domain_defaults = {
            "vegetation": INDEX_PALETTES["NDVI"],
            "water":      INDEX_PALETTES["NDWI"],
            "burn":       INDEX_PALETTES["NBR"],
            "snow":       INDEX_PALETTES["NDSI"],
            "soil":       INDEX_PALETTES["BSI"],
            "urban":      INDEX_PALETTES["NDBI"],
        }
        base = domain_defaults.get(domain, INDEX_PALETTES["SPYNDEX_GENERIC"]).copy()
        base["label"] = index_name
        return base
    return {**INDEX_PALETTES["SPYNDEX_GENERIC"], "label": index_name}
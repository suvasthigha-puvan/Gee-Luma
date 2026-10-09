# GEE Dynamic Map Generator — Knowledge Base
> This file is loaded at runtime and injected into the CrewAI agent prompt.
> It covers: (1) GEE Dataset Registry, (2) Spyndex band-variable mappings,
> (3) Precomputed Band Registry, (4) Index palette hints, (5) Agent decision rules.

---

## 1. SPYNDEX — Spectral Index Library

The app uses the **spyndex** Python package (`pip install spyndex`) which provides
access to 200+ spectral indices from the **Awesome Spectral Indices** catalogue:
  https://github.com/awesome-spectral-indices/spyndex

### How spyndex works
- `spyndex.indices` → dict of all available indices (short_name → metadata)
- Each index has: `short_name`, `long_name`, `formula`, `bands` (list of required variable keys), `application_domain`
- `spyndex.computeIndex(index=["NDVI"], params={"N": nir_array, "R": red_array})`
- Works directly with **ee.Image expressions** in GEE via the formula string

### Spyndex Standard Band Variable Names
These are the standardised single-letter/two-letter variable names used in spyndex formulas:

| Variable | Meaning              | Sentinel-2 Band | Landsat 8/9 Band | Landsat 5/7 Band | MODIS Band      |
|----------|----------------------|-----------------|------------------|------------------|-----------------|
| A        | Coastal / Aerosol    | B1              | SR_B1            | —                | —               |
| B        | Blue                 | B2              | SR_B2            | SR_B1            | sur_refl_b03    |
| G        | Green                | B3              | SR_B3            | SR_B2            | sur_refl_b04    |
| R        | Red                  | B4              | SR_B4            | SR_B3            | sur_refl_b01    |
| RE1      | Red Edge 1 (705 nm)  | B5              | —                | —                | —               |
| RE2      | Red Edge 2 (740 nm)  | B6              | —                | —                | —               |
| RE3      | Red Edge 3 (783 nm)  | B7              | —                | —                | —               |
| N        | NIR (broad)          | B8              | SR_B5            | SR_B4            | sur_refl_b02    |
| N2       | NIR narrow (865 nm)  | B8A             | —                | —                | —               |
| S1       | SWIR 1 (1610 nm)     | B11             | SR_B6            | SR_B5            | sur_refl_b06    |
| S2       | SWIR 2 (2190 nm)     | B12             | SR_B7            | SR_B7            | sur_refl_b07    |
| T1       | Thermal 1            | —               | ST_B10           | —                | —               |
| T2       | Thermal 2            | —               | ST_B11           | —                | —               |
| VV       | SAR VV backscatter   | S1 VV           | —                | —                | —               |
| VH       | SAR VH backscatter   | S1 VH           | —                | —                | —               |
| HH       | SAR HH backscatter   | ALOS HH         | —                | —                | —               |
| HV       | SAR HV backscatter   | ALOS HV         | —                | —                | —               |

### Spyndex Constants (default values used in formulas)
| Constant | Value | Used in       |
|----------|-------|---------------|
| L        | 0.5   | SAVI, EVI     |
| C1       | 6.0   | EVI           |
| C2       | 7.5   | EVI           |
| g        | 2.5   | EVI           |
| sigma    | 0.5   | kNDVI         |
| p        | 2.0   | kernel ops    |

### Application Domains in spyndex
- `vegetation` — NDVI, EVI, SAVI, GNDVI, NDRE, CIre, …
- `water` — NDWI, MNDWI, AWEInsh, AWEIsh, …
- `burn` — NBR, NBR2, BAIS2, BAI, MIRBI, …
- `snow` — NDSI, S3, SWI, …
- `soil` — BSI, DBSI, RI, …
- `urban` — NDBI, BUI, IBI, …
- `radar` — RVI, RFDI, …
- `kernel` — kNDVI, …

---

## 2. GEE DATASET REGISTRY — LIVE CATALOG SEARCH

This section used to be a static, hand-maintained list of ~40 dataset entries.
It has been replaced with the `search_gee_catalog` tool, which looks up real
collection IDs at request time from the official Earth Engine Data Catalog
(~880 datasets) and the community-maintained catalog (~4,300 datasets),
instead of asking you to recall an ID from memory.

### When to use the tool
You already know the common sensors well — do NOT call the tool for these,
just use your own knowledge combined with Section 3 (Precomputed Band
Registry) below:
- Sentinel-2 (`COPERNICUS/S2_SR_HARMONIZED`, `COPERNICUS/S2_HARMONIZED`)
- Landsat 5/7/8/9 Collection 2 (`LANDSAT/L{T05,E07,C08,C09}/C02/T1_L2`)
- MODIS (`MODIS/061/...`)
- Sentinel-1 SAR (`COPERNICUS/S1_GRD`)
- Sentinel-5P (`COPERNICUS/S5P/...`)
- SRTM (`USGS/SRTMGL1_003`)

Call `search_gee_catalog(query=...)` whenever the request names a dataset,
sensor, or theme you're not confident about — unusual sensors, thematic
products (soil moisture, canopy height, nighttime lights, air quality,
population, land cover variants, etc.), or anything phrased in a way that
doesn't map cleanly onto the sensors above. Pass a short natural-language
query (e.g. `"global forest canopy height"`, `"soil moisture SMAP"`), not a
guessed collection ID.

### How to use the results
The tool returns a JSON list of candidate datasets, each with:
`id` (the real GEE collection ID — use this verbatim as `"collection"`),
`ee_snippet`, `title`, `type` (`image_collection` / `image` / `table`),
`provider`, `tags`, `source` (`official` or `community`), and `docs`.

Pick the best match by title/tags relevance to the user's request. The tool
does NOT return band names or scale factors — the app verifies those itself
at runtime via `introspect_collection()` once you've picked a collection, so
it's fine to leave `band_override` empty or provide your best guess for an
unlisted dataset; the app's live band introspection is the safety net, not
the tool.

If the tool call fails or returns nothing relevant, fall back to your own
knowledge and follow the existing UNLISTED COLLECTION RULE (still provide
your best collection ID, band mapping, and scale factor) rather than
blocking the request.

---

## 3. PRECOMPUTED BAND REGISTRY

This section is the **authoritative lookup table** the agent MUST consult before deciding
whether to compute an index. If the requested variable/index appears here for the chosen
dataset, use the precomputed band — do NOT run spyndex or band math.

### Rule: Use-Existing-Band-First
```
IF (requested_index OR variable) IN precomputed_bands[collection]:
    → set map_type = "PRECOMPUTED"
    → set precomputed_band = <band_name>
    → set index = ""
    → do NOT invoke spyndex
ELSE IF raw reflectance bands are available and spyndex supports the index:
    → set map_type = "SPYNDEX"
    → set index = <spyndex_short_name>
ELSE:
    → choose a different dataset that has the required bands
```

### Precomputed Band Lookup Table

| Collection ID                          | Variable / Index    | Band Name                                      | Scale   | Unit              |
|----------------------------------------|---------------------|------------------------------------------------|---------|-------------------|
| MODIS/061/MOD13Q1                      | NDVI                | NDVI                                           | ×0.0001 | dimensionless     |
| MODIS/061/MOD13Q1                      | EVI                 | EVI                                            | ×0.0001 | dimensionless     |
| MODIS/061/MOD13A1                      | NDVI                | NDVI                                           | ×0.0001 | dimensionless     |
| MODIS/061/MOD13A1                      | EVI                 | EVI                                            | ×0.0001 | dimensionless     |
| MODIS/061/MYD13Q1                      | NDVI                | NDVI                                           | ×0.0001 | dimensionless     |
| MODIS/061/MYD13Q1                      | EVI                 | EVI                                            | ×0.0001 | dimensionless     |
| MODIS/061/MYD13A1                      | NDVI                | NDVI                                           | ×0.0001 | dimensionless     |
| MODIS/061/MYD13A1                      | EVI                 | EVI                                            | ×0.0001 | dimensionless     |
| NOAA/VIIRS/001/VNP13A1                 | NDVI                | NDVI                                           | ×0.0001 | dimensionless     |
| NOAA/VIIRS/001/VNP13A1                 | EVI                 | EVI                                            | ×0.0001 | dimensionless     |
| NOAA/VIIRS/001/VNP13A1                 | EVI2                | EVI2                                           | ×0.0001 | dimensionless     |
| MODIS/061/MOD16A2                      | ET                  | ET                                             | ×0.1    | kg/m²/8day        |
| MODIS/061/MOD16A2                      | PET                 | PET                                            | ×0.1    | kg/m²/8day        |
| MODIS/061/MOD16A2GF                    | ET                  | ET                                             | ×0.1    | kg/m²/8day        |
| MODIS/061/MOD16A2GF                    | PET                 | PET                                            | ×0.1    | kg/m²/8day        |
| IDAHO_EPSCOR/TERRACLIMATE              | ET / actual ET      | aet                                            | ×1      | mm/month          |
| IDAHO_EPSCOR/TERRACLIMATE              | PET                 | pet                                            | ×1      | mm/month          |
| IDAHO_EPSCOR/TERRACLIMATE              | soil moisture       | soil                                           | ×1      | mm (accumulated)  |
| IDAHO_EPSCOR/TERRACLIMATE              | precipitation       | pr                                             | ×1      | mm/month          |
| IDAHO_EPSCOR/TERRACLIMATE              | temperature min     | tmmn                                           | ×0.1    | °C                |
| IDAHO_EPSCOR/TERRACLIMATE              | temperature max     | tmmx                                           | ×0.1    | °C                |
| IDAHO_EPSCOR/TERRACLIMATE              | drought (PDSI)      | pdsi                                           | ×0.01   | dimensionless     |
| ECMWF/ERA5_LAND/DAILY_AGGR             | ET / evapotranspiration | total_evaporation_sum                      | ×1      | m/day             |
| ECMWF/ERA5_LAND/DAILY_AGGR             | PET                 | potential_evaporation_sum                      | ×1      | m/day             |
| ECMWF/ERA5_LAND/DAILY_AGGR             | soil moisture       | volumetric_soil_water_layer_1                  | ×1      | m³/m³             |
| ECMWF/ERA5_LAND/DAILY_AGGR             | LAI high veg        | leaf_area_index_high_vegetation                | ×1      | m²/m²             |
| ECMWF/ERA5_LAND/DAILY_AGGR             | LAI low veg         | leaf_area_index_low_vegetation                 | ×1      | m²/m²             |
| MODIS/061/MOD11A2                      | LST (day)           | LST_Day_1km                                    | ×0.02   | Kelvin            |
| MODIS/061/MOD11A2                      | LST (night)         | LST_Night_1km                                  | ×0.02   | Kelvin            |
| MODIS/061/MYD11A2                      | LST (day)           | LST_Day_1km                                    | ×0.02   | Kelvin            |
| MODIS/061/MYD11A2                      | LST (night)         | LST_Night_1km                                  | ×0.02   | Kelvin            |
| NASA/SMAP/SPL4SMGP/007                 | soil moisture        | sm_surface                                    | ×1      | m³/m³             |
| NASA/SMAP/SPL4SMGP/007                 | root zone moisture   | sm_rootzone                                   | ×1      | m³/m³             |
| USGS/SRTMGL1_003                       | elevation            | elevation                                     | ×1      | metres            |
| COPERNICUS/DEM/GLO30                   | elevation            | DEM                                           | ×1      | metres            |
| NASA/NASADEM_HGT/001                   | elevation            | elevation                                     | ×1      | metres            |
| NASA/ORNL/biomass_carbon_density/v1    | biomass (AGB)        | agb                                           | ×1      | Mg C/ha           |
| NASA/ORNL/biomass_carbon_density/v1    | biomass (BGB)        | bgb                                           | ×1      | Mg C/ha           |
| JAXA/GEDI_TCH_V2                       | canopy height        | canopy_height                                 | ×1      | metres            |
| UMD/hansen/global_forest_change_2023_v1_11 | tree cover       | treecover2000                                 | ×1      | % (0–100)         |
| UMD/hansen/global_forest_change_2023_v1_11 | forest loss      | loss                                          | ×1      | binary            |
| ESA/WorldCover/v200                    | land cover           | Map                                           | ×1      | class integer     |
| MODIS/061/MCD12Q1                      | land cover           | LC_Type1                                      | ×1      | class integer     |
| JRC/GSW1_4/GlobalSurfaceWater          | water occurrence     | occurrence                                    | ×1      | % (0–100)         |
| NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG    | nighttime lights     | avg_rad                                       | ×1      | nW/cm²/sr         |
| NOAA/DMSP-OLS/NIGHTTIME_LIGHTS         | nighttime lights     | avg_vis                                       | ×1      | digital number    |
| MODIS/061/MOD14A1                      | fire mask            | FireMask                                      | ×1      | class integer     |
| MODIS/061/MCD64A1                      | burned area          | BurnDate                                      | ×1      | day-of-year       |
| COPERNICUS/S5P/NRTI/L3_NO2            | NO2                  | tropospheric_NO2_column_number_density        | ×1      | mol/m²            |
| COPERNICUS/S5P/NRTI/L3_CO             | CO                   | CO_column_number_density                      | ×1      | mol/m²            |
| COPERNICUS/S5P/NRTI/L3_AER_AI         | aerosol index        | absorbing_aerosol_index                       | ×1      | dimensionless     |
| COPERNICUS/S5P/OFFL/L3_CH4            | CH4 / methane        | CH4_column_volume_mixing_ratio_dry_air        | ×1      | ppb               |
| COPERNICUS/S5P/OFFL/L3_SO2            | SO2                  | SO2_column_number_density                     | ×1      | mol/m²            |
| WorldPop/GP/100m/pop                   | population density   | population                                    | ×1      | persons/pixel     |
| CIESIN/GPWv411/GPW_Population_Density  | population density   | population_density                            | ×1      | persons/km²       |

---

## 4. LEGACY COLLECTION ID ALIASES
When the user or AI produces these old IDs, remap to the current ones:

```
LANDSAT/LC08/C01/T1_L2   → LANDSAT/LC08/C02/T1_L2
LANDSAT/LC08/C01/T1_SR   → LANDSAT/LC08/C02/T1_L2
LANDSAT/LC09/C01/T1_L2   → LANDSAT/LC09/C02/T1_L2
LANDSAT/LE07/C01/T1_L2   → LANDSAT/LE07/C02/T1_L2
LANDSAT/LT05/C01/T1_L2   → LANDSAT/LT05/C02/T1_L2
COPERNICUS/S2_SR         → COPERNICUS/S2_SR_HARMONIZED
COPERNICUS/S2            → COPERNICUS/S2_HARMONIZED
MODIS/006/MOD13Q1        → MODIS/061/MOD13Q1
MODIS/006/MCD12Q1        → MODIS/061/MCD12Q1
MODIS/006/MOD11A2        → MODIS/061/MOD11A2
MODIS/061/MOD16A2        → MODIS/061/MOD16A2GF  (prefer gap-filled version)
```

---

## 5. MAP TYPE REFERENCE

Beyond spectral indices, users may ask for these map types. Return the correct `map_type` in JSON:

| map_type      | Description                              | Typical Dataset                            |
|---------------|------------------------------------------|--------------------------------------------|
| RGB           | True-color composite (R,G,B)             | Sentinel-2, Landsat 8/9                    |
| FALSE_COLOR   | False-color (NIR,R,G)                    | Sentinel-2, Landsat 8/9                    |
| SWIR          | SWIR composite (SWIR2,SWIR1,R)           | Sentinel-2, Landsat 8/9                    |
| SAR_RGB       | SAR RGB composite (VV,VH,VV/VH)         | Sentinel-1 GRD                             |
| ELEVATION     | Raw DEM elevation                        | SRTM, Copernicus DEM, NASADEM              |
| SLOPE         | Terrain slope (degrees)                  | SRTM, Copernicus DEM                       |
| ASPECT        | Terrain aspect (degrees)                 | SRTM, Copernicus DEM                       |
| HILLSHADE     | Shaded relief                            | SRTM, Copernicus DEM                       |
| LANDCOVER     | Discrete land classification             | ESA WorldCover, MODIS MCD12Q1              |
| LST           | Land Surface Temperature                 | MODIS MOD11A2 / MYD11A2                    |
| NIGHTLIGHTS   | Nighttime light radiance                 | VIIRS DNB Monthly, DMSP OLS               |
| PRECIPITATION | Rainfall accumulation                    | CHIRPS, GPM IMERG                          |
| TEMPERATURE   | Air temperature                          | ERA5 Daily                                 |
| WATER         | Surface water occurrence/extent          | JRC GSW                                    |
| SOIL_MOISTURE | Volumetric soil water                    | SMAP L4                                    |
| TREECOVER     | Percent tree cover year 2000             | Hansen GFC                                 |
| FOREST_LOSS   | Annual forest loss (binary)              | Hansen GFC                                 |
| BIOMASS       | Above-ground biomass carbon              | NASA/ORNL Biomass Carbon                   |
| CANOPY_HEIGHT | Canopy height 2020                       | GEDI TCH                                   |
| FIRE          | Fire/thermal anomaly detection           | MODIS MOD14A1                              |
| NO2           | Tropospheric NO2 column                  | Sentinel-5P NRTI NO2                       |
| CO            | Carbon monoxide column                   | Sentinel-5P NRTI CO                        |
| AEROSOL       | Absorbing aerosol index                  | Sentinel-5P NRTI AER_AI                    |
| CH4           | Methane dry-air mixing ratio             | Sentinel-5P OFFL CH4                       |
| SO2           | SO2 column density                       | Sentinel-5P OFFL SO2                       |
| POPULATION    | Population density                       | WorldPop, GPWv4                            |
| ET            | Evapotranspiration (actual)              | MODIS MOD16A2GF, TerraClimate, ERA5-Land   |
| PET           | Potential evapotranspiration             | MODIS MOD16A2GF, TerraClimate, ERA5-Land   |
| PRECOMPUTED   | Use an existing dataset band directly    | Any dataset with precomputed bands         |
| SPYNDEX       | Any index from the spyndex catalogue     | Depends on required bands                  |

---

## 6. AGENT DECISION RULES

### Rule 1 — Use-Existing-Band-First (HIGHEST PRIORITY)
Before invoking spyndex or any band math, ALWAYS check Section 3 (Precomputed Band Registry).

```
Decision flow for every index/variable request:
  1. Is the requested variable in the Precomputed Band Registry for the selected collection?
     YES → map_type = "PRECOMPUTED", precomputed_band = <band_name>, index = ""
     NO  → continue to step 2

  2. Does spyndex know this index AND does the collection have all required reflectance bands?
     YES → map_type = "SPYNDEX", index = <spyndex_short_name>
     NO  → switch to a collection that has the variable precomputed or the required raw bands
```

Examples:
- User asks "NDVI for Sri Lanka using MODIS" → MOD13Q1 has NDVI precomputed → map_type="PRECOMPUTED", precomputed_band="NDVI"
- User asks "NDVI for Sri Lanka using Sentinel-2" → S2 has no precomputed NDVI → map_type="SPYNDEX", index="NDVI"
- User asks "EVI2 for Amazon" → VNP13A1 has EVI2 precomputed → map_type="PRECOMPUTED", precomputed_band="EVI2"
- User asks "evapotranspiration map" → MOD16A2GF has ET precomputed → map_type="PRECOMPUTED", precomputed_band="ET"
- User asks "potential ET" → MOD16A2GF has PET precomputed → map_type="PRECOMPUTED", precomputed_band="PET"
- User asks "kNDVI for Amazon" → no dataset has kNDVI precomputed → map_type="SPYNDEX", index="kNDVI", use Sentinel-2

### Rule 2 — Dataset selection by sensor capability
- Red-edge indices (NDRE, S2REP, IRECI, etc.) → Sentinel-2 only
- Thermal / LST → MODIS MOD11A2 (precomputed) or Landsat thermal band
- SAR indices (RVI, RFDI) → Sentinel-1 or ALOS PALSAR
- Historical before 2014 → Landsat 5/7/8 (no Sentinel-2)
- Cloudy/tropical regions for vegetation → prefer MODIS (precomputed NDVI/EVI) or Landsat over Sentinel-2
- ET / evapotranspiration → MODIS MOD16A2GF (8-day) or TerraClimate (monthly) or ERA5-Land (daily)

### Rule 3 — Cloud cover defaults
Use 90 for optical sensors. Irrelevant for SAR, DEM, MODIS VI/ET, static datasets.

### Rule 4 — Static datasets
(DEM, Hansen, ESA WorldCover, JRC Water occurrence): Do NOT filter by date. Use `.mosaic()` or direct `ee.Image`.

### Rule 5 — Scale factors
Always apply. Sentinel-2 and MODIS reflectance ×0.0001. Landsat C2 SR: ×0.0000275 −0.2.
MODIS NDVI/EVI (precomputed): ×0.0001. MODIS ET/PET: ×0.1. LST: ×0.02 → Kelvin.
Precomputed bands already encode the correct physical unit after the listed scale factor.

### Rule 6 — RGB / composite maps
Return `map_type: "RGB"` (or FALSE_COLOR/SWIR), no index name needed — the app handles band selection.

### Rule 7 — Dataset preference when user doesn't specify
For optical: Sentinel-2 > Landsat 8/9 > MODIS.
For ET/hydrology: MODIS MOD16A2GF > TerraClimate > ERA5-Land.
For vegetation indices without red-edge: check MODIS precomputed first if tropical or multi-year.

### Rule 8 — Always return valid JSON with these exact keys:
```json
{
  "collection": "COLLECTION_ID",
  "index": "SPYNDEX_SHORT_NAME_OR_EMPTY",
  "map_type": "PRECOMPUTED|SPYNDEX|RGB|ELEVATION|LST|ET|PET|...",
  "precomputed_band": "BAND_NAME_OR_EMPTY",
  "precomputed_scale": 1.0,
  "region": "Place name",
  "date_start": "YYYY-MM-DD",
  "date_end": "YYYY-MM-DD",
  "cloud_cover": 90,
  "band_override": {},
  "notes": "One sentence rationale including whether precomputed band or spyndex was used."
}
```
- `precomputed_band`: the GEE band name to select directly when map_type is "PRECOMPUTED"; empty string otherwise.
- `precomputed_scale`: the numeric scale factor to apply to the precomputed band (from Section 3); default 1.0.
- `band_override`: optional dict to override spyndex variable → actual GEE band mapping if non-standard.
- `index`: the spyndex short name (e.g. "NDVI", "kNDVI") when map_type is "SPYNDEX"; empty string otherwise.
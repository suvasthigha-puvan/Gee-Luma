"""
cloud_masking.py
----------------
Pixel-level cloud and shadow masking for optical image collections, plus
detection of whether the user asked for (or declined) cloud masking.

Masking is matched to a collection by ID pattern, so every Landsat
Collection 2 product and both Sentinel-2 harmonized collections are covered
without listing each ID.
"""

import re

import ee

# ---------------------------------------------------------------------------
# Prompt intent
# ---------------------------------------------------------------------------

CLOUD_REMOVAL_KEYWORDS = [
    "cloud removal", "cloud mask", "cloud masking", "remove clouds",
    "mask clouds", "cloud-free", "cloud free", "cloudless", "no clouds", "without clouds",
    "cloud filter", "cloud correction", "cloud removed", "clear sky",
]

CLOUD_OPT_OUT_KEYWORDS = [
    "no cloud mask", "without cloud mask", "no cloud removal", "without cloud removal",
    "don't mask", "do not mask", "unmasked", "keep clouds", "with clouds",
]


def user_declined_cloud_removal(prompt: str) -> bool:
    """True if the prompt explicitly asks for clouds to be left in."""
    text = prompt.lower()
    return any(kw in text for kw in CLOUD_OPT_OUT_KEYWORDS)


def user_wants_cloud_removal(prompt: str) -> bool:
    """True if the prompt explicitly asks for pixel-level cloud masking."""
    text = prompt.lower()
    if user_declined_cloud_removal(prompt):
        return False
    return any(kw in text for kw in CLOUD_REMOVAL_KEYWORDS)


# ---------------------------------------------------------------------------
# Per-sensor masking
# ---------------------------------------------------------------------------

CLOUD_SCORE_PLUS = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
CLOUD_SCORE_BAND = "cs_cdf"
CLOUD_SCORE_CLEAR_THRESHOLD = 0.60   # pixels scoring below this are treated as cloud/shadow


def _mask_s2_collection(col: ee.ImageCollection) -> ee.ImageCollection:
    """
    Sentinel-2: Cloud Score+, Google's per-pixel clear-sky score. It catches
    thin cloud, haze and cloud shadow, which the older QA60 band misses (and
    QA60 was empty from early 2022 to early 2024).
    """
    scores = ee.ImageCollection(CLOUD_SCORE_PLUS)

    def _mask(image):
        return image.updateMask(image.select(CLOUD_SCORE_BAND).gte(CLOUD_SCORE_CLEAR_THRESHOLD))

    return col.linkCollection(scores, [CLOUD_SCORE_BAND]).map(_mask)


def mask_landsat_c2_clouds(image: ee.Image) -> ee.Image:
    """Landsat Collection 2: QA_PIXEL dilated cloud, cirrus, cloud and cloud shadow."""
    qa = image.select("QA_PIXEL")
    clear = (qa.bitwiseAnd(1 << 1).eq(0)        # dilated cloud
               .And(qa.bitwiseAnd(1 << 2).eq(0))    # cirrus (Landsat 8/9)
               .And(qa.bitwiseAnd(1 << 3).eq(0))    # cloud
               .And(qa.bitwiseAnd(1 << 4).eq(0)))   # cloud shadow
    return image.updateMask(clear)


def mask_modis_clouds(image: ee.Image) -> ee.Image:
    """MODIS daily surface reflectance: state_1km cloud state = clear, no shadow."""
    state = image.select("state_1km")
    clear = state.bitwiseAnd(3).eq(0).And(state.bitwiseAnd(1 << 2).eq(0))
    return image.updateMask(clear)


def mask_modis_8day_clouds(image: ee.Image) -> ee.Image:
    """MODIS 8-day surface reflectance: StateQA cloud state = clear, no shadow."""
    state = image.select("StateQA")
    clear = state.bitwiseAnd(3).eq(0).And(state.bitwiseAnd(1 << 2).eq(0))
    return image.updateMask(clear)


def mask_viirs_clouds(image: ee.Image) -> ee.Image:
    """VIIRS VNP09GA: QF1 cloud mask confidence = confident or probably clear."""
    qf1 = image.select("QF1")
    return image.updateMask(qf1.bitwiseAnd(0b1100).lte(4))


# (ID pattern, collection-level masking function, description for the map credit)
_CLOUD_MASK_METHODS = [
    (r"^COPERNICUS/S2(_SR)?_HARMONIZED$",
     _mask_s2_collection,
     f"Cloud Score+ (clear-sky score >= {CLOUD_SCORE_CLEAR_THRESHOLD:.2f})"),
    (r"^LANDSAT/L[A-Z]\d\d/C02/T\d(_L2|_TOA)?$",
     lambda col: col.map(mask_landsat_c2_clouds),
     "Landsat QA_PIXEL (cloud, dilated cloud, cirrus, shadow)"),
    (r"^MODIS/\d+/M[OY]D09G[AQ]$",
     lambda col: col.map(mask_modis_clouds),
     "MODIS state_1km (cloud and shadow)"),
    (r"^MODIS/\d+/M[OY]D09A1$",
     lambda col: col.map(mask_modis_8day_clouds),
     "MODIS StateQA (cloud and shadow)"),
    (r"^NOAA/VIIRS/\d+/VNP09GA$",
     lambda col: col.map(mask_viirs_clouds),
     "VIIRS QF1 cloud mask"),
]


def cloud_mask_method(cid: str):
    """(masking function, description) for a collection, or None if it has no pixel-level mask."""
    for pattern, fn, description in _CLOUD_MASK_METHODS:
        if re.match(pattern, cid or ""):
            return fn, description
    return None


def apply_cloud_mask(col: ee.ImageCollection, cid: str) -> ee.ImageCollection:
    """Mask cloudy pixels in every image of `col`; returns `col` unchanged if no method exists."""
    method = cloud_mask_method(cid)
    return method[0](col) if method else col

"""
cloud_masking.py
----------------
Per-sensor cloud and shadow masking functions for Google Earth Engine images,
plus keyword-based detection of cloud-removal intent from user prompts.
"""

import ee

# ---------------------------------------------------------------------------
# Keyword detection
# ---------------------------------------------------------------------------

CLOUD_REMOVAL_KEYWORDS = [
    "cloud removal", "cloud mask", "cloud masking", "remove clouds",
    "mask clouds", "cloud-free", "cloudless", "no clouds", "without clouds",
    "cloud filter", "cloud correction", "cloud removed", "clear sky",
]


def user_wants_cloud_removal(prompt: str) -> bool:
    """Return True if the prompt requests pixel-level cloud masking."""
    text = prompt.lower()
    return any(kw in text for kw in CLOUD_REMOVAL_KEYWORDS)


# ---------------------------------------------------------------------------
# Per-sensor masking functions
# ---------------------------------------------------------------------------

def mask_s2_clouds(image: ee.Image) -> ee.Image:
    """Mask Sentinel-2 SR (HARMONIZED) clouds using QA60 bitmask."""
    qa = image.select("QA60")
    cloud_bit_mask  = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = (qa.bitwiseAnd(cloud_bit_mask).eq(0)
              .And(qa.bitwiseAnd(cirrus_bit_mask).eq(0)))
    return image.updateMask(mask)


def mask_s2_toa_clouds(image: ee.Image) -> ee.Image:
    """Mask Sentinel-2 TOA clouds (same QA60 approach)."""
    return mask_s2_clouds(image)


def mask_landsat_c2_clouds(image: ee.Image) -> ee.Image:
    """Mask Landsat Collection-2 clouds and cloud shadows via QA_PIXEL."""
    qa = image.select("QA_PIXEL")
    cloud_mask  = qa.bitwiseAnd(1 << 3).eq(0)
    shadow_mask = qa.bitwiseAnd(1 << 4).eq(0)
    return image.updateMask(cloud_mask.And(shadow_mask))


def mask_modis_clouds(image: ee.Image) -> ee.Image:
    """Mask MODIS MOD09GA clouds using state_1km QA band."""
    state = image.select("state_1km")
    cloud_mask = state.bitwiseAnd(3).eq(0)
    return image.updateMask(cloud_mask)


def mask_viirs_clouds(image: ee.Image) -> ee.Image:
    """Mask VIIRS VNP09GA clouds using QF1 quality flag."""
    qf1 = image.select("QF1")
    cloud_mask = qf1.bitwiseAnd(0b1100).lte(4)
    return image.updateMask(cloud_mask)


# ---------------------------------------------------------------------------
# Lookup table: collection ID -> masking function
# ---------------------------------------------------------------------------

CLOUD_MASK_FUNCTIONS: dict = {
    "COPERNICUS/S2_SR_HARMONIZED": mask_s2_clouds,
    "COPERNICUS/S2_HARMONIZED":    mask_s2_toa_clouds,
    "LANDSAT/LC09/C02/T1_L2":      mask_landsat_c2_clouds,
    "LANDSAT/LC08/C02/T1_L2":      mask_landsat_c2_clouds,
    "LANDSAT/LE07/C02/T1_L2":      mask_landsat_c2_clouds,
    "LANDSAT/LT05/C02/T1_L2":      mask_landsat_c2_clouds,
    "MODIS/061/MOD09GA":           mask_modis_clouds,
    "NOAA/VIIRS/001/VNP09GA":      mask_viirs_clouds,
}

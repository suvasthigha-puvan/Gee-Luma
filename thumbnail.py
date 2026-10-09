"""
thumbnail.py
------------
Fetches GEE thumbnail images with automatic dimension retry.
"""

import io
import time

import requests
import streamlit as st
from PIL import Image


# ====================== THUMBNAIL WITH RETRY ======================

def fetch_thumbnail_with_retry(vis_img, vis_params, region_geom, max_retries=3):
    dimension_steps = [512, 384, 256]
    for attempt, dim in enumerate(dimension_steps[:max_retries]):
        try:
            thumb_params = {**vis_params, "region": region_geom, "dimensions": dim, "format": "png"}
            thumb_params.pop("bands", None)
            bands_for_thumb = vis_params.get("bands")
            if bands_for_thumb:
                thumb_params["bands"] = bands_for_thumb
            url  = vis_img.getThumbURL(thumb_params)
            resp = requests.get(url, timeout=90)
            if resp.status_code == 200:
                return Image.open(io.BytesIO(resp.content)), dim
            st.warning(f"Attempt {attempt+1}: HTTP {resp.status_code}, retrying...")
        except requests.exceptions.Timeout:
            st.warning(f"Attempt {attempt+1}: Timeout at {dim}px, trying smaller...")
        except Exception as e:
            st.warning(f"Attempt {attempt+1}: {e}")
        time.sleep(2)
    raise RuntimeError("All thumbnail attempts failed. Try a smaller region or coarser dataset.")

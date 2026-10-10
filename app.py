"""
app.py
------
Gee-Luma - Streamlit interface.

The map pipeline itself lives in pipeline.py and is shared with the web
interface (server.py + frontend/). This file is only the Streamlit page:
inputs in, pipeline call, results out.

Run with:
    streamlit run app.py
"""

import inspect
import json
import os
from pathlib import Path

import ee
import streamlit as st
from dotenv import load_dotenv

from pipeline import (
    run_pipeline, render_original_map, create_llm,
    PALETTE_PRESETS, EE_PROJECT, SPYNDEX_AVAILABLE,
)
from utils import ascii_label
from styles import (
    inject_css, SIDEBAR_WORDMARK, GUIDANCE_HTML,
    section_label, metric_card,
)
from geojson_helpers import _ensure_wgs84, get_geojson_bounds, get_geojson_label
from map_stats import format_value
from exports import fetch_geotiff

if SPYNDEX_AVAILABLE:
    import spyndex


def _stretch(widget) -> dict:
    """
    Keyword arguments that make a widget fill its container.

    Streamlit replaced `use_container_width=True` (and st.image's
    `use_column_width`) with `width="stretch"`, and shows a deprecation notice
    in the page when the old ones are used. This picks whichever the installed
    version expects.
    """
    width_param = inspect.signature(widget).parameters.get("width")
    if width_param is not None and isinstance(width_param.default, str):
        return {"width": "stretch"}
    return {"use_container_width": True}


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
        ee.Initialize(project=EE_PROJECT)
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
        st.session_state.llm = create_llm(api_key)
        st.session_state.crew_ready = True

# ====================== SIDEBAR ======================
st.sidebar.markdown(SIDEBAR_WORDMARK, unsafe_allow_html=True)

selected_palette = st.sidebar.selectbox("Color Palette Override", list(PALETTE_PRESETS.keys()))

fill_gaps_option = st.sidebar.checkbox(
    "Fill cloud gaps from nearby dates", value=True,
    help=(
        "When cloud leaves holes in the requested period, fill them with imagery from the "
        "weeks before and after it. The original, unfilled map stays available next to the "
        "filled one."
    ),
)

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

        if st.sidebar.button("✕ Remove region", **_stretch(st.button)):
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
    generate = st.button("GENERATE MAP", type="primary", **_stretch(st.button))

# ====================== MAIN GENERATION LOGIC ======================
if generate and user_prompt and "llm" in st.session_state:

    # A new request replaces the previous map, even if this one fails.
    st.session_state.pop("last_result", None)

    result_data = run_pipeline(
        user_prompt,
        llm=st.session_state.llm,
        ui=st,
        uploaded_region_geojson=uploaded_region_geojson,
        uploaded_region_label=uploaded_region_label,
        map_title_override=map_title_override,
        selected_palette=selected_palette,
        fill_gaps_option=fill_gaps_option,
    )
    if result_data:
        st.session_state["last_result"] = result_data

elif generate and "llm" not in st.session_state:
    st.warning("Please enter your OpenAI API key first.")

# ====================== MAP OUTPUT ======================
# Rendered from session state so the map stays on screen across reruns.
if "last_result" in st.session_state:
    res = st.session_state["last_result"]
    cloud_note = " - Cloud masked" if res["cloud_removal_applied"] else ""

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(metric_card(res["map_label"], "Map Index", accent=True), unsafe_allow_html=True)
    with m2:
        st.markdown(metric_card(res["region"], "Region"), unsafe_allow_html=True)
    with m3:
        st.markdown(metric_card(str(res["n_images"]), "Scenes"), unsafe_allow_html=True)
    with m4:
        st.markdown(metric_card(res["engine"], "Engine"), unsafe_allow_html=True)

    st.markdown(section_label("Map Output"), unsafe_allow_html=True)
    caption = f"{res['map_label']} - {res['region']} - {res['collection']}{cloud_note}"
    fill = res.get("gap_fill")
    if not fill:
        st.image(res["png_bytes"], caption=caption, **_stretch(st.image))
    else:
        st.info(
            f"Cloud left data over only **{fill['original_percent']:.0f}%** of the region in the requested period. "
            f"The gaps were filled with imagery from {fill['window_start']} to {fill['window_end']}, "
            f"so the map now covers **{fill['filled_percent']:.0f}%**. "
            "The original map is in the second tab."
        )
        tab_filled, tab_original = st.tabs(["Gap-filled map", "Original map (no gap filling)"])
        with tab_filled:
            st.image(res["png_bytes"], caption=caption + " - Gap-filled", **_stretch(st.image))
        with tab_original:
            original = res.get("original")
            if original:
                st.image(original["png"], caption=caption + " - Original, no gap filling", **_stretch(st.image))
                base = res["file_name"].rsplit(".", 1)[0]
                o1, o2, _o3, _o4 = st.columns(4)
                with o1:
                    st.download_button("Download Original PNG", data=original["png"],
                                       file_name=f"{base}_original.png", mime="image/png",
                                       **_stretch(st.download_button))
                with o2:
                    st.download_button("Download Original PDF", data=original["pdf"],
                                       file_name=f"{base}_original.pdf", mime="application/pdf",
                                       **_stretch(st.download_button))
            else:
                st.caption("The map exactly as the requested period shows it, with cloud gaps left empty.")
                if st.button("Render original map"):
                    try:
                        with st.spinner("Rendering the original map..."):
                            res["original"] = render_original_map(res["original_job"])
                        st.rerun()
                    except Exception as e:
                        st.error(f"The original map could not be rendered: {e}")
    st.success("Map generated successfully"
               + (" with pixel-level cloud masking applied." if res["cloud_removal_applied"] else "."))
    base_name = res["file_name"].rsplit(".", 1)[0]
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.download_button(label="Download Map PNG", data=res["png_bytes"],
                           file_name=f"{base_name}.png", mime="image/png", **_stretch(st.download_button))
    with d2:
        st.download_button(label="Download Map PDF", data=res["pdf_bytes"],
                           file_name=f"{base_name}.pdf", mime="application/pdf", **_stretch(st.download_button))
    with d3:
        if res["stats_csv"]:
            st.download_button(label="Download Statistics CSV", data=res["stats_csv"],
                               file_name=f"{base_name}_statistics.csv", mime="text/csv",
                               **_stretch(st.download_button))
    with d4:
        geotiff = res["geotiff"]
        if geotiff and "bytes" in geotiff:
            st.download_button(label="Download GeoTIFF", data=geotiff["bytes"],
                               file_name=f"{base_name}.tif", mime="image/tiff", **_stretch(st.download_button))
        elif geotiff:
            # Fetched on request: the file can be tens of megabytes.
            if st.button("Prepare GeoTIFF", **_stretch(st.button)):
                try:
                    with st.spinner("Downloading GeoTIFF from Earth Engine..."):
                        geotiff["bytes"] = fetch_geotiff(geotiff["url"])
                    st.rerun()
                except Exception as e:
                    st.error(f"GeoTIFF export failed: {e}")
    if res["geotiff"]:
        g = res["geotiff"]
        st.caption(
            f"GeoTIFF: data values at {g['scale_m']:g} m pixels in the map projection"
            + (f" (resampled from the dataset's {g['native_scale_m']:g} m to fit Earth Engine's "
               "download size limit)." if g["resampled"] else ".")
        )

    # ---------------- Statistics ----------------
    stats = res["stats"]
    if stats:
        import pandas as pd
        st.markdown(section_label("Statistics"), unsafe_allow_html=True)
        if stats.get("area_km2"):
            st.caption(f"Region area: {stats['area_km2']:,.0f} km2")
        coverage = stats.get("coverage_percent")
        if coverage is not None:
            st.caption(f"Valid data covers {coverage:.0f}% of the region; statistics describe that part only.")
            if coverage < 60:
                st.warning(
                    f"Only {coverage:.0f}% of the region has data - the rest was masked (usually cloud) or is "
                    "missing from the dataset"
                    + (", even after gap filling." if res.get("gap_fill") else ". A longer period usually fills the gaps.")
                )
        if stats["kind"] == "categorical":
            table = pd.DataFrame([
                {"Class": r["class"], "Area (km2)": round(r["area_km2"], 2), "Share (%)": round(r["percent"], 2)}
                for r in stats["rows"]
            ])
            t1, t2 = st.columns([1, 1])
            with t1:
                st.dataframe(table, hide_index=True, **_stretch(st.dataframe))
            with t2:
                st.bar_chart(table.set_index("Class")["Share (%)"])
        else:
            table = pd.DataFrame([{"Statistic": name, res["value_label"]: format_value(value)}
                                  for name, value in stats["rows"]])
            t1, t2 = st.columns([1, 1])
            with t1:
                st.dataframe(table, hide_index=True, **_stretch(st.dataframe))
            with t2:
                if stats["histogram"]:
                    hist = pd.DataFrame({
                        res["value_label"]: [float(format_value((b["from"] + b["to"]) / 2).replace(",", ""))
                                             for b in stats["histogram"]],
                        "Pixels": [b["pixels"] for b in stats["histogram"]],
                    }).set_index(res["value_label"])
                    st.bar_chart(hist)
                    st.caption("Distribution of values across the region.")

    info = res["index_info"]
    if info:
        with st.expander(f"About {info['name']} - {info['long_name']}"):
            st.markdown(f"**Formula:** `{info['formula']}`")
            st.markdown(f"**Domain:** {info['domain']}")
            st.markdown(f"**Required bands:** {', '.join(info['bands'])}")
            st.markdown(f"**Reference:** {info['reference']}")
            if info["available_bands"]:
                st.markdown(f"**Available bands in `{res['collection']}`:** `{', '.join(info['available_bands'])}`")
            if info["band_override"]:
                st.markdown(f"**Band mapping used:** `{info['band_override']}`")

    if res["cloud_mask_desc"]:
        with st.expander("Cloud Removal Details"):
            st.markdown(f"**Method:** {res['cloud_mask_desc']}")
            st.markdown(f"**Dataset:** `{res['collection']}`")
            st.markdown(
                "Pixel-level cloud masking was applied before computing the composite. "
                "Masked pixels are excluded from index computation."
            )

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

"""
cartography.py
--------------
Cartographic figure renderer: produces the final map PNG with
centred title, north arrow, scale bar, legend, and intelligent boundary detection.

Public API:
  render_cartographic_figure(...)  -> bytes (PNG)
"""

import io
import textwrap

import ee
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import matplotlib.colorbar as mcolorbar
import matplotlib.gridspec as mgridspec
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import cartopy.crs as ccrs
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
from PIL import Image

from utils import ascii_label
from boundary_agent import draw_geojson_outline

matplotlib.rcParams.update({"font.family": "DejaVu Sans"})

_MAP_BG    = "#ffffff"
_PANEL_BG  = "#ffffff"
_TEXT_DARK = "#0d1b2a"
_TICK_COL  = "#445566"

# ====================== CARTOGRAPHIC FIGURE RENDERER ======================

def _nice_coord_ticks(lo, hi, n=6):
    step_candidates = [0.5, 1, 2, 5, 10, 15, 20, 30]
    span = hi - lo
    for s in step_candidates:
        ticks = [round(lo + s * i, 4) for i in range(int(span / s) + 2)
                 if lo <= lo + s * i <= hi]
        if 3 <= len(ticks) <= n + 2:
            return ticks
    return list(np.linspace(lo, hi, n))

def _fmt_lon(v):
    if v == 0: return "0 deg"
    return f"{v:.4g} deg E" if v > 0 else f"{abs(v):.4g} deg W"

def _fmt_lat(v):
    if v == 0: return "0 deg"
    return f"{v:.4g} deg N" if v > 0 else f"{abs(v):.4g} deg S"

def _haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dlam = np.radians(lon2 - lon1)
    dphi = np.radians(lat2 - lat1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

def _dynamic_scale_ticks(geo_bounds, n_segments=4):
    if geo_bounds is None:
        return [0, 1000, 2000, 3000, 4000], [0, 621, 1243, 1864, 2485]
    lon_min  = geo_bounds["lon_min"]
    lon_max  = geo_bounds["lon_max"]
    lat_mid  = (geo_bounds["lat_min"] + geo_bounds["lat_max"]) / 2.0
    width_km = _haversine_km(lon_min, lat_mid, lon_max, lat_mid)
    seg_raw  = width_km * 0.80 / n_segments
    mag      = 10 ** np.floor(np.log10(max(seg_raw, 0.1)))
    seg_km   = mag * min([1, 2, 2.5, 5, 10], key=lambda s: abs(s * mag - seg_raw))
    km_ticks   = [int(seg_km*i) if (seg_km*i)==int(seg_km*i) else round(seg_km*i,1) for i in range(n_segments+1)]
    mile_ticks = [int(round(v * 0.621371)) for v in km_ticks]
    return km_ticks, mile_ticks

def _build_info_panel(ap, title, palette, vmin, vmax, legend_label, is_rgb,
                      geo_bounds=None, lulc_legend=None, compact=False):
    """
    lulc_legend: list of {"label": str, "color": hex} dicts for discrete class legends.
    When provided, replaces the continuous colorbar with color-box + label rows.
    """
    ap.set_facecolor(_PANEL_BG)
    ap.axis("off")
    ap.add_patch(mpatches.Rectangle(
        (0,0), 1, 1, lw=0.9, edgecolor="#8899aa", facecolor=_PANEL_BG,
        transform=ap.transAxes, zorder=0, clip_on=False))
    title_clean = "\n".join(ascii_label(part) for part in str(title).splitlines() if ascii_label(part))
    title_fs = 8 if compact else 13
    title_spacing = 1.18 if compact else 1.55
    ap.text(0.50, 0.965, title_clean, ha="center", va="top", fontsize=title_fs,
            fontweight="bold", color=_TEXT_DARK, transform=ap.transAxes, linespacing=title_spacing)

    cx = 0.50
    if compact:
        cy_t, cy_b, hw = 0.705, 0.585, 0.055
        scale_label_fs, scale_tick_fs = 8, 7
        sb_top, bar_h = 0.405, 0.030
        sep_y = 0.255
    else:
        cy_t, cy_b, hw = 0.785, 0.640, 0.080
        scale_label_fs, scale_tick_fs = 13, 13
        sb_top, bar_h = 0.470, 0.038
        sep_y = 0.285
    cy_m=(cy_t+cy_b)/2
    for pts, col in [
        ([[cx,cy_t],[cx-hw,cy_m+0.015],[cx,cy_m]],"#1a1a2e"),
        ([[cx,cy_t],[cx+hw,cy_m+0.015],[cx,cy_m]],"#9aa0ae"),
        ([[cx,cy_b],[cx-hw,cy_m-0.015],[cx,cy_m]],"#9aa0ae"),
        ([[cx,cy_b],[cx+hw,cy_m-0.015],[cx,cy_m]],"#1a1a2e"),
    ]:
        ap.add_patch(plt.Polygon(pts, closed=True, color=col, transform=ap.transAxes, zorder=5))
    ap.plot(cx, cy_m, "o", color="white", ms=5, zorder=6, transform=ap.transAxes)
    ap.text(cx, cy_t+0.022, "N", ha="center", va="bottom", fontsize=scale_label_fs,
            fontweight="bold", color=_TEXT_DARK, transform=ap.transAxes)
    km_ticks, _ = _dynamic_scale_ticks(geo_bounds, n_segments=4)
    x0,x1=0.08,0.92; seg_w=(x1-x0)/4
    for i in range(4):
        ap.add_patch(mpatches.Rectangle(
            (x0+i*seg_w, sb_top-bar_h), seg_w, bar_h,
            lw=0.8, edgecolor="#1a1a2e",
            facecolor="#1a1a2e" if i%2==0 else "white",
            transform=ap.transAxes, zorder=4))
    for i, km in enumerate(km_ticks):
        xf = x0 + (x1-x0)*i/4
        ap.plot([xf,xf],[sb_top,sb_top+0.015], color=_TEXT_DARK, lw=0.9, transform=ap.transAxes)
        ap.text(xf, sb_top+0.021, str(km), ha="center", va="bottom",
                fontsize=scale_tick_fs, color=_TEXT_DARK, transform=ap.transAxes)
    ap.text((x0+x1)/2, sb_top+0.072, "km", ha="center", va="bottom",
            fontsize=scale_label_fs, fontweight="bold", color=_TEXT_DARK, transform=ap.transAxes)
    ap.plot([0.04,0.96],[sep_y,sep_y], color="#8899aa", lw=0.9, transform=ap.transAxes)

    if is_rgb:
        ap.text(0.50, sep_y-0.04, "RGB Composite", ha="center", va="top",
                fontsize=13, fontweight="bold", color=_TEXT_DARK, transform=ap.transAxes)
        for j, (band, col) in enumerate(zip(["Red","Green","Blue"],["#e05050","#50b050","#5080e0"])):
            ap.add_patch(mpatches.Rectangle(
                (0.15+j*0.24,sep_y-0.14), 0.10, 0.040,
                facecolor=col, edgecolor="none", transform=ap.transAxes, zorder=4))
            ap.text(0.20+j*0.24, sep_y-0.175, band, ha="center", va="top",
                    fontsize=13, color=_TEXT_DARK, transform=ap.transAxes)

    elif lulc_legend:
        ap.text(0.50, sep_y-0.018, "LULC Map", ha="center", va="top",
                fontsize=10 if compact else 13, fontweight="bold", color=_TEXT_DARK, transform=ap.transAxes)
        n_classes  = len(lulc_legend)
        row_h      = min(0.046, max(0.018, (sep_y - 0.085) / max(n_classes, 1)))
        font_size  = (8 if compact else 11) if n_classes <= 8 else (7 if compact else 9) if n_classes <= 14 else 7
        box_w      = 0.095
        box_h      = row_h * 0.68
        x_box      = 0.08           # left edge of swatch
        x_label    = 0.22           # left edge of label text
        start_y    = sep_y - 0.062  # top of first row

        for i, entry in enumerate(lulc_legend):
            y_center = start_y - i * row_h
            # Color swatch
            ap.add_patch(mpatches.FancyBboxPatch(
                (x_box, y_center - box_h / 2), box_w, box_h,
                boxstyle="round,pad=0.005",
                facecolor=entry["color"],
                edgecolor="#333333",
                linewidth=0.6,
                transform=ap.transAxes, zorder=5,
            ))
            # Class label
            ap.text(x_label, y_center, entry["label"],
                    ha="left", va="center", fontsize=font_size,
                    color=_TEXT_DARK, transform=ap.transAxes)

    else:
        ap.text(0.50, sep_y-0.022, legend_label, ha="center", va="top",
                fontsize=10, fontweight="bold", color=_TEXT_DARK, transform=ap.transAxes)
        cb_ax = ap.inset_axes([0.06,0.046,0.88,0.124])
        cmap  = LinearSegmentedColormap.from_list("leg", palette, N=256)
        norm  = mcolors.Normalize(vmin=vmin, vmax=vmax)
        cb    = mcolorbar.ColorbarBase(cb_ax, cmap=cmap, norm=norm, orientation="horizontal")
        ticks = np.linspace(vmin, vmax, 5)
        cb.set_ticks(ticks)
        cb.set_ticklabels([f"{t:.3g}" for t in ticks])
        cb.ax.tick_params(labelsize=8, color=_TEXT_DARK, length=3, width=0.7)
        for tl in cb.ax.get_xticklabels():
            tl.set_color(_TEXT_DARK)
        cb.outline.set_linewidth(0.7)
        cb.outline.set_edgecolor(_TICK_COL)


# ====================== BASEMAP TILE FETCHING ======================

def fetch_basemap_tile(lon_min: float, lon_max: float, lat_min: float, lat_max: float, 
                       zoom: int = 8, tile_size: int = 512) -> Image.Image | None:
    """
    Fetch a satellite/OSM basemap tile from OpenStreetMap's Satellite layer
    (powered by USGS ortho imagery). Falls back to OSM if unavailable.
    
    Returns PIL Image or None if fetch fails.
    """
    try:
        # Calculate tile coordinates from bounds
        import math
        
        def lat_lon_to_tile(lat, lon, zoom):
            n = 2.0 ** zoom
            x = int((lon + 180.0) / 360.0 * n)
            y = int((1.0 - np.log(np.tan(np.radians(lat)) + 1.0 / np.cos(np.radians(lat))) / np.pi) / 2.0 * n)
            return x, y
        
        x, y = lat_lon_to_tile((lat_min + lat_max) / 2, (lon_min + lon_max) / 2, zoom)
        
        # Try Satellite layer first
        url = f"https://a.tile.openstreetmap.fr/osmfr/{zoom}/{x}/{y}.png"
        resp = requests.get(url, timeout=5)
        
        if resp.status_code != 200:
            # Fallback to standard OSM
            url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
            resp = requests.get(url, timeout=5)
        
        if resp.status_code == 200:
            return Image.open(io.BytesIO(resp.content))
    except Exception as e:
        pass
    
    return None


# ====================== MAP SCALE BAR / COMPOSITE LEGEND ======================

def _nice_length_km(target_km: float) -> float:
    """Largest 1/2/5 x 10^n length that does not exceed target_km."""
    mag = 10 ** np.floor(np.log10(max(target_km, 1e-3)))
    for m in (5, 2, 1):
        if m * mag <= target_km:
            return float(m * mag)
    return float(mag)


def _fmt_distance(km: float) -> str:
    if km < 1:
        return f"{km * 1000:g} m"
    return f"{km:g} km"


def _draw_map_scale_bar(map_ax, lon_min, lon_max, lat_min, lat_max):
    """
    Draw a scale bar in the lower-left corner of the map, in map coordinates,
    so its drawn length is the ground distance it is labelled with
    (measured east-west at the map's middle latitude).
    """
    width_deg  = lon_max - lon_min
    height_deg = lat_max - lat_min
    lat_mid    = (lat_min + lat_max) / 2.0
    km_per_deg = 111.32 * max(np.cos(np.radians(lat_mid)), 1e-6)

    length_km  = _nice_length_km(width_deg * km_per_deg * 0.25)
    length_deg = length_km / km_per_deg

    x0    = lon_min + 0.04 * width_deg
    y0    = lat_min + 0.04 * height_deg
    bar_h = 0.012 * height_deg
    pc    = ccrs.PlateCarree()

    # White backing so the bar stays readable over any imagery
    map_ax.add_patch(mpatches.Rectangle(
        (x0 - 0.02 * width_deg, y0 - 0.015 * height_deg),
        length_deg + 0.10 * width_deg, bar_h + 0.065 * height_deg,
        facecolor="white", edgecolor="#94a3b8", lw=0.5, alpha=0.85,
        transform=pc, zorder=8))

    half = length_deg / 2.0
    for i, face in enumerate(("#111827", "white")):
        map_ax.add_patch(mpatches.Rectangle(
            (x0 + i * half, y0), half, bar_h,
            facecolor=face, edgecolor="#111827", lw=0.6,
            transform=pc, zorder=9))

    y_text = y0 + bar_h + 0.008 * height_deg
    for x, label in ((x0, "0"),
                     (x0 + half, f"{length_km / 2:g}"),
                     (x0 + length_deg, _fmt_distance(length_km))):
        map_ax.text(x, y_text, label, ha="center", va="bottom", fontsize=7,
                    color=_TEXT_DARK, transform=pc, zorder=9)


_CHANNEL_BAND_NAMES = {
    "R": "Red", "G": "Green", "B": "Blue", "N": "Near infrared",
    "S1": "Shortwave infrared 1", "S2": "Shortwave infrared 2",
    "VV": "VV backscatter", "VH": "VH backscatter", "VVdVH": "VV / VH ratio",
}


def _draw_composite_legend(ap, bands):
    """Legend for 3-band colour composites: which band is shown in each colour channel."""
    ap.text(0.5, 0.34, "Colour composite", ha='center', va='center', fontsize=8,
            weight='bold', color=_TEXT_DARK, transform=ap.transAxes)
    channels = [("Red", "#d64545"), ("Green", "#3f9d4b"), ("Blue", "#3f6fd1")]
    for i, (channel, colour) in enumerate(channels):
        y_row = 0.27 - i * 0.055
        ap.add_patch(mpatches.Rectangle(
            (0.10, y_row - 0.016), 0.08, 0.032,
            facecolor=colour, edgecolor="#333", lw=0.5,
            transform=ap.transAxes, zorder=5))
        band = bands[i] if i < len(bands) else channel
        ap.text(0.22, y_row, _CHANNEL_BAND_NAMES.get(band, str(band)),
                ha='left', va='center', fontsize=7,
                color=_TEXT_DARK, transform=ap.transAxes)


def _compute_layout_params(geo_bounds: dict | None) -> dict:
    """
    Compute figure dimensions and subplot sizes based on region aspect ratio.
    Returns dict with orientation, map_w, map_h, panel_w.
    """
    if not geo_bounds:
        region_aspect = 1.0
    else:
        region_w = geo_bounds["lon_max"] - geo_bounds["lon_min"]
        region_h = geo_bounds["lat_max"] - geo_bounds["lat_min"]
        region_aspect = region_w / max(region_h, 1e-6)

    if region_aspect >= 1.28:
        orientation = "landscape"
        map_w = 10.5
        map_h = float(np.clip(map_w / region_aspect, 4.6, 8.2))
        panel_w = 4.3
    elif region_aspect <= 0.78:
        orientation = "portrait"
        map_h = 10.8
        map_w = float(np.clip(map_h * region_aspect, 4.2, 8.4))
        panel_w = 4.0
    else:
        orientation = "balanced"
        map_w = 8.8
        map_h = float(np.clip(map_w / region_aspect, 7.2, 9.4))
        panel_w = 4.1

    return {
        "orientation": orientation,
        "map_w": map_w,
        "map_h": map_h,
        "panel_w": panel_w,
    }


def render_cartographic_figure(
    map_pil_image,
    region_name,
    map_label,
    date_start,
    date_end,
    vis_params_gee,
    display_label,
    is_rgb,
    geo_bounds=None,
    cloud_removal_applied=False,
    lulc_legend=None,
    region_geom=None,
    uploaded_geojson=None,
    custom_title: str | None = None,
    boundary_geojson=None,
):

    import textwrap
    import requests

    # -------------------------
    # BOUNDS
    # -------------------------
    if geo_bounds:
        lon_min = geo_bounds["lon_min"]
        lon_max = geo_bounds["lon_max"]
        lat_min = geo_bounds["lat_min"]
        lat_max = geo_bounds["lat_max"]
    else:
        lon_min, lon_max, lat_min, lat_max = -180, 180, -90, 90

    # -------------------------
    # FIGURE SIZE BASED ON SHAPE
    # -------------------------
    lon_span = abs(lon_max - lon_min)
    lat_span = abs(lat_max - lat_min)
    mid_lat = (lat_min + lat_max) / 2

    projected_lon = lon_span * max(np.cos(np.deg2rad(mid_lat)), 0.3)
    aspect = projected_lon / max(lat_span, 1e-6)

    if aspect < 0.7:
        fig_size = (9, 13)
    elif aspect > 1.8:
        fig_size = (15, 8)
    else:
        fig_size = (12, 9)

    # Use GridSpec with top margin for the centered figure title
    fig = plt.figure(figsize=fig_size, facecolor="white")

    # Reserve top space for centered title, then map + panel below
    # FIXED: Adjusted width_ratios for better balance (was 3.6, 1.4)
    gs = mgridspec.GridSpec(
        2, 2,
        height_ratios=[0.05, 1],
        width_ratios=[3.0, 1.0],
        wspace=0.05,
        hspace=0.02,
    )

    # Top row: title centered
    title_ax = fig.add_subplot(gs[0, :])
    title_ax.axis("off")

    # Bottom left: map
    map_ax = fig.add_subplot(gs[1, 0], projection=ccrs.PlateCarree())

    # Bottom right: info panel
    ap = fig.add_subplot(gs[1, 1])

    # -------------------------
    # TITLE (Plain, no styling)
    # -------------------------
    title_text = custom_title or f"{ascii_label(region_name)} {ascii_label(map_label)} {date_start}"
    title_ax.text(0.5, 0.5, title_text,
                  ha="center", va="center", fontsize=16, fontweight="bold",
                  color=_TEXT_DARK, transform=title_ax.transAxes,
                  bbox=None)  # No box styling

    # -------------------------
    # DISPLAY MAP IMAGE
    # -------------------------
    extent = [lon_min, lon_max, lat_min, lat_max]
    map_ax.imshow(map_pil_image, extent=extent, origin='upper', transform=ccrs.PlateCarree(), zorder=0)

    # -------------------------
    # MAP BOUNDARIES
    # -------------------------
    map_ax.set_xlim(lon_min, lon_max)
    map_ax.set_ylim(lat_min, lat_max)
    map_ax.coastlines(resolution='50m', color='gray', linewidth=0.5, zorder=2)

    # -------------------------
    # GRIDLINES
    # -------------------------
    gl = map_ax.gridlines(draw_labels=True,
                      linewidth=0.4,
                      color='gray',
                      alpha=0.25,
                      linestyle='--')

    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {'size': 9}
    gl.ylabel_style = {'size': 9}
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER

    # -------------------------
    # REGION BOUNDARY
    # The outline is resolved once by the caller: either the uploaded AOI
    # or the admin boundary that was used to clip the data.
    # -------------------------
    if uploaded_geojson:
        draw_geojson_outline(map_ax, uploaded_geojson, color="black", linewidth=2.0)
    elif boundary_geojson:
        draw_geojson_outline(map_ax, boundary_geojson, color=_TEXT_DARK, linewidth=1.5)

    # -------------------------
    # SCALE BAR (on the map, so its length matches the map's scale)
    # -------------------------
    if geo_bounds:
        _draw_map_scale_bar(map_ax, lon_min, lon_max, lat_min, lat_max)

    map_ax.set_title("")  # remove matplotlib default

    # -------------------------
    # PANEL
    # -------------------------
    ap.axis('off')
    ap.set_facecolor("#ffffff")

    ap.add_patch(mpatches.Rectangle(
        (0, 0), 1, 1,
        fill=False, lw=1.2,
        edgecolor="#94a3b8",
        transform=ap.transAxes
    ))

    y = 0.96

    # -------------------------
    # TITLE IN PANEL (Small, clean)
    # -------------------------
    title_clean = "\n".join(ascii_label(part) for part in str(region_name).splitlines() if ascii_label(part))
    ap.text(0.5, y - 0.03, title_clean,
            ha='center', fontsize=10, weight='bold', color=_TEXT_DARK,
            transform=ap.transAxes)
    y -= 0.08

    # -------------------------
    # NORTH ARROW
    # -------------------------
    arrow_height = 0.08
    y -= arrow_height

    ap.text(0.5, y + arrow_height * 0.6 + 0.032, "N",
            ha='center', va='bottom', fontsize=8, weight='bold', color=_TEXT_DARK,
            transform=ap.transAxes)

    ap.add_patch(mpatches.FancyArrow(
        0.5, y,
        0, arrow_height * 0.6,
        width=0.004,
        head_width=0.025,
        head_length=0.025,
        color="#111827",
        transform=ap.transAxes,
        zorder=5
    ))

    y -= 0.05

    # -------------------------
    # LEGEND  (fully inside panel box)
    # -------------------------
    palette = vis_params_gee.get("palette")

    if lulc_legend:
        # Discrete class legend; rows shrink so every class fits in the panel
        y_top = y - 0.04
        row_h = min(0.035, (y_top - 0.04) / max(len(lulc_legend), 1))
        font_size = 7 if row_h >= 0.03 else 6
        for i, item in enumerate(lulc_legend):
            y_row = y_top - i * row_h
            ap.add_patch(mpatches.Rectangle(
                (0.10, y_row - row_h * 0.36), 0.08, row_h * 0.72,
                facecolor=item["color"], edgecolor="#333", lw=0.5,
                transform=ap.transAxes, zorder=5
            ))
            ap.text(0.22, y_row, item["label"],
                    ha='left', va='center', fontsize=font_size,
                    color=_TEXT_DARK, transform=ap.transAxes)

    elif is_rgb or not palette:
        # Colour composite: no colour ramp, so show which band drives each channel
        _draw_composite_legend(ap, vis_params_gee.get("bands", []))

    else:
        # Continuous colorbar
        cmap = LinearSegmentedColormap.from_list("custom", palette)
        norm = mcolors.Normalize(
            vmin=vis_params_gee.get("min", 0),
            vmax=vis_params_gee.get("max", 1)
        )
        cax = ap.inset_axes([0.08, 0.18, 0.84, 0.058])
        cb = mcolorbar.ColorbarBase(cax, cmap=cmap, norm=norm, orientation='horizontal')
        ticks = np.linspace(vis_params_gee.get("min", 0), vis_params_gee.get("max", 1), 5)
        cb.set_ticks(ticks)
        # Whole numbers for wide ranges (totals in the thousands), else 2 significant digits
        wide = abs(ticks[-1] - ticks[0]) >= 20
        cb.set_ticklabels([f"{t:,.0f}" if wide else f"{t:.2g}" for t in ticks], fontsize=6)
        cb.ax.tick_params(labelsize=6, length=2, width=0.5, color=_TEXT_DARK)
        for tl in cb.ax.get_xticklabels():
            tl.set_color(_TEXT_DARK)
        cb.outline.set_linewidth(0.5)
        cb.outline.set_edgecolor(_TICK_COL)

        # Label below colorbar
        ap.text(0.5, 0.12, display_label,
                ha='center', va='top', fontsize=7, color=_TEXT_DARK,
                transform=ap.transAxes, weight='bold')

    # -------------------------
    # EXPORT
    # -------------------------
    buf = io.BytesIO()
    plt.savefig(buf, dpi=300, bbox_inches='tight', pad_inches=0.15)
    plt.close(fig)
    buf.seek(0)

    return buf.getvalue()

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
from boundary_agent import BoundaryAgent, draw_intelligent_boundary

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
    # INTELLIGENT BOUNDARY DETECTION & DRAWING
    # Agent automatically detects: Country (ADM0), Province (ADM1), District (ADM2)
    # Uses geoBoundaries: WM/geoLab/geoBoundaries/600/ADM{0,1,2}
    # -------------------------
    
    # Auto-detect administrative level from region name
    admin_level, admin_type = BoundaryAgent.detect_admin_level(region_name)
    
    print(f"🗺️  Region: '{region_name}' → {admin_type} (ADM{admin_level})")
    
    if not uploaded_geojson:
        # No custom AOI: Draw the region's official boundary
        success = draw_intelligent_boundary(
            map_ax=map_ax,
            region_name=region_name,
            country_name="Sri Lanka",
            admin_level=admin_level,
            custom_geojson=None
        )
        
        if not success:
            print(f"⚠️  Could not fetch boundary for '{region_name}' - map will display without boundary")
    
    # -------------------------
    # CUSTOM AOI BOUNDARY (uploaded GeoJSON)
    # Draw custom polygons + optional context boundary
    # -------------------------
    if uploaded_geojson:
        print(f"📍 Custom AOI uploaded with {len(uploaded_geojson.get('features', []))} features")
        
        # Option 1: Draw context boundary (region boundary) - lighter style
        # This provides geographic context for the custom AOI
        try:
            success = draw_intelligent_boundary(
                map_ax=map_ax,
                region_name=region_name,
                country_name="Sri Lanka",
                admin_level=admin_level,
                custom_geojson=None
            )
            if success:
                print(f"✅ Context boundary added: {admin_type} ({region_name})")
        except Exception as e:
            print(f"⚠️  Could not add context boundary: {e}")
        
        # Option 2: Draw the custom AOI polygons on top - bold black
        try:
            from shapely.geometry import shape

            if uploaded_geojson["type"] == "FeatureCollection":
                geoms = [shape(f["geometry"]) for f in uploaded_geojson["features"]]
            else:
                geoms = [shape(uploaded_geojson)]

            for geom in geoms:
                if hasattr(geom, 'exterior'):
                    x, y = geom.exterior.xy
                    map_ax.plot(x, y,
                            color="black",
                            linewidth=2.5,  # Bold for custom AOI
                            transform=ccrs.PlateCarree(),
                            zorder=7,  # On top of context boundary
                            label="Custom AOI")
            
            print(f"✅ Custom AOI polygons drawn on top")
        except Exception as e:
            print(f"⚠️  Custom AOI draw error: {e}")

    map_ax.set_title("")  # remove matplotlib default

    # -------------------------
    # PANEL  match map axes position exactly
    # -------------------------
    ap.axis('off')
    ap.set_facecolor("#ffffff")

    ap.add_patch(mpatches.Rectangle(
        (0, 0), 1, 1,
        fill=False, lw=1.2,
        edgecolor="#94a3b8",
        transform=ap.transAxes
    ))

    # -------------------------
    # INTELLIGENT PANEL LAYOUT (AI-driven spacing)
    # -------------------------
    # Calculate optimal spacing based on available height
    panel_height = 1.0
    reserved_for_legend = 0.40  # 40% for legend/colorbar
    reserved_for_title = 0.08   # 8% for panel title
    remaining_space = panel_height - reserved_for_legend - reserved_for_title  # ~52%
    
    # Distribute remaining space among elements
    arrow_height = remaining_space * 0.15  # 15% of remaining = ~8%
    arrow_spacing = remaining_space * 0.10 # spacing after arrow = ~5%
    scale_height = remaining_space * 0.25  # 25% of remaining = ~13%
    scale_spacing = remaining_space * 0.08 # spacing after scale = ~4%
    # Rest goes to padding and breathing room

    y = 0.96

    def next_y(h):
        nonlocal y
        y -= h
        return y

    # -------------------------
    # TITLE IN PANEL (Small, clean)
    # -------------------------
    title_clean = "\n".join(ascii_label(part) for part in str(region_name).splitlines() if ascii_label(part))
    ap.text(0.5, y - 0.03, title_clean,
            ha='center', fontsize=10, weight='bold', color=_TEXT_DARK,
            transform=ap.transAxes)
    y -= reserved_for_title

    # -------------------------
    # NORTH ARROW - Optimally sized
    # -------------------------
    yn = next_y(arrow_height)

    # N label
    ap.text(0.5, yn + arrow_height * 0.5, "N",
            ha='center', fontsize=8, weight='bold', color=_TEXT_DARK,
            transform=ap.transAxes)

    # Arrow - proportional
    ap.add_patch(mpatches.FancyArrow(
        0.5, yn,
        0, arrow_height * 0.6,
        width=0.004,
        head_width=0.025,
        head_length=0.025,
        color="#111827",
        transform=ap.transAxes,
        zorder=5
    ))
    
    # Breathing room after arrow
    y -= arrow_spacing

    # -------------------------
    # SCALE BAR - Optimally sized
    # -------------------------
    ys = next_y(scale_height)

    km_ticks, _ = _dynamic_scale_ticks(geo_bounds)

    total_w = 0.60
    x_start = 0.20
    bar_h   = scale_height * 0.35  # Proportional to scale section height
    seg_w   = total_w / (len(km_ticks) - 1)

    # "km" label above bar
    ap.text(0.5, ys + bar_h + 0.012, "km",
            ha='center', va='bottom', fontsize=7, weight='bold', color=_TEXT_DARK,
            transform=ap.transAxes)

    # Scale bar segments
    for i in range(len(km_ticks) - 1):
        x0 = x_start + i * seg_w
        color = "#111827" if i % 2 == 0 else "#e5e7eb"
        ap.add_patch(mpatches.Rectangle(
            (x0, ys - bar_h), seg_w, bar_h,
            facecolor=color, edgecolor="#111827", lw=0.5,
            transform=ap.transAxes, zorder=4
        ))

    # Tick labels BELOW the bar
    for i, km in enumerate(km_ticks):
        xf = x_start + i * seg_w
        ap.text(xf, ys - bar_h - 0.015, str(km),
                ha='center', va='top', fontsize=6.5, color=_TEXT_DARK,
                transform=ap.transAxes)

    # Breathing room after scale (no divider line - removed!)
    y -= scale_spacing

    # -------------------------
    # LEGEND  (fully inside panel box) - FIXED
    # -------------------------
    yl = next_y(0.02)

    if lulc_legend:
        # LULC legend
        y_legend = yl - 0.15
        for item in lulc_legend:
            ap.add_patch(mpatches.Rectangle(
                (0.10, y_legend - 0.014), 0.08, 0.025,
                facecolor=item["color"], edgecolor="#333", lw=0.5,
                transform=ap.transAxes, zorder=5
            ))
            ap.text(0.22, y_legend, item["label"],
                    ha='left', va='center', fontsize=7,
                    color=_TEXT_DARK, transform=ap.transAxes)
            y_legend -= 0.035

    else:
        # Continuous colorbar
        cmap = LinearSegmentedColormap.from_list("custom", vis_params_gee["palette"])
        norm = mcolors.Normalize(
            vmin=vis_params_gee.get("min", 0),
            vmax=vis_params_gee.get("max", 1)
        )
        # Colorbar inset - FIXED: Better positioning
        cax = ap.inset_axes([0.08, 0.18, 0.84, 0.058])
        cb = mcolorbar.ColorbarBase(cax, cmap=cmap, norm=norm, orientation='horizontal')
        ticks = np.linspace(vis_params_gee.get("min", 0), vis_params_gee.get("max", 1), 5)
        cb.set_ticks(ticks)
        cb.set_ticklabels([f"{t:.2g}" for t in ticks], fontsize=6)
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

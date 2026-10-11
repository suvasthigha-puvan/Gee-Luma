"""
cartography.py
--------------
Cartographic figure renderer: lays out the final map PNG - map frame in a
projection suited to the region, graticule, scale bar, title and period,
side panel with north arrow, locator map and legend, and a credit block
naming the data source, processing and projection.

Public API:
  render_cartographic_figure(...)  -> {"png": bytes, "pdf": bytes}
"""

import io
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as patheffects
import matplotlib.colors as mcolors
import matplotlib.colorbar as mcolorbar
import matplotlib.gridspec as mgridspec
import matplotlib.ticker as mticker
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from gee_luma.utils import ascii_label
from gee_luma.boundary_agent import draw_geojson_outline

matplotlib.rcParams.update({"font.family": "DejaVu Sans"})

_PANEL_BG  = "#ffffff"
_TEXT_DARK = "#0d1b2a"
_TEXT_MUTED = "#52606d"
_TICK_COL  = "#445566"
_FRAME_COL = "#94a3b8"
_ACCENT    = "#d62828"


# ====================== SCALE BAR ======================

def _nice_length(target: float) -> float:
    """Largest 1/2/5 x 10^n length that does not exceed target."""
    mag = 10 ** np.floor(np.log10(max(target, 1e-9)))
    for m in (5, 2, 1):
        if m * mag <= target:
            return float(m * mag)
    return float(mag)


def _fmt_distance(km: float) -> str:
    if km < 1:
        return f"{km * 1000:g} m"
    return f"{km:,.0f} km" if km >= 1000 else f"{km:g} km"


def _draw_map_scale_bar(map_ax, extent, projection, lat_mid, compact=False):
    """
    Draw a scale bar in the lower-left corner of the map, in map coordinates,
    so its drawn length is the ground distance it is labelled with.
    compact: for small maps - a longer bar labelled at its ends only.
    """
    xmin, xmax, ymin, ymax = extent
    width, height = xmax - xmin, ymax - ymin
    # Map units per kilometre: metres for projected maps; for lat/lon maps,
    # degrees of longitude at the map's middle latitude.
    units_per_km = 1000.0 if projection["metric"] else 1.0 / (111.32 * max(np.cos(np.radians(lat_mid)), 1e-6))

    length_km = _nice_length(width / units_per_km * (0.36 if compact else 0.22))
    length    = length_km * units_per_km

    x0    = xmin + 0.035 * width
    y0    = ymin + 0.035 * height
    bar_h = 0.010 * height
    crs   = projection["cartopy"]

    # No background box, so nothing of the map is hidden. A white outline
    # around the bar and its labels keeps them readable over dark data.
    halo = [patheffects.withStroke(linewidth=2.2, foreground="white")]

    quarter = length / 4.0
    for i in range(4):
        map_ax.add_patch(mpatches.Rectangle(
            (x0 + i * quarter, y0), quarter, bar_h,
            facecolor="#111827" if i % 2 == 0 else "white", edgecolor="#111827", lw=0.6,
            transform=crs, zorder=9, path_effects=halo))

    y_text = y0 + bar_h + 0.008 * height
    labels = [(x0, "0"), (x0 + length / 2, f"{length_km / 2:g}"), (x0 + length, _fmt_distance(length_km))]
    if compact:
        del labels[1]
    for x, label in labels:
        map_ax.text(x, y_text, label, ha="center", va="bottom", fontsize=7,
                    color=_TEXT_DARK, transform=crs, zorder=9, path_effects=halo)


# ====================== LEGENDS ======================

_CHANNEL_BAND_NAMES = {
    "R": "Red", "G": "Green", "B": "Blue", "N": "Near infrared",
    "S1": "Shortwave infrared 1", "S2": "Shortwave infrared 2",
    "VV": "VV backscatter", "VH": "VH backscatter", "VVdVH": "VV - VH difference",
}


def _draw_composite_legend(ap, bands, y_top):
    """Legend for 3-band colour composites: which band is shown in each colour channel."""
    ap.text(0.5, y_top, "Colour composite", ha='center', va='top', fontsize=8,
            weight='bold', color=_TEXT_DARK, transform=ap.transAxes)
    channels = [("Red", "#d64545"), ("Green", "#3f9d4b"), ("Blue", "#3f6fd1")]
    for i, (channel, colour) in enumerate(channels):
        y_row = y_top - 0.075 - i * 0.05
        ap.add_patch(mpatches.Rectangle(
            (0.10, y_row - 0.015), 0.08, 0.030,
            facecolor=colour, edgecolor="#333", lw=0.5,
            transform=ap.transAxes, zorder=5))
        band = bands[i] if i < len(bands) else channel
        ap.text(0.22, y_row, _CHANNEL_BAND_NAMES.get(band, str(band)),
                ha='left', va='center', fontsize=7,
                color=_TEXT_DARK, transform=ap.transAxes)


def _draw_class_legend(ap, classes, title, y_top, y_bottom=0.03):
    """Discrete class legend; rows shrink so every class fits in the panel."""
    ap.text(0.5, y_top, "\n".join(textwrap.wrap(ascii_label(title), 30)[:2]),
            ha='center', va='top', fontsize=8, weight='bold', color=_TEXT_DARK,
            transform=ap.transAxes)
    y_first = y_top - 0.075
    row_h = min(0.036, (y_first - y_bottom) / max(len(classes), 1))
    font_size = 7 if row_h >= 0.028 else (6 if row_h >= 0.02 else 5)
    for i, item in enumerate(classes):
        y_row = y_first - i * row_h
        if not item.get("color"):
            # Closing line that sums up the classes left out of a long legend.
            ap.text(0.08, y_row, ascii_label(item["label"]), ha='left', va='center',
                    fontsize=font_size, style='italic', color=_TEXT_MUTED, transform=ap.transAxes)
            continue
        ap.add_patch(mpatches.Rectangle(
            (0.08, y_row - row_h * 0.36), 0.08, row_h * 0.72,
            facecolor=item["color"], edgecolor="#333", lw=0.5,
            transform=ap.transAxes, zorder=5))
        ap.text(0.20, y_row, ascii_label(item["label"]),
                ha='left', va='center', fontsize=font_size,
                color=_TEXT_DARK, transform=ap.transAxes)


def _fmt_tick(value: float, step: float) -> str:
    """Tick label with just enough decimals to tell neighbouring ticks apart."""
    if step >= 1 and abs(value) >= 10000:
        return f"{value:,.0f}"
    if step >= 1:
        return f"{value:.0f}"
    if step < 1e-4:
        return f"{value:.1e}"
    decimals = int(min(max(-np.floor(np.log10(step)), 1), 6))
    return f"{value:.{decimals}f}"


def _draw_stats_block(ap, stats_lines, y_top):
    """Short summary of the data over the region, under the legend."""
    ap.text(0.5, y_top, "Over the region", ha='center', va='top', fontsize=7.2, weight='bold',
            color=_TEXT_DARK, transform=ap.transAxes)
    ap.text(0.5, y_top - 0.032, "\n".join(ascii_label(line) for line in stats_lines),
            ha='center', va='top', fontsize=6.8, color=_TEXT_MUTED,
            transform=ap.transAxes, linespacing=1.6)


def _draw_colorbar_legend(ap, palette, vmin, vmax, label, y_top):
    """Continuous legend: label, colour ramp, and ticks at round values."""
    ap.text(0.5, y_top, "\n".join(textwrap.wrap(ascii_label(label), 30)[:3]),
            ha='center', va='top', fontsize=8, weight='bold', color=_TEXT_DARK,
            transform=ap.transAxes, linespacing=1.3)
    _fill_colorbar(ap.inset_axes([0.09, y_top - 0.185, 0.82, 0.045]), palette, vmin, vmax)


def _fill_colorbar(cax, palette, vmin, vmax, tick_size=6.5):
    """Draw the colour ramp into `cax`, with ticks at round values."""
    if vmax <= vmin:
        vmax = vmin + 1
    cmap = LinearSegmentedColormap.from_list("legend", palette)
    cb   = mcolorbar.ColorbarBase(cax, cmap=cmap, norm=mcolors.Normalize(vmin=vmin, vmax=vmax),
                                  orientation='horizontal')
    ticks = [t for t in mticker.MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]).tick_values(vmin, vmax)
             if vmin - 1e-12 <= t <= vmax + 1e-12]
    if len(ticks) < 2:
        ticks = [vmin, vmax]
    step = abs(ticks[1] - ticks[0])
    cb.set_ticks(ticks)
    cb.set_ticklabels([_fmt_tick(t, step) for t in ticks])
    cb.ax.tick_params(labelsize=tick_size, length=2.5, width=0.5, color=_TEXT_DARK)
    for tl in cb.ax.get_xticklabels():
        tl.set_color(_TEXT_DARK)
    cb.outline.set_linewidth(0.5)
    cb.outline.set_edgecolor(_TICK_COL)


# ====================== LOCATOR MAP ======================

def _draw_locator(ap, bounds_axes, geo_bounds, outline_geojson):
    """
    Small overview map showing where the region is. Returns False (and draws
    nothing) for regions so large that an overview adds no information.
    """
    lon_span = geo_bounds["lon_max"] - geo_bounds["lon_min"]
    lat_span = geo_bounds["lat_max"] - geo_bounds["lat_min"]
    if max(lon_span, lat_span) > 50:
        return False
    lon_mid = (geo_bounds["lon_min"] + geo_bounds["lon_max"]) / 2.0
    lat_mid = (geo_bounds["lat_min"] + geo_bounds["lat_max"]) / 2.0
    half = float(np.clip(max(lon_span, lat_span) * 3.0, 4.0, 60.0))
    try:
        ax = ap.inset_axes(bounds_axes, projection=ccrs.PlateCarree())
        ax.set_extent([max(lon_mid - half, -180), min(lon_mid + half, 180),
                       max(lat_mid - half, -90), min(lat_mid + half, 90)], crs=ccrs.PlateCarree())
        scale = "110m" if half > 25 else "50m"
        ax.add_feature(cfeature.OCEAN.with_scale(scale), facecolor="#e8f1f8", edgecolor="none")
        ax.add_feature(cfeature.LAND.with_scale(scale), facecolor="#f1efe9", edgecolor="none")
        ax.add_feature(cfeature.BORDERS.with_scale(scale), edgecolor="#9aa5b1", linewidth=0.3)
        ax.add_feature(cfeature.COASTLINE.with_scale(scale), edgecolor="#7b8794", linewidth=0.35)
        if outline_geojson and max(lon_span, lat_span) > half * 0.12:
            draw_geojson_outline(ax, outline_geojson, color=_ACCENT, linewidth=0.8)
        else:
            # Region too small to see as a shape at this scale: mark it.
            ax.plot(lon_mid, lat_mid, marker="s", markersize=4.5, markerfacecolor=_ACCENT,
                    markeredgecolor="white", markeredgewidth=0.6, transform=ccrs.PlateCarree(), zorder=6)
        if not outline_geojson:
            ax.add_patch(mpatches.Rectangle(
                (geo_bounds["lon_min"], geo_bounds["lat_min"]), lon_span, lat_span,
                fill=False, edgecolor=_ACCENT, lw=0.8, transform=ccrs.PlateCarree(), zorder=6))
        for spine in ax.spines.values():
            spine.set_edgecolor(_FRAME_COL)
            spine.set_linewidth(0.6)
        return True
    except Exception as e:  # Natural Earth download failed, etc. - the map is still valid without it
        print(f"Locator map skipped: {e}")
        return False


def _draw_context_lines(map_ax, geo_bounds):
    """Coastlines and country borders, for maps that have no region outline."""
    try:
        span = max(geo_bounds["lon_max"] - geo_bounds["lon_min"],
                   geo_bounds["lat_max"] - geo_bounds["lat_min"])
        scale = "110m" if span > 60 else ("50m" if span > 8 else "10m")
        map_ax.add_feature(cfeature.COASTLINE.with_scale(scale), edgecolor="#1f2933", linewidth=0.5, zorder=3)
        map_ax.add_feature(cfeature.BORDERS.with_scale(scale), edgecolor="#52606d", linewidth=0.35, zorder=3)
    except Exception as e:
        print(f"Context lines skipped: {e}")


# ====================== MAIN RENDERER ======================

def render_cartographic_figure(
    map_pil_image,
    extent,
    projection,
    title,
    region_name,
    vis_params_gee,
    display_label,
    is_rgb,
    geo_bounds,
    subtitle: str | None = None,
    lulc_legend=None,
    uploaded_geojson=None,
    boundary_geojson=None,
    credit_lines: list[str] | None = None,
    stats_lines: list[str] | None = None,
):
    """
    Lay out the final map.

    map_pil_image: rendered data image covering exactly `extent`
    extent:        [xmin, xmax, ymin, ymax] in the map projection
    projection:    dict from projection.choose_map_projection()
    title/subtitle: main title and the line under it (period, composite)
    lulc_legend:   [{label, color}] for categorical maps, else None
    boundary_geojson / uploaded_geojson: outline drawn over the data
    credit_lines:  text lines for the credit block under the map
    stats_lines:   short summary statistics shown under a continuous legend

    Returns {"png": bytes, "pdf": bytes}. The PDF keeps text and lines as
    vectors, so it stays sharp at any print size.
    """
    xmin, xmax, ymin, ymax = extent
    aspect = (xmax - xmin) / max(ymax - ymin, 1e-9)
    lat_mid = (geo_bounds["lat_min"] + geo_bounds["lat_max"]) / 2.0 if geo_bounds else 0.0

    if aspect < 0.7:
        fig_size = (9.5, 13)
    elif aspect > 1.8:
        # Wide regions need less height; keep enough for the side panel.
        fig_size = (15, float(np.clip(15 * 0.6 / aspect + 3.4, 7.2, 8.5)))
    else:
        fig_size = (12.5, 9.5)

    fig = plt.figure(figsize=fig_size, facecolor="white")
    gs = mgridspec.GridSpec(
        2, 2,
        height_ratios=[0.075, 1],
        width_ratios=[3.0, 1.0],
        wspace=0.05,
        hspace=0.03,
    )
    title_ax = fig.add_subplot(gs[0, :])
    title_ax.axis("off")
    map_ax = fig.add_subplot(gs[1, 0], projection=projection["cartopy"])
    ap = fig.add_subplot(gs[1, 1])

    # -------------------------
    # TITLE + PERIOD
    # -------------------------
    title_ax.text(0.5, 0.78 if subtitle else 0.5, ascii_label(title),
                  ha="center", va="center", fontsize=17, fontweight="bold",
                  color=_TEXT_DARK, transform=title_ax.transAxes)
    if subtitle:
        title_ax.text(0.5, 0.12, ascii_label(subtitle),
                      ha="center", va="center", fontsize=10.5,
                      color=_TEXT_MUTED, transform=title_ax.transAxes)

    # -------------------------
    # MAP IMAGE
    # -------------------------
    map_crs = projection["cartopy"]
    map_ax.set_xlim(xmin, xmax)
    map_ax.set_ylim(ymin, ymax)
    map_ax.imshow(map_pil_image, extent=[xmin, xmax, ymin, ymax], origin='upper',
                  transform=map_crs, interpolation="nearest", zorder=1)

    # Without a region outline (bounding-box regions such as continents) the
    # data needs coastlines and borders to be readable.
    if not uploaded_geojson and not boundary_geojson and geo_bounds:
        _draw_context_lines(map_ax, geo_bounds)

    # -------------------------
    # GRATICULE (latitude / longitude lines, labelled on the left and bottom)
    # -------------------------
    try:
        gl = map_ax.gridlines(draw_labels=True, linewidth=0.4, color='gray', alpha=0.3,
                              linestyle='--', x_inline=False, y_inline=False, zorder=4)
        gl.top_labels = False
        gl.right_labels = False
        gl.rotate_labels = False
        gl.xlabel_style = {'size': 8, 'color': _TICK_COL}
        gl.ylabel_style = {'size': 8, 'color': _TICK_COL}
    except Exception as e:
        print(f"Graticule skipped: {e}")

    # -------------------------
    # REGION BOUNDARY
    # -------------------------
    if uploaded_geojson:
        draw_geojson_outline(map_ax, uploaded_geojson, color="black", linewidth=1.4)
    elif boundary_geojson:
        draw_geojson_outline(map_ax, boundary_geojson, color=_TEXT_DARK, linewidth=1.1)

    # -------------------------
    # SCALE BAR (omitted on near-global lat/lon maps, where no single scale holds)
    # -------------------------
    wide_geographic = (not projection["metric"]) and (xmax - xmin) > 40
    if not wide_geographic:
        _draw_map_scale_bar(map_ax, extent, projection, lat_mid)

    for spine in map_ax.spines.values():
        spine.set_edgecolor(_TEXT_DARK)
        spine.set_linewidth(0.9)
    map_ax.set_title("")

    # -------------------------
    # SIDE PANEL
    # -------------------------
    ap.axis('off')
    ap.set_facecolor(_PANEL_BG)
    ap.add_patch(mpatches.Rectangle((0, 0), 1, 1, fill=False, lw=1.0,
                                    edgecolor=_FRAME_COL, transform=ap.transAxes))

    region_text = "\n".join(textwrap.wrap(ascii_label(region_name), 24)[:2])
    ap.text(0.5, 0.965, region_text, ha='center', va='top', fontsize=10.5, weight='bold',
            color=_TEXT_DARK, transform=ap.transAxes, linespacing=1.25)
    y = 0.90

    # North arrow. On wide equal-area maps north is not the same direction
    # everywhere, so the graticule shows it instead.
    if projection["kind"] != "laea":
        ap.text(0.5, y, "N", ha='center', va='top', fontsize=8.5, weight='bold',
                color=_TEXT_DARK, transform=ap.transAxes)
        ap.add_patch(mpatches.FancyArrow(
            0.5, y - 0.105, 0, 0.05, width=0.004, head_width=0.03, head_length=0.028,
            color="#111827", transform=ap.transAxes, zorder=5))
        y -= 0.135

    # Locator map
    if geo_bounds:
        locator_h = 0.20
        if _draw_locator(ap, [0.10, y - locator_h, 0.80, locator_h], geo_bounds,
                         uploaded_geojson or boundary_geojson):
            y -= locator_h + 0.035

    ap.plot([0.08, 0.92], [y, y], color=_FRAME_COL, lw=0.6, transform=ap.transAxes)
    y -= 0.03

    # Legend
    palette = vis_params_gee.get("palette")
    if lulc_legend:
        _draw_class_legend(ap, lulc_legend, display_label, y)
    elif is_rgb or not palette:
        _draw_composite_legend(ap, vis_params_gee.get("bands", []), y)
    else:
        _draw_colorbar_legend(ap, palette, float(vis_params_gee.get("min", 0)),
                              float(vis_params_gee.get("max", 1)), display_label, y)
        if stats_lines:
            _draw_stats_block(ap, stats_lines, y - 0.27)

    # -------------------------
    # CREDIT BLOCK
    # -------------------------
    if credit_lines:
        wrapped = []
        for line in credit_lines:
            wrapped.extend(textwrap.wrap(ascii_label(line), 150) or [""])
        fig.text(0.125, 0.055, "\n".join(wrapped), ha="left", va="top", fontsize=6.8,
                 color=_TEXT_MUTED, linespacing=1.5)

    outputs = {}
    for fmt in ("png", "pdf"):
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=300, bbox_inches='tight', pad_inches=0.18)
        outputs[fmt] = buf.getvalue()
    plt.close(fig)
    return outputs


# ====================== MULTI-MAP FIGURE ======================

# Layout of the grid of maps, in inches. The grid is fitted into a page-sized
# box; the figure then grows around it for the title, legend and credits.
_GRID_MAX_W, _GRID_MAX_H = 15.0, 9.6
_CELL_MAX = 6.5         # no single map needs to be larger than this
_LABEL_H = 0.27         # strip above each map for its label
_GAP_X, _GAP_Y = 0.16, 0.13


def choose_grid_layout(n_maps: int, aspect: float) -> dict:
    """
    Rows and columns for `n_maps` maps of the given width/height ratio.

    Every arrangement is tried and the one that draws the maps largest on the
    page wins, so tall regions get many columns (12 maps: 6 x 2), wide regions
    many rows (3 x 4) and compact ones something in between (4 x 3). Empty
    cells count against an arrangement.

    Returns {"rows", "cols", "cell_w", "cell_h" (inches), "panel_px"}, where
    panel_px is the longest side to render each map at for 300 dpi.
    """
    aspect = float(np.clip(aspect, 0.05, 20.0))
    best, best_score = None, -1.0
    for cols in range(1, n_maps + 1):
        rows = int(np.ceil(n_maps / cols))
        room_w = (_GRID_MAX_W - (cols - 1) * _GAP_X) / cols
        room_h = (_GRID_MAX_H - rows * _LABEL_H - (rows - 1) * _GAP_Y) / rows
        if room_w <= 0 or room_h <= 0:
            continue
        cell_w = min(room_w, room_h * aspect)
        cell_h = cell_w / aspect
        shrink = min(1.0, _CELL_MAX / max(cell_w, cell_h))
        cell_w, cell_h = cell_w * shrink, cell_h * shrink
        empty_share = (rows * cols - n_maps) / (rows * cols)
        score = cell_w * cell_h * (1.0 - 0.5 * empty_share)
        if score > best_score * 1.0001:
            best, best_score = {"rows": rows, "cols": cols, "cell_w": cell_w, "cell_h": cell_h}, score
    best["panel_px"] = int(np.clip(np.ceil(max(best["cell_w"], best["cell_h"]) * 300 / 64) * 64, 384, 1024))
    return best


def _draw_strip_legend(lg, width, height, vis_params_gee, display_label, is_rgb, lulc_legend):
    """
    The figure's one shared legend, in a strip under the maps. `lg` is an axes
    whose data coordinates are inches (0..width, 0..height).
    """
    palette = vis_params_gee.get("palette")
    if lulc_legend:
        lg.text(width / 2, height - 0.05, ascii_label(display_label), ha="center", va="top",
                fontsize=8.5, weight="bold", color=_TEXT_DARK)
        n_cols, n_rows = _class_legend_grid(len(lulc_legend), width)
        col_w = width / n_cols
        for i, item in enumerate(lulc_legend):
            x = (i // n_rows) * col_w + 0.1
            y = height - 0.42 - (i % n_rows) * 0.2
            label = textwrap.shorten(ascii_label(item["label"]), int(col_w * 15), placeholder="...")
            if not item.get("color"):
                lg.text(x, y, label, ha="left", va="center", fontsize=7, style="italic", color=_TEXT_MUTED)
                continue
            lg.add_patch(mpatches.Rectangle((x, y - 0.065), 0.2, 0.13, facecolor=item["color"],
                                            edgecolor="#333", lw=0.5))
            lg.text(x + 0.28, y, label, ha="left", va="center", fontsize=7, color=_TEXT_DARK)
    elif is_rgb or not palette:
        bands = vis_params_gee.get("bands", [])
        channels = [("Red", "#d64545"), ("Green", "#3f9d4b"), ("Blue", "#3f6fd1")]
        entry_w = min(2.2, width / 3)
        x0 = (width - 3 * entry_w) / 2
        lg.text(width / 2, height - 0.05, "Colour composite", ha="center", va="top",
                fontsize=8.5, weight="bold", color=_TEXT_DARK)
        for i, (channel, colour) in enumerate(channels):
            band = bands[i] if i < len(bands) else channel
            lg.add_patch(mpatches.Rectangle((x0 + i * entry_w, 0.1), 0.2, 0.13, facecolor=colour,
                                            edgecolor="#333", lw=0.5))
            lg.text(x0 + i * entry_w + 0.28, 0.165, _CHANNEL_BAND_NAMES.get(band, str(band)),
                    ha="left", va="center", fontsize=7, color=_TEXT_DARK)
    else:
        bar_w = min(6.0, width * 0.7)
        lg.text(width / 2, height - 0.05, ascii_label(display_label), ha="center", va="top",
                fontsize=8.5, weight="bold", color=_TEXT_DARK)
        cax = lg.inset_axes([(width - bar_w) / 2, height - 0.5, bar_w, 0.17], transform=lg.transData)
        _fill_colorbar(cax, palette, float(vis_params_gee.get("min", 0)),
                       float(vis_params_gee.get("max", 1)), tick_size=7)


def _class_legend_grid(n_classes: int, width: float) -> tuple[int, int]:
    """Columns and rows of a class legend laid out across `width` inches."""
    n_cols = int(max(1, min(n_classes, width // 2.3)))
    return n_cols, int(np.ceil(n_classes / n_cols))


def render_composite_figure(
    panels,
    layout,
    extent,
    projection,
    title,
    vis_params_gee,
    display_label,
    is_rgb,
    geo_bounds,
    subtitle: str | None = None,
    lulc_legend=None,
    uploaded_geojson=None,
    boundary_geojson=None,
    credit_lines: list[str] | None = None,
    **_unused,
):
    """
    Lay out several maps of the same region in one figure.

    panels: [{"image": PIL image covering `extent`, "label": str, "note": str | None}],
            in reading order. Every map uses the same extent, projection and
            colours, so one legend serves them all.
    layout: dict from choose_grid_layout()
    The other arguments are those of render_cartographic_figure().

    Returns {"png": bytes, "pdf": bytes}.
    """
    xmin, xmax, ymin, ymax = extent
    rows, cols = layout["rows"], layout["cols"]
    cell_w, cell_h = layout["cell_w"], layout["cell_h"]
    lat_mid = (geo_bounds["lat_min"] + geo_bounds["lat_max"]) / 2.0 if geo_bounds else 0.0

    left, right = 0.62, 0.35
    top = 0.95 if subtitle else 0.68
    grid_w = cols * cell_w + (cols - 1) * _GAP_X
    grid_h = rows * (cell_h + _LABEL_H) + (rows - 1) * _GAP_Y
    fig_w = max(left + grid_w + right, 9.0)
    inner_w = fig_w - left - right
    grid_x = left + (inner_w - grid_w) / 2

    palette = vis_params_gee.get("palette")
    if lulc_legend:
        legend_h = 0.42 + _class_legend_grid(len(lulc_legend), inner_w)[1] * 0.2
    elif is_rgb or not palette:
        legend_h = 0.55
    else:
        legend_h = 0.85
    credits = []
    for line in credit_lines or []:
        credits.extend(textwrap.wrap(ascii_label(line), int(inner_w * 17)) or [""])
    credit_h = 0.15 * len(credits) + (0.12 if credits else 0.0)
    lon_label_h = 0.3
    base = 0.1
    legend_y = base + credit_h
    grid_y = legend_y + legend_h + lon_label_h
    fig_h = grid_y + grid_h + top

    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")

    # -------------------------
    # TITLE + PERIOD
    # -------------------------
    title = ascii_label(title)
    title_size = float(np.clip(fig_w * 0.92 * 72 / (0.6 * max(len(title), 1)), 11, 17))
    fig.text(0.5, (fig_h - 0.3) / fig_h, title, ha="center", va="center", fontsize=title_size,
             fontweight="bold", color=_TEXT_DARK)
    if subtitle:
        fig.text(0.5, (fig_h - 0.63) / fig_h, ascii_label(subtitle), ha="center", va="center",
                 fontsize=10.5, color=_TEXT_MUTED)

    # -------------------------
    # MAPS
    # -------------------------
    map_crs = projection["cartopy"]
    label_size = 8.5 if cell_w >= 2.0 else 7.5
    wide_geographic = (not projection["metric"]) and (xmax - xmin) > 40
    for i, panel in enumerate(panels):
        r, c = divmod(i, cols)
        x = grid_x + c * (cell_w + _GAP_X)
        y = grid_y + (rows - 1 - r) * (cell_h + _LABEL_H + _GAP_Y)
        ax = fig.add_axes([x / fig_w, y / fig_h, cell_w / fig_w, cell_h / fig_h], projection=map_crs)
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.imshow(panel["image"], extent=[xmin, xmax, ymin, ymax], origin="upper",
                  transform=map_crs, interpolation="nearest", zorder=1)
        if not uploaded_geojson and not boundary_geojson and geo_bounds:
            _draw_context_lines(ax, geo_bounds)

        # Graticule on every map; its labels only down the left side and along
        # the bottom of the grid, where they serve the whole row or column.
        try:
            gl = ax.gridlines(draw_labels=True, linewidth=0.3, color="gray", alpha=0.3,
                              linestyle="--", x_inline=False, y_inline=False, zorder=4)
            gl.xlocator = mticker.MaxNLocator(nbins=3)
            gl.ylocator = mticker.MaxNLocator(nbins=4)
            gl.top_labels = False
            gl.right_labels = False
            gl.left_labels = (c == 0)
            gl.bottom_labels = (i + cols >= len(panels))
            gl.rotate_labels = False
            gl.xlabel_style = {"size": 6, "color": _TICK_COL}
            gl.ylabel_style = {"size": 6, "color": _TICK_COL}
        except Exception as e:
            print(f"Graticule skipped: {e}")

        if uploaded_geojson:
            draw_geojson_outline(ax, uploaded_geojson, color="black", linewidth=0.9)
        elif boundary_geojson:
            draw_geojson_outline(ax, boundary_geojson, color=_TEXT_DARK, linewidth=0.7)

        # One scale bar serves all the maps: they share extent and projection.
        if i == (rows - 1) * cols and not wide_geographic:
            _draw_map_scale_bar(ax, extent, projection, lat_mid, compact=cell_w < 3.2)

        for spine in ax.spines.values():
            spine.set_edgecolor(_TEXT_DARK)
            spine.set_linewidth(0.7)

        label = ascii_label(panel["label"])
        note = ascii_label(panel.get("note") or "")
        y_text = (y + cell_h + 0.075) / fig_h
        fig.text(x / fig_w, y_text, label, ha="left", va="bottom", fontsize=label_size,
                 fontweight="bold", color=_TEXT_DARK)
        # The note is dropped rather than allowed to run into the label.
        if note and (len(label) * 0.62 * label_size + len(note) * 0.58 * 6.5 + 8) < cell_w * 72:
            fig.text((x + cell_w) / fig_w, y_text, note, ha="right", va="bottom", fontsize=6.5,
                     color=_TEXT_MUTED)

    # -------------------------
    # SHARED LEGEND + NORTH ARROW
    # -------------------------
    lg = fig.add_axes([left / fig_w, legend_y / fig_h, inner_w / fig_w, legend_h / fig_h])
    lg.set_xlim(0, inner_w)
    lg.set_ylim(0, legend_h)
    lg.axis("off")
    _draw_strip_legend(lg, inner_w, legend_h, vis_params_gee, display_label, is_rgb, lulc_legend)
    if projection["kind"] != "laea":
        lg.text(inner_w - 0.2, legend_h - 0.05, "N", ha="center", va="top", fontsize=8.5,
                weight="bold", color=_TEXT_DARK)
        lg.add_patch(mpatches.FancyArrow(inner_w - 0.2, legend_h - 0.5, 0, 0.17, width=0.012,
                                         head_width=0.09, head_length=0.1, color="#111827", zorder=5))

    # -------------------------
    # CREDIT BLOCK
    # -------------------------
    if credits:
        fig.text(left / fig_w, (base + credit_h - 0.06) / fig_h, "\n".join(credits), ha="left", va="top",
                 fontsize=6.8, color=_TEXT_MUTED, linespacing=1.5)

    outputs = {}
    for fmt in ("png", "pdf"):
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=300, bbox_inches="tight", pad_inches=0.18)
        outputs[fmt] = buf.getvalue()
    plt.close(fig)
    return outputs

"""
projection.py
-------------
Chooses a map projection suited to the region being mapped, and works out
the region's extent in that projection.

Plain latitude/longitude stretches shapes east-west away from the equator
(by 2x at 60 degrees). Instead:

  - regions up to ~9 degrees wide   -> the local UTM zone (true shape, metres)
  - wider regions, up to continents -> Lambert azimuthal equal-area centred
                                       on the region
  - near-global extents             -> geographic (lat/lon)

Public API:
  choose_map_projection(geo_bounds) -> dict
  projected_extent(projection, geo_bounds, outline_geojson) -> [xmin, xmax, ymin, ymax]
"""

from __future__ import annotations

import cartopy.crs as ccrs
import numpy as np
from pyproj import CRS, Transformer

_LAEA_WKT = (
    'PROJCS["Lambert Azimuthal Equal Area",'
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Lambert_Azimuthal_Equal_Area"],'
    'PARAMETER["latitude_of_center",{lat:.4f}],PARAMETER["longitude_of_center",{lon:.4f}],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1]]'
)


def choose_map_projection(geo_bounds: dict | None) -> dict:
    """
    Pick a projection for the region.

    Returns a dict with:
      kind    - "utm" | "laea" | "geographic"
      name    - human-readable name for the map's credit line
      crs     - CRS string Earth Engine accepts (EPSG code or WKT)
      cartopy - matching cartopy CRS for drawing
      pyproj  - matching pyproj CRS for coordinate transforms
      metric  - True when map units are metres
    """
    geographic = {
        "kind": "geographic", "name": "Geographic, WGS 84 (EPSG:4326)",
        "crs": "EPSG:4326", "cartopy": ccrs.PlateCarree(),
        "pyproj": CRS.from_epsg(4326), "metric": False,
    }
    if not geo_bounds:
        return geographic

    lon_span = geo_bounds["lon_max"] - geo_bounds["lon_min"]
    lat_span = geo_bounds["lat_max"] - geo_bounds["lat_min"]
    lon_mid = (geo_bounds["lon_min"] + geo_bounds["lon_max"]) / 2.0
    lat_mid = (geo_bounds["lat_min"] + geo_bounds["lat_max"]) / 2.0

    if lon_span > 120 or lat_span > 100:
        return geographic

    if lon_span <= 9 and max(abs(geo_bounds["lat_min"]), abs(geo_bounds["lat_max"])) < 80:
        zone = int(min(max(np.floor((lon_mid + 180) / 6) + 1, 1), 60))
        south = lat_mid < 0
        epsg = (32700 if south else 32600) + zone
        return {
            "kind": "utm", "name": f"WGS 84 / UTM zone {zone}{'S' if south else 'N'} (EPSG:{epsg})",
            "crs": f"EPSG:{epsg}", "cartopy": ccrs.UTM(zone, southern_hemisphere=south),
            "pyproj": CRS.from_epsg(epsg), "metric": True,
        }

    wkt = _LAEA_WKT.format(lat=lat_mid, lon=lon_mid)
    return {
        "kind": "laea",
        "name": f"Lambert azimuthal equal-area, centred {abs(lat_mid):.1f}°{'N' if lat_mid >= 0 else 'S'} "
                f"{abs(lon_mid):.1f}°{'E' if lon_mid >= 0 else 'W'}",
        "crs": wkt,
        "cartopy": ccrs.LambertAzimuthalEqualArea(central_longitude=round(lon_mid, 4),
                                                  central_latitude=round(lat_mid, 4)),
        "pyproj": CRS.from_wkt(wkt), "metric": True,
    }


def _outline_points(geojson: dict | None) -> list:
    """All [lon, lat] vertices of a GeoJSON geometry / Feature / FeatureCollection."""
    points: list = []

    def _walk(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            points.append(coords[:2])
        else:
            for c in coords:
                _walk(c)

    def _geom(g):
        if not g:
            return
        if g.get("type") == "GeometryCollection":
            for sub in g.get("geometries", []):
                _geom(sub)
        else:
            _walk(g.get("coordinates"))

    if geojson:
        gtype = geojson.get("type")
        if gtype == "FeatureCollection":
            for feat in geojson.get("features", []):
                _geom(feat.get("geometry"))
        elif gtype == "Feature":
            _geom(geojson.get("geometry"))
        else:
            _geom(geojson)
    return points


def projected_extent(projection: dict, geo_bounds: dict, outline_geojson: dict | None = None,
                     margin: float = 0.04) -> list[float]:
    """
    Extent of the region in the map projection as [xmin, xmax, ymin, ymax],
    with a small margin so the region does not touch the map frame.

    Uses the region's outline when available (tight fit); otherwise the edges
    of its lat/lon bounding box, sampled densely because straight lat/lon
    edges become curves once projected.
    """
    points = _outline_points(outline_geojson)
    if not points:
        lons = np.linspace(geo_bounds["lon_min"], geo_bounds["lon_max"], 60)
        lats = np.linspace(geo_bounds["lat_min"], geo_bounds["lat_max"], 60)
        points = ([[lo, geo_bounds["lat_min"]] for lo in lons] + [[lo, geo_bounds["lat_max"]] for lo in lons] +
                  [[geo_bounds["lon_min"], la] for la in lats] + [[geo_bounds["lon_max"], la] for la in lats])

    lon = np.array([p[0] for p in points], dtype=float)
    lat = np.array([p[1] for p in points], dtype=float)
    if projection["kind"] == "geographic":
        xs, ys = lon, lat
    else:
        transformer = Transformer.from_crs(4326, projection["pyproj"], always_xy=True)
        xs, ys = transformer.transform(lon, lat)
        xs, ys = np.asarray(xs), np.asarray(ys)
        ok = np.isfinite(xs) & np.isfinite(ys)
        xs, ys = xs[ok], ys[ok]

    xmin, xmax, ymin, ymax = float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())
    pad_x = (xmax - xmin) * margin
    pad_y = (ymax - ymin) * margin
    extent = [xmin - pad_x, xmax + pad_x, ymin - pad_y, ymax + pad_y]
    if projection["kind"] == "geographic":
        extent = [max(extent[0], -180.0), min(extent[1], 180.0),
                  max(extent[2], -90.0), min(extent[3], 90.0)]
    return extent

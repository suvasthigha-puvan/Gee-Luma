"""
geojson_helpers.py
------------------
GeoJSON parsing, CRS reprojection, geometry validation,
and conversion to ee.Geometry for use with Google Earth Engine.
"""

import re
import ee

try:
    from pyproj import Transformer, CRS
    PYPROJ_AVAILABLE = True
except ImportError:
    PYPROJ_AVAILABLE = False

# ====================== SHAPEFILE / GEOJSON HELPERS ======================

def _reproject_coords(coords, transformer):
    """Recursively reproject a GeoJSON coordinate array, stripping Z/M to [lon, lat]."""
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        x, y = transformer.transform(coords[0], coords[1])
        return [x, y]
    return [_reproject_coords(c, transformer) for c in coords]


def _ensure_wgs84(geojson: dict) -> dict:
    """
    Reproject a GeoJSON FeatureCollection / Feature / Geometry to WGS-84 (EPSG:4326).
    Handles any CRS declared in the GeoJSON (name, EPSG code, WKT, PROJ string).
    If no CRS declared, assumes WGS-84 and returns as-is.
    """
    crs_node = geojson.get("crs")
    src_epsg = None

    if crs_node:
        props = crs_node.get("properties", {})
        name  = props.get("name", "")
        # Common patterns: "EPSG:32644", "urn:ogc:def:crs:EPSG::4326", plain integer
        import re as _re
        m = _re.search(r"EPSG[:\s]*(\d+)", name, _re.IGNORECASE)
        if m:
            src_epsg = int(m.group(1))
        elif name.upper().startswith("urn:ogc:def:crs:epsg"):
            parts = name.split(":")
            try:
                src_epsg = int(parts[-1])
            except ValueError:
                pass

    if src_epsg is None or src_epsg == 4326:
        return geojson  # already WGS-84

    if not PYPROJ_AVAILABLE:
        raise RuntimeError(
            f"The uploaded file uses EPSG:{src_epsg} but `pyproj` is not installed. "
            "Run `pip install pyproj` to enable automatic reprojection."
        )

    transformer = Transformer.from_crs(src_epsg, 4326, always_xy=True)

    def _reproject_geometry(geom):
        if geom is None:
            return geom
        return {**geom, "coordinates": _reproject_coords(geom["coordinates"], transformer)}

    def _reproject_feature(feat):
        return {**feat, "geometry": _reproject_geometry(feat.get("geometry"))}

    geojson_type = geojson.get("type", "")
    if geojson_type == "FeatureCollection":
        return {**geojson,
                "features": [_reproject_feature(f) for f in geojson.get("features", [])],
                "crs": None}
    elif geojson_type == "Feature":
        return _reproject_feature(geojson)
    else:
        return _reproject_geometry(geojson)


def _clean_geometry(geom: dict) -> dict | None:
    """
    Validate and clean a GeoJSON geometry dict.
    Returns None if the geometry is unusable (null, empty coords, unknown type).
    Strips Z/M coordinates down to [lon, lat] pairs so GEE doesn't reject them.
    """
    if not geom or not isinstance(geom, dict):
        return None
    gtype = geom.get("type", "")
    if gtype not in ("Point", "MultiPoint", "LineString", "MultiLineString",
                     "Polygon", "MultiPolygon", "GeometryCollection"):
        return None

    if gtype == "GeometryCollection":
        cleaned = [_clean_geometry(g) for g in geom.get("geometries", [])]
        cleaned = [g for g in cleaned if g is not None]
        return {"type": "GeometryCollection", "geometries": cleaned} if cleaned else None

    def _strip_z(coords):
        """Recursively strip Z (and beyond) from coordinate arrays."""
        if not coords:
            return coords
        if isinstance(coords[0], (int, float)):
            return coords[:2]  # keep only [lon, lat]
        return [_strip_z(c) for c in coords]

    coords = geom.get("coordinates")
    if not coords:
        return None
    return {"type": gtype, "coordinates": _strip_z(coords)}


def geojson_to_ee_geometry(geojson: dict) -> ee.Geometry:
    """
    Convert a WGS-84 GeoJSON dict (FeatureCollection / Feature / Geometry)
    to an ee.Geometry.

    Strategy for FeatureCollections:
    - Clean + validate every feature geometry (strip Z-coords, filter nulls)
    - Build an ee.FeatureCollection from the cleaned features
    - Use .geometry() on the collection, which GEE unions efficiently server-side
    - Falls back to dissolving via ee.Geometry.MultiPolygon for polygon-only sets
    """
    gtype = geojson.get("type", "")

    if gtype == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            raise ValueError("FeatureCollection has no features.")

        # Clean all geometries
        clean_features = []
        for feat in features:
            raw_geom = feat.get("geometry")
            clean_geom = _clean_geometry(raw_geom)
            if clean_geom is None:
                continue  # skip null / empty geometries
            clean_features.append({
                "type": "Feature",
                "geometry": clean_geom,
                "properties": {},   # strip properties  GEE doesn't need them
            })

        if not clean_features:
            raise ValueError(
                "No valid geometries found in the FeatureCollection after cleaning. "
                "Check that your GeoJSON contains Polygon or MultiPolygon features."
            )

        try:
            ee_fc = ee.FeatureCollection(clean_features)
            return ee_fc.geometry(maxError=1)
        except Exception:
            pass

        # Try approach 2: dissolve polygons into a single MultiPolygon
        all_rings = []
        for feat in clean_features:
            g = feat["geometry"]
            if g["type"] == "Polygon":
                all_rings.append(g["coordinates"])
            elif g["type"] == "MultiPolygon":
                all_rings.extend(g["coordinates"])

        if all_rings:
            try:
                return ee.Geometry.MultiPolygon(all_rings)
            except Exception:
                pass

        # Try approach 3: union geometry by geometry (chunked to avoid deep recursion)
        try:
            chunk_size = 50
            chunks = [clean_features[i:i+chunk_size]
                      for i in range(0, len(clean_features), chunk_size)]
            chunk_geoms = []
            for chunk in chunks:
                ee_fc_chunk = ee.FeatureCollection(chunk)
                chunk_geoms.append(ee_fc_chunk.geometry(maxError=1))
            base = chunk_geoms[0]
            for cg in chunk_geoms[1:]:
                base = base.union(cg, maxError=1)
            return base
        except Exception as e:
            raise ValueError(
                f"Could not convert FeatureCollection to GEE geometry after 3 attempts. "
                f"Last error: {e}"
            )

    elif gtype == "Feature":
        raw_geom  = geojson.get("geometry")
        clean_geom = _clean_geometry(raw_geom)
        if clean_geom is None:
            raise ValueError("Feature has a null or invalid geometry.")
        return ee.Geometry(clean_geom)

    else:
        clean_geom = _clean_geometry(geojson)
        if clean_geom is None:
            raise ValueError(f"Unsupported or empty geometry type: '{gtype}'")
        return ee.Geometry(clean_geom)


def get_geojson_bounds(geojson: dict) -> dict:
    """Return {lon_min, lon_max, lat_min, lat_max} from a WGS-84 GeoJSON dict."""
    all_lons, all_lats = [], []

    def _collect(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            all_lons.append(coords[0])
            all_lats.append(coords[1])
        else:
            for c in coords:
                _collect(c)

    def _collect_feature(feat):
        geom = feat.get("geometry") or {}
        _collect(geom.get("coordinates", []))

    gtype = geojson.get("type", "")
    if gtype == "FeatureCollection":
        for f in geojson.get("features", []):
            _collect_feature(f)
    elif gtype == "Feature":
        _collect_feature(geojson)
    else:
        _collect(geojson.get("coordinates", []))

    if not all_lons:
        return None
    return {"lon_min": min(all_lons), "lon_max": max(all_lons),
            "lat_min": min(all_lats), "lat_max": max(all_lats)}


def get_geojson_label(geojson: dict) -> str:
    """Try to extract a human-readable name from the GeoJSON properties."""
    for name_key in ("NAME", "name", "Name", "ADMIN", "admin",
                     "shapeName", "SHAPENAME", "ADM0_NAME", "REGION", "region"):
        if geojson.get("type") == "FeatureCollection":
            for feat in geojson.get("features", [])[:1]:
                val = feat.get("properties", {}).get(name_key)
                if val:
                    return str(val)
        elif geojson.get("type") == "Feature":
            val = geojson.get("properties", {}).get(name_key)
            if val:
                return str(val)
    n = len(geojson.get("features", [])) if geojson.get("type") == "FeatureCollection" else 1
    return f"Custom Region ({n} polygon{'s' if n > 1 else ''})"

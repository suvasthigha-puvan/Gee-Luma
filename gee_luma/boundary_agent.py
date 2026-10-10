"""
boundary_agent.py
-----------------
Resolves a place name to an administrative boundary from the geoBoundaries
dataset, for any country.

Uses:
  - ADM0 (Country):          WM/geoLab/geoBoundaries/600/ADM0
  - ADM1 (Province / State): WM/geoLab/geoBoundaries/600/ADM1
  - ADM2 (District):         WM/geoLab/geoBoundaries/600/ADM2

The admin level and parent country normally come from the LLM agent, which
knows that "Galle" is a district of Sri Lanka. When they are missing, every
level is tried in turn (country first) rather than guessing from the name.
"""

import difflib
import re
import unicodedata

import ee
from typing import Dict, List, Optional, Tuple


class BoundaryAgent:
    """Looks up administrative boundaries in geoBoundaries."""

    DATASETS = {
        0: 'WM/geoLab/geoBoundaries/600/ADM0',
        1: 'WM/geoLab/geoBoundaries/600/ADM1',
        2: 'WM/geoLab/geoBoundaries/600/ADM2',
    }

    LEVEL_NAMES = {0: "Country", 1: "Province / State", 2: "District"}

    # Words in the region name that state the admin level explicitly.
    # Matched as whole words only ("Galle" must not match "all").
    _LEVEL_WORDS = {
        0: {'country', 'nation', 'national'},
        1: {'province', 'state', 'region', 'territory', 'provincial'},
        2: {'district', 'county', 'municipality', 'borough', 'commune', 'departement'},
    }

    # Trailing admin-level words that geoBoundaries' shapeName field never
    # includes (it stores bare place names, e.g. "Jaffna" not "Jaffna District").
    _ADMIN_SUFFIXES = {
        'district', 'province', 'state', 'county', 'region',
        'territory', 'zone', 'municipality',
    }

    @staticmethod
    def core_name(region_name: str) -> str:
        """
        Strip a trailing admin-level word so shapeName lookups succeed.
        "Jaffna District" -> "Jaffna", "Western Province" -> "Western".
        Leaves names with no such suffix untouched.
        """
        words = region_name.strip().split()
        if len(words) > 1 and words[-1].lower() in BoundaryAgent._ADMIN_SUFFIXES:
            return " ".join(words[:-1])
        return region_name.strip()

    @staticmethod
    def detect_admin_level(region_name: str) -> Tuple[Optional[int], str]:
        """
        Read an explicit admin level out of the region name, if it states one.

        Returns (admin_level, description). admin_level is None when the name
        gives no hint ("Galle", "India") - callers should then try all levels.
        """
        words = set(region_name.lower().replace(',', ' ').split())
        for level in (2, 1, 0):
            if words & BoundaryAgent._LEVEL_WORDS[level]:
                return level, BoundaryAgent.LEVEL_NAMES[level]
        return None, "Auto"

    @staticmethod
    def get_boundary_dataset(admin_level: int) -> str:
        """GEE dataset path for an admin level (0, 1 or 2)."""
        return BoundaryAgent.DATASETS.get(admin_level, BoundaryAgent.DATASETS[2])

    # geoBoundaries stores names in each country's own convention
    # ("Galle District", "Western Province", "Bayern", "Maharashtra" with
    # diacritics), so names are compared in a normalised form: ASCII-folded,
    # lower-case, punctuation removed, trailing admin word dropped.
    _NORMALISE_SUFFIXES = _ADMIN_SUFFIXES | {
        'prefecture', 'governorate', 'department', 'oblast', 'division', 'parish', 'canton',
    }

    _names_cache: Dict[Tuple[int, str], List[Tuple[str, str]]] = {}

    @staticmethod
    def _normalise(name: str) -> str:
        text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
        words = text.split()
        if len(words) > 1 and words[-1] in BoundaryAgent._NORMALISE_SUFFIXES:
            words = words[:-1]
        return " ".join(words)

    @staticmethod
    def _names(level: int, iso3: str = "") -> List[Tuple[str, str]]:
        """
        (shapeName, shapeGroup) pairs at an admin level - all countries for
        level 0, one country's units for levels 1 and 2. Cached per process.
        """
        key = (level, iso3)
        if key not in BoundaryAgent._names_cache:
            col = ee.FeatureCollection(BoundaryAgent.DATASETS[level])
            if level > 0:
                col = col.filter(ee.Filter.eq('shapeGroup', iso3))
            info = ee.Dictionary({
                'names': col.aggregate_array('shapeName'),
                'groups': col.aggregate_array('shapeGroup'),
            }).getInfo()
            BoundaryAgent._names_cache[key] = list(zip(info['names'], info['groups']))
        return BoundaryAgent._names_cache[key]

    @staticmethod
    def _best_match(candidates: List[str], names: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
        """
        Pick the (shapeName, shapeGroup) that a candidate spelling refers to:
        exact normalised match first, then a near-identical spelling
        (transliteration differences). Never a mere substring, so "Western"
        cannot match "North Western".
        """
        by_norm: Dict[str, Tuple[str, str]] = {}
        for pair in names:
            by_norm.setdefault(BoundaryAgent._normalise(pair[0]), pair)
        wanted = [BoundaryAgent._normalise(c) for c in candidates if c and str(c).strip()]
        wanted = [w for w in wanted if w]
        for w in wanted:
            if w in by_norm:
                return by_norm[w]
        # Same words in another order ("South Korea" is stored as "Korea, South")
        by_words = {frozenset(n.split()): pair for n, pair in by_norm.items()}
        for w in wanted:
            if frozenset(w.split()) in by_words:
                return by_words[frozenset(w.split())]
        # Some names are stored with "?" where an accented letter was lost
        # ("Mah?r?shtra"); treat each "?" as any single letter.
        for shape_name, group in names:
            if "?" not in shape_name:
                continue
            pattern = ".".join(re.escape(part) for part in shape_name.lower().split("?"))
            for c in candidates:
                folded = unicodedata.normalize("NFKD", str(c)).encode("ascii", "ignore").decode("ascii")
                if re.fullmatch(pattern + r"( \w+)?", folded.strip().lower()):
                    return (shape_name, group)
        for w in wanted:
            close = difflib.get_close_matches(w, list(by_norm), n=1, cutoff=0.88)
            if close:
                return by_norm[close[0]]
        return None

    @staticmethod
    def resolve(region_name: str, country_name: Optional[str] = None,
                admin_level: Optional[int] = None, country_iso3: Optional[str] = None,
                aliases: Optional[List[str]] = None) -> Optional[Dict]:
        """
        Find the boundary for a place name.

        Args:
            region_name:  place to find ("Sri Lanka", "Western Province", "Galle")
            country_name: country the place is in
            admin_level:  0, 1 or 2 if known. Tried first; the other levels are
                          still tried afterwards in case the hint was wrong.
            country_iso3: ISO 3166-1 alpha-3 code of the country ("LKA"). More
                          reliable than the name ("South Korea" is stored as
                          "Korea, South").
            aliases:      other spellings of the region, e.g. the local-language
                          name ("Bayern" for "Bavaria")

        Returns None if nothing matches, otherwise a dict with:
            geometry    - ee.Geometry (server-side, not downloaded)
            name        - matched shapeName
            admin_level - level the match was found at
            admin_type  - "Country" / "Province / State" / "District"
        """
        if not region_name or not region_name.strip():
            return None
        candidates = [region_name] + [a for a in (aliases or []) if isinstance(a, str)]

        def _result(level, shape_name, iso3):
            feature = (ee.FeatureCollection(BoundaryAgent.DATASETS[level])
                       .filter(ee.Filter.eq('shapeGroup', iso3))
                       .filter(ee.Filter.eq('shapeName', shape_name))
                       .first())
            return {
                'geometry': feature.geometry(),
                'name': shape_name,
                'admin_level': level,
                'admin_type': BoundaryAgent.LEVEL_NAMES[level],
            }

        countries = BoundaryAgent._names(0)

        # Which country are we in?
        iso3 = (country_iso3 or "").strip().upper()
        if not (len(iso3) == 3 and any(g == iso3 for _, g in countries)):
            iso3 = ""
            if country_name and country_name.strip():
                match = BoundaryAgent._best_match([country_name], countries)
                iso3 = match[1] if match else ""

        if admin_level not in (0, 1, 2):
            admin_level, _ = BoundaryAgent.detect_admin_level(region_name)
        levels = ([admin_level] if admin_level is not None else []) + \
                 [l for l in (0, 1, 2) if l != admin_level]

        for level in levels:
            if level == 0:
                # The region is a country if its name is a country name, or it
                # is the same name the agent gave as the containing country.
                match = BoundaryAgent._best_match(candidates, countries)
                if match is None and iso3 and country_name and \
                        BoundaryAgent._normalise(country_name) in \
                        {BoundaryAgent._normalise(c) for c in candidates}:
                    match = next(pair for pair in countries if pair[1] == iso3)
                if match:
                    return _result(0, match[0], match[1])
            elif iso3:
                match = BoundaryAgent._best_match(candidates, BoundaryAgent._names(level, iso3))
                if match:
                    return _result(level, match[0], match[1])
            else:
                # Country unknown: the whole world's units cannot be listed, so
                # ask the server for exact spellings, with and without suffix.
                spellings = []
                for c in candidates:
                    core = BoundaryAgent.core_name(c)
                    for base in (core, core.title()):
                        for form in [base] + [f"{base} {sfx.title()}" for sfx in
                                              ('district', 'province', 'state', 'county', 'region')]:
                            if form not in spellings:
                                spellings.append(form)
                info = (ee.FeatureCollection(BoundaryAgent.DATASETS[level])
                        .filter(ee.Filter.inList('shapeName', spellings))
                        .limit(1).select(['shapeName', 'shapeGroup'], None, False).getInfo())
                feats = info.get('features', [])
                if feats:
                    props = feats[0]['properties']
                    return _result(level, props['shapeName'], props['shapeGroup'])

        return None

    @staticmethod
    def outline_geojson(geometry: ee.Geometry, geo_bounds: Optional[Dict] = None) -> Optional[Dict]:
        """
        Download a boundary as GeoJSON for drawing on the map.

        The outline is simplified to about 1/2000 of the region's extent, which
        is below what is visible in print and keeps large countries small
        enough to download.
        """
        try:
            max_error_m = 100.0
            if geo_bounds:
                span_deg = max(geo_bounds["lon_max"] - geo_bounds["lon_min"],
                               geo_bounds["lat_max"] - geo_bounds["lat_min"])
                max_error_m = max(span_deg * 111_000 / 2000, 10.0)
            return geometry.simplify(maxError=max_error_m).getInfo()
        except Exception as e:
            print(f"Could not download boundary outline: {e}")
            return None

    @staticmethod
    def fetch_boundary(region_name: str, country_name: Optional[str] = None,
                       admin_level: Optional[int] = None) -> Optional[Dict]:
        """Boundary of a region as a GeoJSON geometry dict, or None if not found."""
        try:
            found = BoundaryAgent.resolve(region_name, country_name, admin_level)
            return found['geometry'].getInfo() if found else None
        except Exception as e:
            print(f"Error fetching boundary for '{region_name}': {e}")
            return None


def draw_geojson_outline(map_ax, geom_dict: Dict, color: str = "#0d1b2a",
                         linewidth: float = 1.5):
    """Draw a GeoJSON geometry / Feature / FeatureCollection outline on a cartopy axes."""
    import cartopy.crs as ccrs

    if not geom_dict:
        return
    gtype = geom_dict.get("type", "")

    def _ring(ring):
        xs = [c[0] for c in ring]
        ys = [c[1] for c in ring]
        map_ax.plot(xs, ys, color=color, linewidth=linewidth, linestyle="-",
                    transform=ccrs.PlateCarree(), zorder=5)

    if gtype == "FeatureCollection":
        for feat in geom_dict.get("features", []):
            draw_geojson_outline(map_ax, feat.get("geometry"), color, linewidth)
    elif gtype == "Feature":
        draw_geojson_outline(map_ax, geom_dict.get("geometry"), color, linewidth)
    elif gtype == "Polygon":
        for ring in geom_dict["coordinates"]:
            _ring(ring)
    elif gtype == "MultiPolygon":
        for poly_coords in geom_dict["coordinates"]:
            for ring in poly_coords:
                _ring(ring)
    elif gtype == "GeometryCollection":
        for g in geom_dict.get("geometries", []):
            draw_geojson_outline(map_ax, g, color, linewidth)

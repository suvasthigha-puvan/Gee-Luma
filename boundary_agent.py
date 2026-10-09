"""
boundary_agent.py
-----------------
Intelligent agent that detects administrative levels (Country, Province, District)
from user input and fetches the appropriate geoBoundaries dataset.

Uses:
  - ADM0 (Country): WM/geoLab/geoBoundaries/600/ADM0
  - ADM1 (Province): WM/geoLab/geoBoundaries/600/ADM1
  - ADM2 (District): WM/geoLab/geoBoundaries/600/ADM2
"""

import ee
import re
from typing import Dict, Tuple, Optional

class BoundaryAgent:
    """
    Intelligent agent for detecting and fetching administrative boundaries.
    Understands user input context to determine admin level.
    """
    
    # Admin level keywords and patterns
    COUNTRY_KEYWORDS = {
        'country', 'nation', 'whole', 'full', 'entire', 'national',
        'worldwide', 'global', 'complete', 'all', 'end-to-end'
    }
    
    PROVINCE_KEYWORDS = {
        'province', 'state', 'region', 'territory', 'zone',
        'administrative region', 'subdivision', 'provincial'
    }
    
    DISTRICT_KEYWORDS = {
        'district', 'county', 'municipality', 'local authority',
        'local government', 'borough', 'commune', 'departement'
    }

    # Known country-province-district hierarchies
    KNOWN_HIERARCHIES = {
        'sri_lanka': {
            'country': 'Sri Lanka',
            'provinces': ['Western', 'Central', 'Southern', 'Northern', 'Eastern', 
                         'North Western', 'North Central', 'Uva', 'Sabaragamuwa'],
            'districts': {
                'Northern': ['Jaffna', 'Mullaitivu', 'Vavuniya', 'Batticaloa'],
                'Central': ['Kandy', 'Matara', 'Nuwara Eliya'],
                'Western': ['Colombo', 'Gampaha', 'Kalutara'],
                'Southern': ['Galle', 'Matara', 'Hambantota'],
            }
        }
    }
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text for comparison."""
        return text.lower().strip().replace(' ', '_')

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
    def detect_admin_level(region_name: str, context: Optional[Dict] = None) -> Tuple[int, str]:
        """
        Detect administrative level from region name and context.
        
        Args:
            region_name: Name of the region (e.g., "Sri Lanka", "Western", "Jaffna")
            context: Optional context dict with keys like 'hierarchy', 'keywords'
        
        Returns:
            Tuple of (admin_level, detected_type)
            admin_level: 0 (Country), 1 (Province), 2 (District)
            detected_type: String description
        """
        
        region_lower = region_name.lower()
        
        # Check explicit context hints first
        if context:
            if 'hierarchy' in context:
                hierarchy = context['hierarchy'].lower()
                if 'country' in hierarchy or 'national' in hierarchy:
                    return 0, "Country"
                elif 'province' in hierarchy or 'state' in hierarchy:
                    return 1, "Province"
                elif 'district' in hierarchy or 'county' in hierarchy:
                    return 2, "District"
        
        # Check region name against known keywords
        words_in_region = set(region_lower.split())
        
        # Check for country-level indicators
        if any(kw in region_lower for kw in BoundaryAgent.COUNTRY_KEYWORDS):
            return 0, "Country"
        
        # Check for province-level indicators
        if any(kw in region_lower for kw in BoundaryAgent.PROVINCE_KEYWORDS):
            return 1, "Province"
        
        # Check for district-level indicators
        if any(kw in region_lower for kw in BoundaryAgent.DISTRICT_KEYWORDS):
            return 2, "District"
        
        # Check against known hierarchies (Sri Lanka example)
        sri_lanka = BoundaryAgent.KNOWN_HIERARCHIES.get('sri_lanka', {})
        
        # Check if it's a known country
        if region_name.lower() == sri_lanka.get('country', '').lower():
            return 0, "Country"
        
        # Check if it's a known province
        if region_name in sri_lanka.get('provinces', []):
            return 1, "Province"
        
        # Check if it's a known district
        for prov_districts in sri_lanka.get('districts', {}).values():
            if region_name in prov_districts:
                return 2, "District"
        
        # Default: Try to infer from capitalization and length
        # Longer, multi-word names are usually countries
        # Single words could be provinces or districts
        if len(region_name.split()) > 1:
            return 0, "Country (inferred)"
        
        # Single word: ambiguous - check if matches known district
        if region_name in ['Jaffna', 'Colombo', 'Galle', 'Kandy']:
            return 2, "District (pattern match)"
        
        # Default to district level for single region names
        return 2, "District (default)"
    
    @staticmethod
    def get_boundary_dataset(admin_level: int) -> str:
        """
        Get the appropriate geoBoundaries dataset for the admin level.
        
        Args:
            admin_level: 0 (Country), 1 (Province), 2 (District)
        
        Returns:
            GEE dataset path
        """
        datasets = {
            0: 'WM/geoLab/geoBoundaries/600/ADM0',
            1: 'WM/geoLab/geoBoundaries/600/ADM1',
            2: 'WM/geoLab/geoBoundaries/600/ADM2'
        }
        return datasets.get(admin_level, datasets[2])
    
    @staticmethod
    def fetch_boundary(region_name: str, country_name: Optional[str] = None,
                       admin_level: Optional[int] = None) -> Optional[Dict]:
        """
        Fetch boundary for a region from geoBoundaries.
        
        Args:
            region_name: Name of the region
            country_name: Country name for filtering (helpful for provinces/districts)
            admin_level: Explicit admin level (0, 1, or 2). If None, auto-detect.
        
        Returns:
            GeoJSON geometry or None if not found
        """
        try:
            # Auto-detect admin level if not provided
            if admin_level is None:
                admin_level, detected_type = BoundaryAgent.detect_admin_level(region_name)
                print(f"Detected '{region_name}' as: {detected_type} (ADM{admin_level})")

            # Get appropriate dataset
            dataset_path = BoundaryAgent.get_boundary_dataset(admin_level)
            collection = ee.FeatureCollection(dataset_path)

            # geoBoundaries' shapeName is a bare place name ("Jaffna"), so strip
            # trailing admin words ("Jaffna District") before matching against it.
            core = BoundaryAgent.core_name(region_name)

            # Try exact match on the stripped name first, then the raw name
            filtered = collection.filter(ee.Filter.inList('shapeName', [core, region_name]))

            # If no results, try substring match both directions
            if filtered.size().getInfo() == 0:
                filtered = collection.filter(
                    ee.Filter.stringContains('shapeName', core)
                )

            # If still no results and country provided, filter by country for districts/provinces
            if filtered.size().getInfo() == 0 and country_name:
                filtered = collection.filter(
                    ee.Filter.eq('countryName', country_name)
                ).filter(
                    ee.Filter.stringContains('shapeName', core)
                )

            # Get geometry
            if filtered.size().getInfo() > 0:
                geometry = filtered.first().geometry()
                return geometry.getInfo()

            print(f"Warning: Could not find boundary for '{region_name}' at level ADM{admin_level}")
            return None

        except Exception as e:
            print(f"Error fetching boundary for '{region_name}': {e}")
            return None
    
    @staticmethod
    def get_boundary_info(region_name: str, admin_level: Optional[int] = None) -> Dict:
        """
        Get comprehensive boundary information.
        
        Returns dict with:
          - admin_level: 0, 1, or 2
          - admin_type: "Country", "Province", or "District"
          - dataset: GEE dataset path
          - boundary_color: Recommended color for visualization
        """
        if admin_level is None:
            admin_level, admin_type = BoundaryAgent.detect_admin_level(region_name)
        else:
            type_map = {0: "Country", 1: "Province", 2: "District"}
            admin_type = type_map.get(admin_level, "Unknown")
        
        colors = {
            0: "#0a0e27",      # Dark navy for country
            1: "#1f2937",      # Dark gray for province
            2: "#0d1b2a"       # Black for district
        }
        
        line_widths = {
            0: 2.5,  # Thicker for country
            1: 2.0,  # Medium for province
            2: 1.5   # Thinner for district
        }
        
        return {
            'admin_level': admin_level,
            'admin_type': admin_type,
            'dataset': BoundaryAgent.get_boundary_dataset(admin_level),
            'boundary_color': colors.get(admin_level, "#000000"),
            'line_width': line_widths.get(admin_level, 1.5),
            'region_name': region_name
        }


def draw_intelligent_boundary(map_ax, region_name: str, 
                             country_name: Optional[str] = None,
                             admin_level: Optional[int] = None,
                             custom_geojson: Optional[Dict] = None) -> bool:
    """
    Draw boundary intelligently on map based on administrative level.
    
    If custom_geojson is provided, it takes precedence.
    Otherwise, fetches from geoBoundaries automatically.
    
    Args:
        map_ax: Cartopy GeoAxes
        region_name: Name of the region
        country_name: Country name (optional, helps with filtering)
        admin_level: Explicit admin level (optional, auto-detects if None)
        custom_geojson: Custom GeoJSON to use instead of fetching
    
    Returns:
        bool: True if boundary was drawn successfully
    """
    import cartopy.crs as ccrs
    from shapely.geometry import shape
    
    try:
        # Use custom GeoJSON if provided
        if custom_geojson:
            geom_dict = custom_geojson
            info = BoundaryAgent.get_boundary_info(region_name)
            print(f"Using custom GeoJSON for '{region_name}'")
        else:
            # Fetch boundary automatically
            geom_dict = BoundaryAgent.fetch_boundary(region_name, country_name, admin_level)
            if not geom_dict:
                return False
            
            info = BoundaryAgent.get_boundary_info(region_name, admin_level)
        
        # Draw the boundary
        _draw_geom_on_map(map_ax, geom_dict, 
                         color=info['boundary_color'],
                         linewidth=info['line_width'],
                         label=f"{info['admin_type']}: {region_name}")
        
        return True
        
    except Exception as e:
        print(f"Error drawing boundary: {e}")
        return False


def _draw_geom_on_map(map_ax, geom_dict: Dict, color: str = "#000000",
                      linewidth: float = 1.5, label: str = ""):
    """
    Internal function to draw GeoJSON geometry on map.
    """
    import cartopy.crs as ccrs
    
    gtype = geom_dict.get("type", "")
    
    if gtype == "Polygon":
        for ring in geom_dict["coordinates"]:
            xs = [c[0] for c in ring]
            ys = [c[1] for c in ring]
            map_ax.plot(xs, ys, color=color, linewidth=linewidth,
                       linestyle="-", transform=ccrs.PlateCarree(),
                       zorder=5, label=label if label else "_nolegend_")
    
    elif gtype == "MultiPolygon":
        for poly_coords in geom_dict["coordinates"]:
            for ring in poly_coords:
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
                map_ax.plot(xs, ys, color=color, linewidth=linewidth,
                           linestyle="-", transform=ccrs.PlateCarree(),
                           zorder=5, label=label if label else "_nolegend_")
    
    elif gtype == "GeometryCollection":
        for g in geom_dict.get("geometries", []):
            _draw_geom_on_map(map_ax, g, color, linewidth, label)


# Example usage and testing
if __name__ == "__main__":
    # Initialize Earth Engine (requires authentication)
    # ee.Authenticate()
    ee.Initialize()
    
    # Test the agent
    print("=== Boundary Detection Agent Test ===\n")
    
    test_cases = [
        "Sri Lanka",
        "Western Province",
        "Jaffna District",
        "Jaffna",
        "Northern",
    ]
    
    for region in test_cases:
        admin_level, admin_type = BoundaryAgent.detect_admin_level(region)
        info = BoundaryAgent.get_boundary_info(region)
        print(f"Region: '{region}'")
        print(f"  → Admin Level: ADM{admin_level} ({admin_type})")
        print(f"  → Dataset: {info['dataset']}")
        print(f"  → Color: {info['boundary_color']}")
        print(f"  → Line Width: {info['line_width']}\n")

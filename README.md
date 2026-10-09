# Gee-Luma — GEE Map Studio

AI-powered Google Earth Engine map generator built with Streamlit, CrewAI, and spyndex.

## Project Structure

```
gee-luma/
├── app.py               # Main Streamlit entry point
├── styles.py            # Custom CSS and page header HTML
├── utils.py             # Shared helpers (ascii_label, warnings shim)
├── cloud_masking.py     # Per-sensor cloud/shadow masking functions
├── dataset_config.py    # Band maps, scale configs, LULC schemas, GEE introspection
├── palettes.py          # Colour palettes for every index and map type
├── map_engine.py        # GEE image computation (spyndex + special map types)
├── cartography.py       # Cartographic figure renderer (PNG export)
├── thumbnail.py         # GEE thumbnail fetcher with retry logic
├── geojson_helpers.py   # GeoJSON CRS reprojection + ee.Geometry conversion
├── requirements.txt
├── .gitignore
└── README.md
```

## Quick Start

```bash
# 1. Clone and enter the directory
git clone <your-repo-url>
cd gee-luma

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Authenticate with Google Earth Engine
earthengine authenticate

# 5. Set your OpenAI API key
echo "OPENAI_API_KEY=sk-..." > .env

# 6. Run the app
streamlit run app.py
```

## Key Features

- **AI-guided mission parsing** via CrewAI + GPT-4o-mini — describe your map in plain English
- **200+ spectral indices** via spyndex (NDVI, kNDVI, EVI, NBR, MNDWI, …)
- **Multi-sensor support**: Sentinel-2, Landsat 8/9, MODIS, VIIRS, Sentinel-1 SAR, SRTM, and more
- **Pixel-level cloud masking** for optical sensors
- **Custom region upload**: drag-in a GeoJSON shapefile (any CRS)
- **Custom map title**: override the auto-generated figure title
- **Cartographic export**: centered title, north arrow, dynamic scale bar, Jaffna district boundary, LULC legend

## Map Title Override

After typing your Earth observation mission, a **"Custom map title"** field lets you set
a specific title on the exported PNG (e.g. *"Jaffna District Cropland 2021"*).
Leave it blank to auto-generate the title from index name + region + date range.

## Environment Variables

| Variable         | Description                           |
|------------------|---------------------------------------|
| `OPENAI_API_KEY` | Required for the CrewAI agent         |
| `EE_PROJECT`     | Optional: GEE project ID override     |

## License

MIT

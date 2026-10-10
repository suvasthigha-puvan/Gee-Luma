# Gee-Luma — GEE Map Studio

Describe a map in plain English; Gee-Luma finds the dataset in Google Earth Engine,
processes it, and returns a print-ready cartographic map.

Built with Streamlit, CrewAI, Earth Engine and spyndex.

## How it works

1. **Agent** (CrewAI + GPT-4o-mini) reads the request and chooses the dataset, band,
   region, period and compositing method. It searches the live Earth Engine catalog
   and checks the dataset's real bands before answering.
2. **Dataset metadata** is read from the public Earth Engine STAC catalog: scale and
   offset, units, class names and colours, coverage period, provider. This is what
   lets the app map datasets it has no built-in knowledge of.
3. **Region** is resolved from geoBoundaries (any country, province/state or district),
   from an uploaded GeoJSON, or — for areas that are not administrative units — from
   an approximate bounding box.
4. **Processing** runs on Earth Engine: cloud masking, compositing over the period,
   index computation, scaling to real units.
5. **Rendering** fetches the result at print resolution in a projection suited to the
   region and lays out the final map.

## Project structure

```
gee-luma/
├── app.py               # Streamlit entry point and request pipeline
├── catalog_search.py    # Live Earth Engine catalog search (agent tool)
├── stac_metadata.py     # Per-dataset metadata from the EE STAC catalog (agent tool)
├── boundary_agent.py    # Place name -> admin boundary (geoBoundaries, any country)
├── geojson_helpers.py   # Uploaded GeoJSON: reprojection + ee.Geometry conversion
├── dataset_config.py    # Sensor band maps, class schemas, colour-range statistics
├── cloud_masking.py     # Per-sensor cloud/shadow masking (Cloud Score+, QA bands)
├── map_engine.py        # Index computation (spyndex) and composite map types
├── palettes.py          # Colour palettes per index and theme
├── projection.py        # Chooses a map projection for the region
├── thumbnail.py         # Tiled, parallel high-resolution image fetch
├── cartography.py       # Final map layout (PNG and PDF)
├── map_stats.py         # Region statistics and CSV export
├── exports.py           # GeoTIFF export of the data values
├── styles.py            # Custom CSS and page header HTML
├── utils.py             # Shared helpers
├── knowledge_base.md    # Reference notes given to the agent
└── requirements.txt
```

## Quick start

```bash
git clone https://github.com/suvasthigha-puvan/Gee-Luma.git
cd Gee-Luma

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

earthengine authenticate
echo "OPENAI_API_KEY=sk-..." > .env

streamlit run app.py
```

The Earth Engine project ID is set in `app.py` (`ee.Initialize(project=...)`); change it
to your own project.

## What you can ask for

- **Any image dataset in the Earth Engine catalog** — name it, or describe the theme
  and the standard global dataset is used (ESA WorldCover for land cover, SRTM for
  elevation, CHIRPS for rainfall, and so on)
- **200+ spectral indices** via spyndex (NDVI, kNDVI, EVI, NBR, MNDWI, …)
- **Colour composites**: true colour, false colour, SWIR, Sentinel-1 radar
- **Categorical products**: land cover and any other classified band, with the
  dataset's own class names and colours
- **Totals and averages** over a period (e.g. total rainfall for a year)
- **Any region**: a country, province/state or district anywhere; an uploaded GeoJSON
  (any CRS); or a larger area such as a continent

Vector (table) datasets are not supported yet.

## The map

- Projection chosen per region: local UTM zone, or Lambert equal-area for wide regions
- Rendered at about 2,000 px on the long side, exported at 300 dpi
- Cloud masking applied by default for Sentinel-2 (Cloud Score+), Landsat, MODIS and
  VIIRS surface reflectance; add "keep clouds" to a request to turn it off
- Cloud gaps filled from nearby dates: when less than 97% of the region has data in
  the requested period, the gaps are filled with imagery from the weeks before and
  after it (nearest first, up to three widening steps). The map and its credit block
  say so, and the original unfilled map is available in a second tab. Turn it off with
  the sidebar switch or by adding "no gap fill" to the request. Totals (sums) are
  never filled.
- Graticule, true-length scale bar, north arrow, locator map
- Legend in real units, with the colour range fitted to the data in the region
- Credit block: dataset title and provider, Earth Engine ID, period, compositing
  method, cloud masking, projection, native resolution, production date
- Optional custom title

## Statistics and exports

- **Statistics over the region**, computed from the same image that is drawn:
  mean, median, min, max, standard deviation, percentiles and a histogram for
  continuous maps; area and share per class for categorical maps. Shown in the app
  and summarised on the map itself.
- **PNG** (300 dpi) and **PDF** (vector text and lines) of the map layout
- **CSV** of the statistics
- **GeoTIFF** of the data values (real units or class codes) in the map projection.
  Earth Engine caps direct downloads at about 48 MB, so large regions are exported
  at a coarser pixel size than the dataset's native one; the app states the size used.

## Environment variables

| Variable         | Description                   |
|------------------|-------------------------------|
| `OPENAI_API_KEY` | Required for the CrewAI agent |

## License

MIT

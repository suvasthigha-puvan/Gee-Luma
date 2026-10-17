# Gee-Luma — GEE Map Studio

Describe a map in plain English; Gee-Luma finds the dataset in Google Earth Engine,
processes it, and returns a print-ready cartographic map.

Built with React, Starlette, CrewAI, Earth Engine and spyndex. A Streamlit version of the
interface is included as well; both use the same pipeline.

![The Gee-Luma interface](docs/screenshot.png)

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
Gee-Luma/
├── server.py                # Start here: web API + host of the React interface
├── app.py                   # Streamlit interface (alternative to the web one)
├── requirements.txt
├── .env.example             # What the .env file holds (the setup window writes it)
├── frontend/                # React interface (Vite + TypeScript)
├── assets/                  # Logo
├── docs/                    # Screenshots
└── gee_luma/                # The map pipeline (Python package)
    ├── pipeline.py          # The whole pipeline, independent of any interface
    ├── settings.py          # Reads and writes the .env file
    ├── connections.py       # Earth Engine sign-in and project checks, AI key check
    ├── catalog_search.py    # Live Earth Engine catalog search (agent tool)
    ├── dataset_options.py   # Datasets to choose from when several fit the request
    ├── stac_metadata.py     # Per-dataset metadata from the EE STAC catalog (agent tool)
    ├── knowledge_base.md    # Reference notes given to the agent
    ├── boundary_agent.py    # Place name -> admin boundary (geoBoundaries, any country)
    ├── geojson_helpers.py   # Uploaded GeoJSON: reprojection + ee.Geometry conversion
    ├── dataset_config.py    # Sensor band maps, class schemas, colour-range statistics
    ├── cloud_masking.py     # Per-sensor cloud/shadow masking (Cloud Score+, QA bands)
    ├── map_engine.py        # Index computation (spyndex) and composite map types
    ├── palettes.py          # Colour palettes per index and theme
    ├── class_legend.py      # Class legends for classified bands of any dataset
    ├── projection.py        # Chooses a map projection for the region
    ├── thumbnail.py         # Tiled, parallel high-resolution image fetch
    ├── time_series.py       # Splits a period into the maps of a multi-map figure
    ├── units.py             # Legend units for totals and averages (mm/month, mm/year, ...)
    ├── cartography.py       # Final map layout, single and multi-map (PNG and PDF)
    ├── map_stats.py         # Region statistics and CSV export
    ├── exports.py           # GeoTIFF export of the data values
    ├── styles.py            # CSS and header HTML for the Streamlit page
    └── utils.py             # Shared helpers
```

## Getting started

Setting up takes about 10 minutes, once. After that, starting Gee-Luma is one command.

### What you need

| | Where to get it |
|---|---|
| **Python 3.10 or newer** | [python.org/downloads](https://www.python.org/downloads/). On Windows, tick **"Add python.exe to PATH"** in the installer. |
| **A Google account with an Earth Engine project** | [Register a project for Earth Engine](https://code.earthengine.google.com/register). Free for non-commercial use (research, education, non-profits). Note the **project ID**, for example `my-earthengine-project`. |
| **An AI API key** | [OpenAI](https://platform.openai.com/api-keys) (recommended) or [Google AI Studio](https://aistudio.google.com/apikey) for Gemini. A map costs well under one US cent with GPT-4o mini. |

### Step 1: Download Gee-Luma

Either click **Code → Download ZIP** on GitHub and unzip it, or use git:

```bash
git clone https://github.com/suvasthigha-puvan/Gee-Luma.git
```

### Step 2: Install (once)

Open a terminal **in the Gee-Luma folder** (Windows: open the folder, type `cmd` in the
address bar and press Enter), then run:

**Windows**

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The install takes a few minutes.

### Step 3: Start Gee-Luma

```bash
python server.py
```

Gee-Luma opens in your browser at http://localhost:8000. Keep the terminal open while you
use it; press `Ctrl+C` there to stop it.

### Step 4: The setup window (first time only)

The first time, a setup window opens by itself with three steps:

1. **Sign in to Google Earth Engine.** Click **Sign in with Google**, choose the Google
   account that has your Earth Engine project, and allow access. When the page says the
   sign-in worked, close it and go back to Gee-Luma.
2. **Earth Engine project ID.** Type your project's ID (not its name).
3. **AI model and API key.** Pick a model and paste your API key.

Click **Check and save**. Gee-Luma tries each one and tells you in plain words if something
needs fixing. Your details are saved on your computer only, in a file called `.env` in the
Gee-Luma folder, and are used every time you start Gee-Luma.

Now describe a map, for example *"NDVI map for Sri Lanka using Sentinel-2, last 3 months"*.

### Every time after that

Open a terminal in the Gee-Luma folder and run:

| Windows | macOS / Linux |
|---|---|
| `.venv\Scripts\activate` then `python server.py` | `source .venv/bin/activate` then `python server.py` |

### When a project reaches its Earth Engine limit

Earth Engine limits how much each project can use. When a map fails because your project
reached its limit, Gee-Luma asks: **"Would you like to switch to a different Earth Engine
project?"**

- **Yes, switch project** opens a window for another project ID. If that project belongs to a
  different Google account, click **Use another Google account** first. Then click
  **Check and switch** and try the map again.
- **No** keeps your project. Limits reset over time, so you can try again later.

To change the project, model or API key at any other time, click the **gear icon** at the top
right.

### If something goes wrong

| Problem | What to do |
|---|---|
| `python` is not found | Reinstall Python with "Add python.exe to PATH" ticked, then open a new terminal. On macOS/Linux use `python3`. |
| "Your Google account cannot use the project" | Check the project ID, and that you signed in with the account that owns it. |
| "The project is not registered to use Earth Engine" | [Register it](https://code.earthengine.google.com/register), then click **Check and save** again. |
| "The AI service did not accept this key" | Copy the key again in full. An OpenAI key needs credit on the account. |
| Port 8000 is already in use | Change `PORT` in the `.env` file to another number, such as `8010`. |
| The browser did not open | Go to http://localhost:8000 yourself. |

The Streamlit interface still works too, once the setup is done: `streamlit run app.py`.

### Working on the interface

The built interface (`frontend/dist`) is included, so running Gee-Luma does not need Node.js.
To change the interface, install [Node.js 18+](https://nodejs.org) and run the API and the
interface's dev server side by side. The dev server reloads on every change and forwards
`/api` calls to the Python server:

```bash
python server.py --no-browser   # terminal 1
cd frontend && npm install && npm run dev   # terminal 2 -> http://localhost:5173
```

Run `npm run build` in `frontend` to update what `server.py` serves.

## The web interface

- Compose on the left: request, optional title, palette, region upload, gap-fill switch
- Live progress while the map is generated, step by step
- Map viewer with zoom and pan, gap-filled / original switch, and PNG, PDF, CSV and
  GeoTIFF downloads
- Statistics with a histogram or class-area bars, plus source and method details
- Light and dark themes; the open map stays in the address bar (`?map=...`), so a
  refresh returns to it
- Maps are kept in the server's memory for the session only

## What you can ask for

- **Any image dataset in the Earth Engine catalog** — name it exactly ("MOD13Q1"), name
  a family ("using MODIS", "with Landsat 8"), or just describe the theme ("rainfall in
  Sri Lanka")
- **A choice of dataset** — when several datasets fit the request, Gee-Luma lists them
  with resolution, update frequency and coverage and waits for you to pick one before
  it processes anything. For a theme the standard global dataset (ESA WorldCover for
  land cover, SRTM for elevation, CHIRPS for rainfall, and so on) is listed first and
  marked; "Let Gee-Luma choose" uses it. Naming an exact product skips the question
- **200+ spectral indices** via spyndex (NDVI, kNDVI, EVI, NBR, MNDWI, …)
- **Colour composites**: true colour, false colour, SWIR, Sentinel-1 radar
- **Categorical products**: land cover and any other classified band, with the
  dataset's own class names and colours
- **Totals and averages** over a period (e.g. total rainfall for a year)
- **Several maps in one figure** — a map per month, season or year, a multi-year
  climatology, or named periods side by side (see below)
- **Any region**: a country, province/state or district anywhere; an uploaded GeoJSON
  (any CRS); or a larger area such as a continent

Vector (table) datasets are not supported yet.

## Several maps in one figure

Ask for more than one period and the maps are drawn together, on one page:

| Request                                              | Figure                                                        |
|------------------------------------------------------|---------------------------------------------------------------|
| "Monthly ET maps of Sri Lanka for 2025"              | 12 maps, each the total of one month                          |
| "Monthly average land surface temperature, 2024"     | 12 maps, each the mean of one month                           |
| "Seasonal NDVI of Nepal for 2024"                    | 4 maps: Dec–Feb, Mar–May, Jun–Aug, Sep–Nov                    |
| "Annual rainfall maps of Kenya, 2015 to 2024"        | 10 maps, each the total of one year                           |
| "Average monthly rainfall of India, 2001–2020"       | 12 maps: each calendar month's total, averaged over 20 years  |
| "NDVI of Punjab in July 2015 vs July 2025"           | 2 maps, the periods named                                     |

- **What each map holds** follows the request and the variable: a *total* per period for
  rainfall and evapotranspiration, a *mean* when an average is asked for, a median for
  reflectance and indices, the most common class for classified data. A climatology of
  totals is the average of each year's total, not one total over all the years. The
  title, legend and credit block say which it is.
- **The grid** is chosen from the shape of the region so the maps are drawn as large
  as the page allows: twelve maps of a tall region become 6 × 2, of a wide region
  3 × 4, of a compact one 4 × 3.
- **Comparable by construction**: every map has the same extent, projection and colour
  scale (fitted to all of them together), under one shared legend and scale bar.
- **Units follow the aggregation**: monthly totals are in mm/month, seasonal in
  mm/season, annual in mm/year, a total over any other period in mm; averages keep the
  dataset's own rate (mm/day, mm/8 days). Rainfall and evapotranspiration published
  in kg/m² are shown in mm (the same quantity). This applies to single maps too: a
  total for one calendar year reads mm/year.
- Whole calendar units are mapped: a period that covers less than half of a month,
  season or year does not get a map of it. A period still running ends today, and
  periods with no images are left out; both are reported.
- Cloud gaps are not filled in a series (each map shows its own period only), and a
  figure holds at most 36 maps.
- Statistics are given per map, the CSV has a row per map, and the GeoTIFF has one
  band per map.

A request for a single period still produces the single-map layout described next.

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
- Class legends for every classified band, whatever the dataset publishes: the
  catalog's own class names and colours where it lists them; distinct colours assigned
  where it lists names only; names read from the band description where classes are
  only written out there; and classes labelled by value where nothing is published
  (the band is recognised as classified from its data). Only classes present in the
  region are listed, long legends show the largest classes and sum up the rest, and
  "only" in a request ("crop class only") maps just those classes.
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

## Settings (the .env file)

The setup window writes these to the `.env` file in the Gee-Luma folder, so you never have to
edit it by hand. The app reads its settings from this file only (if there is none there, the
nearest `.env` in a folder above is used).

| Setting       | What it is                                                         |
|---------------|--------------------------------------------------------------------|
| `EE_PROJECT`  | Earth Engine project ID                                            |
| `LLM_MODEL`   | AI model, as `provider/model`, for example `openai/gpt-4o-mini`    |
| `LLM_API_KEY` | Key for that AI service                                            |
| `PORT`        | Port for `server.py`; `8000` is written on the first start         |

Your Google sign-in for Earth Engine is kept where Earth Engine's own tools keep it
(`~/.config/earthengine/credentials`), not in the `.env` file. Never share or commit
the `.env` file: it holds your API key (`.gitignore` already leaves it out).

## License

Gee-Luma is released under the [MIT License](LICENSE).

Copyright (c) 2026 Suvasthigha Puvan.

The maps you make use data from Google Earth Engine. Each dataset keeps its own licence and
terms of use, set by its provider, and Earth Engine itself has its own
[terms of service](https://earthengine.google.com/terms/). Check them before you publish or
share maps made with Gee-Luma.

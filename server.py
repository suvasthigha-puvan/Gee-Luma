"""
server.py
---------
Web API for Gee-Luma and host of the React interface.

    python server.py            -> http://localhost:8000

A map takes one to several minutes, so requests are jobs: the browser posts
a request, gets a job id back at once, and polls the job for progress and
the result. Jobs run one at a time on a single worker thread (Earth Engine
rendering and matplotlib are not safe to run concurrently in one process).

Endpoints
    GET  /api/meta                       what the server can do, example requests
    POST /api/region                     validate an uploaded GeoJSON region
    POST /api/maps                       start a map job
    GET  /api/maps                       recent jobs
    GET  /api/maps/{id}                  job progress and result
    POST /api/maps/{id}/original         render the original (not gap-filled) map
    GET  /api/maps/{id}/file/{name}      map.png, map.pdf, stats.csv, data.tif,
                                         original.png, original.pdf

Results are kept in memory only; they are gone when the server stops.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import ee
import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from gee_luma.pipeline import (
    run_pipeline, render_original_map, create_llm,
    PALETTE_PRESETS, EE_PROJECT, LLM_MODEL, SPYNDEX_AVAILABLE,
)
from gee_luma.exports import fetch_geotiff
from gee_luma.geojson_helpers import _ensure_wgs84, get_geojson_bounds, get_geojson_label

FRONTEND_DIR = Path(__file__).with_name("frontend") / "dist"
MAX_JOBS_KEPT = 12

EXAMPLE_REQUESTS = [
    {"label": "Vegetation", "text": "NDVI map for Sri Lanka using Sentinel-2, last 3 months"},
    {"label": "Land cover", "text": "Land cover map of Kandy district"},
    {"label": "Rainfall", "text": "Total rainfall in Sri Lanka for 2023"},
    {"label": "True colour", "text": "True-color image of Galle district using Sentinel-2, January to March 2024"},
    {"label": "Temperature", "text": "Land surface temperature of Tamil Nadu in April 2024"},
    {"label": "Elevation", "text": "Elevation map of Nepal"},
    {"label": "Air quality", "text": "NO2 air pollution over Europe, September 2025"},
    {"label": "Water", "text": "NDWI water index for Jaffna district using Landsat 8, January 2023"},
]


# ====================== progress recorder ======================

class PipelineStop(BaseException):
    """Raised by RecordingUI.stop(). A BaseException so that the pipeline's own
    `except Exception` handlers do not swallow it."""


class _Step:
    def __init__(self, ui: "RecordingUI", index: int):
        self._ui, self._index = ui, index

    def update(self, label=None, state=None, expanded=None):
        with self._ui.lock:
            step = self._ui.steps[self._index]
            if label is not None:
                step["label"] = _plain(label)
            if state in ("complete", "error", "running"):
                step["state"] = state


def _plain(text) -> str:
    """Progress labels as plain text (the pipeline writes them with Markdown marks)."""
    return re.sub(r"[*`]", "", str(text)).strip()


class RecordingUI:
    """
    Stands in for Streamlit when the pipeline runs behind the API: every
    progress step and message the pipeline reports is recorded so the browser
    can show it.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.steps: list[dict] = []
        self.notes: list[dict] = []
        self._muted = 0     # inside an expander: detail the API returns in structured form instead

    def status(self, label, expanded=False, state="running"):
        with self.lock:
            self.steps.append({"label": _plain(label), "state": "running"})
            return _Step(self, len(self.steps) - 1)

    def _note(self, level, text):
        if self._muted:
            return
        with self.lock:
            self.notes.append({"level": level, "text": str(text).strip()})

    def info(self, text, **_):    self._note("info", text)
    def warning(self, text, **_): self._note("warning", text)
    def caption(self, text, **_): self._note("note", text)

    def error(self, text, **_):
        # Errors are always kept, even inside an expander.
        with self.lock:
            self.notes.append({"level": "error", "text": str(text).strip()})

    def markdown(self, text, **_): self._note("note", text)
    def code(self, text, **_):     self._note("detail", text)
    def json(self, obj, **_):      pass

    @contextmanager
    def expander(self, label, expanded=False):
        self._muted += 1
        try:
            yield self
        finally:
            self._muted -= 1

    @contextmanager
    def spinner(self, text=""):
        step = self.status(text)
        try:
            yield
            step.update(state="complete")
        except BaseException:
            step.update(state="error")
            raise

    def stop(self):
        raise PipelineStop()

    def close_open_steps(self, state):
        with self.lock:
            for step in self.steps:
                if step["state"] == "running":
                    step["state"] = state


# ====================== jobs ======================

class Job:
    def __init__(self, request: dict):
        self.id = uuid.uuid4().hex[:12]
        self.request = request
        self.created = time.time()
        self.finished: float | None = None
        self.status = "queued"            # queued | running | done | error
        self.ui = RecordingUI()
        self.result: dict | None = None
        self.error: str | None = None


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gee-luma")
STATE = {"llm": None, "problems": []}


def _startup():
    load_dotenv()
    problems = []
    try:
        ee.Initialize(project=EE_PROJECT)
    except Exception as e:
        problems.append(f"Google Earth Engine could not be initialised ({e}). "
                        "Run `earthengine authenticate` and check the project ID.")
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        STATE["llm"] = create_llm(api_key)
    else:
        problems.append("OPENAI_API_KEY is not set. Add it to a .env file next to server.py.")
    STATE["problems"] = problems
    for p in problems:
        print("STARTUP PROBLEM:", p)


def _run_job(job: Job):
    job.status = "running"
    req = job.request
    try:
        job.result = run_pipeline(
            req["prompt"],
            llm=STATE["llm"],
            ui=job.ui,
            uploaded_region_geojson=req.get("region_geojson"),
            uploaded_region_label=req.get("region_label"),
            map_title_override=req.get("title") or "",
            selected_palette=req.get("palette") or "Auto (index-based)",
            fill_gaps_option=bool(req.get("fill_gaps", True)),
        )
    except PipelineStop:
        job.result = None
    except Exception as e:          # anything the pipeline itself did not handle
        job.ui.error(f"Unexpected error: {e}")
        job.result = None

    if job.result:
        job.status = "done"
        job.ui.close_open_steps("complete")
    else:
        errors = [n["text"] for n in job.ui.notes if n["level"] == "error"]
        job.error = errors[-1] if errors else "The map could not be generated."
        job.status = "error"
        job.ui.close_open_steps("error")
    job.finished = time.time()

    # Results hold large images; keep only the most recent jobs.
    with JOBS_LOCK:
        finished = sorted((j for j in JOBS.values() if j.finished), key=lambda j: j.created)
        for old in finished[:-MAX_JOBS_KEPT]:
            JOBS.pop(old.id, None)


def _json_safe(value):
    """Plain JSON types only (statistics may carry numpy numbers and tuples)."""
    return json.loads(json.dumps(value, default=lambda o: float(o) if hasattr(o, "__float__") else str(o)))


def _result_payload(job: Job) -> dict | None:
    res = job.result
    if not res:
        return None
    stats = res.get("stats")
    if stats and stats.get("kind") == "continuous":
        stats = {**stats, "rows": [{"name": name, "value": value} for name, value in stats["rows"]]}
    geotiff = res.get("geotiff")
    return _json_safe({
        "title": res.get("title"),
        "region": res.get("region"),
        "period": res.get("period"),
        "map_label": res.get("map_label"),
        "value_label": res.get("value_label"),
        "is_rgb": res.get("is_rgb"),
        "file_base": res["file_name"].rsplit(".", 1)[0],
        "dataset": {
            "id": res.get("collection"),
            "title": res.get("dataset_title"),
            "provider": res.get("provider"),
            "coverage": res.get("dataset_coverage"),
            "resolution_m": res.get("resolution_m"),
            "bands": res.get("bands"),
        },
        "processing": {
            "summary": res.get("processing"),
            "images": res.get("n_images"),
            "cloud_mask": res.get("cloud_mask_desc"),
            "projection": res.get("projection"),
        },
        "gap_fill": res.get("gap_fill"),
        "original_rendered": bool(res.get("original")),
        "stats": stats,
        "has_csv": bool(res.get("stats_csv")),
        "geotiff": ({k: geotiff[k] for k in ("scale_m", "native_scale_m", "resampled")} if geotiff else None),
        "index": res.get("index_info"),
        "agent": res.get("agent"),
    })


def _job_payload(job: Job, full: bool = True) -> dict:
    with job.ui.lock:
        steps = [dict(s) for s in job.ui.steps]
        notes = [dict(n) for n in job.ui.notes]
    payload = {
        "id": job.id,
        "status": job.status,
        "prompt": job.request["prompt"],
        "created": job.created,
        "elapsed": round((job.finished or time.time()) - job.created, 1),
        "error": job.error,
        "title": (job.result or {}).get("title"),
        "region": (job.result or {}).get("region"),
    }
    if full:
        payload.update({"steps": steps, "notes": notes, "result": _result_payload(job)})
    return payload


# ====================== endpoints ======================

def api_meta(request: Request):
    index_count = 0
    if SPYNDEX_AVAILABLE:
        import spyndex
        index_count = len(spyndex.indices)
    return JSONResponse({
        "ready": not STATE["problems"],
        "problems": STATE["problems"],
        "palettes": [{"name": name, "colors": colors} for name, colors in PALETTE_PRESETS.items()],
        "examples": EXAMPLE_REQUESTS,
        "index_count": index_count,
        "model": LLM_MODEL.split("/")[-1],
    })


async def api_region(request: Request):
    try:
        raw = await request.json()
        wgs84 = _ensure_wgs84(raw)
        bounds = get_geojson_bounds(wgs84)
        if not bounds:
            raise ValueError("no coordinates found")
        count = len(wgs84.get("features", [])) if wgs84.get("type") == "FeatureCollection" else 1
        return JSONResponse({"ok": True, "label": get_geojson_label(wgs84), "bounds": bounds, "features": count})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"This file could not be read as a GeoJSON region ({e})."},
                            status_code=400)


async def api_create_map(request: Request):
    if STATE["problems"]:
        return JSONResponse({"error": " ".join(STATE["problems"])}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "The request body must be JSON."}, status_code=400)
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "Describe the map you want first."}, status_code=400)

    req = {
        "prompt": prompt,
        "title": str(body.get("title") or "").strip(),
        "palette": body.get("palette") if body.get("palette") in PALETTE_PRESETS else "Auto (index-based)",
        "fill_gaps": bool(body.get("fill_gaps", True)),
    }
    if body.get("region_geojson"):
        try:
            req["region_geojson"] = _ensure_wgs84(body["region_geojson"])
            req["region_label"] = get_geojson_label(req["region_geojson"])
        except Exception as e:
            return JSONResponse({"error": f"The uploaded region could not be used ({e})."}, status_code=400)

    job = Job(req)
    with JOBS_LOCK:
        JOBS[job.id] = job
    WORKER.submit(_run_job, job)
    return JSONResponse({"id": job.id}, status_code=202)


def api_list_maps(request: Request):
    with JOBS_LOCK:
        jobs = sorted(JOBS.values(), key=lambda j: j.created, reverse=True)
    return JSONResponse({"jobs": [_job_payload(j, full=False) for j in jobs]})


def _job_or_404(request: Request):
    job = JOBS.get(request.path_params["job_id"])
    if job is None:
        return None, JSONResponse({"error": "This map is no longer available. Generate it again."}, status_code=404)
    return job, None


def api_get_map(request: Request):
    job, missing = _job_or_404(request)
    return missing or JSONResponse(_job_payload(job))


def api_render_original(request: Request):
    job, missing = _job_or_404(request)
    if missing:
        return missing
    res = job.result or {}
    if not res.get("original_job"):
        return JSONResponse({"error": "This map has no separate original version."}, status_code=400)
    if not res.get("original"):
        try:
            # Through the worker, so it never renders at the same time as a job.
            res["original"] = WORKER.submit(render_original_map, res["original_job"]).result()
        except Exception as e:
            return JSONResponse({"error": f"The original map could not be rendered ({e})."}, status_code=500)
    return JSONResponse({"ok": True})


def api_file(request: Request):
    job, missing = _job_or_404(request)
    if missing:
        return missing
    res = job.result
    if not res:
        return JSONResponse({"error": "This map has no result."}, status_code=404)
    name = request.path_params["name"]
    base = res["file_name"].rsplit(".", 1)[0]
    download = request.query_params.get("download") == "1"

    def send(data, media_type, filename):
        headers = {"Cache-Control": "private, max-age=3600"}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return Response(data, media_type=media_type, headers=headers)

    if name == "map.png":
        return send(res["png_bytes"], "image/png", f"{base}.png")
    if name == "map.pdf":
        return send(res["pdf_bytes"], "application/pdf", f"{base}.pdf")
    if name == "stats.csv" and res.get("stats_csv"):
        return send(res["stats_csv"], "text/csv; charset=utf-8", f"{base}_statistics.csv")
    if name in ("original.png", "original.pdf") and res.get("original"):
        kind = name.rsplit(".", 1)[1]
        return send(res["original"][kind], "image/png" if kind == "png" else "application/pdf",
                    f"{base}_original.{kind}")
    if name == "data.tif" and res.get("geotiff"):
        geotiff = res["geotiff"]
        if "bytes" not in geotiff:
            try:
                geotiff["bytes"] = fetch_geotiff(geotiff["url"])
            except Exception as e:
                return JSONResponse({"error": f"GeoTIFF export failed ({e})."}, status_code=502)
        return send(geotiff["bytes"], "image/tiff", f"{base}.tif")
    return JSONResponse({"error": "File not available."}, status_code=404)


routes = [
    Route("/api/meta", api_meta),
    Route("/api/region", api_region, methods=["POST"]),
    Route("/api/maps", api_create_map, methods=["POST"]),
    Route("/api/maps", api_list_maps, methods=["GET"]),
    Route("/api/maps/{job_id}", api_get_map),
    Route("/api/maps/{job_id}/original", api_render_original, methods=["POST"]),
    Route("/api/maps/{job_id}/file/{name}", api_file),
]
if FRONTEND_DIR.exists():
    routes.append(Mount("/", app=StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend"))

@asynccontextmanager
async def lifespan(app):
    _startup()
    yield
    WORKER.shutdown(wait=False, cancel_futures=True)


app = Starlette(routes=routes, lifespan=lifespan)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    if not FRONTEND_DIR.exists():
        print("Note: frontend/dist not found - build the interface with `npm run build` in frontend/.")
    print(f"Gee-Luma: http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

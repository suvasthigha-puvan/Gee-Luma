// Shapes of the JSON the Python server (server.py) returns.

export interface Palette {
  name: string;
  colors: string[] | null;
}

export interface ExampleRequest {
  label: string;
  text: string;
}

/** A colour ramp a finished map can be restyled with. */
export interface ColorRamp {
  id: string;
  name: string;
  /** "Gee-Luma" (the app's own palettes) or "QGIS" (QGIS's default ramps). */
  group: string;
  colors: string[];
}

export interface Meta {
  ready: boolean;
  problems: string[];
  palettes: Palette[];
  ramps: ColorRamp[];
  examples: ExampleRequest[];
  index_count: number;
  model: string;
}

export type StepState = "running" | "complete" | "error";

export interface Step {
  label: string;
  state: StepState;
}

export interface Note {
  level: "info" | "warning" | "error" | "note" | "detail";
  text: string;
}

export interface HistogramBin {
  from: number;
  to: number;
  pixels: number;
}

export interface ContinuousStats {
  kind: "continuous";
  rows: { name: string; value: number }[];
  histogram: HistogramBin[];
  area_km2: number | null;
  coverage_percent: number | null;
}

export interface ClassRow {
  value: number;
  class: string;
  /** The class's colour on the map, when the class has one. */
  color?: string;
  area_km2: number;
  percent: number;
}

export interface CategoricalStats {
  kind: "categorical";
  rows: ClassRow[];
  area_km2: number | null;
  mapped_km2: number | null;
}

/** One map of a multi-map figure. */
export interface SeriesRow {
  label: string;
  mean: number | null;
  min: number | null;
  max: number | null;
  std: number | null;
  coverage_percent: number | null;
}

export interface SeriesStats {
  kind: "series";
  rows: SeriesRow[];
  area_km2: number | null;
}

export interface SeriesClassRow {
  value: number;
  class: string;
  color?: string;
  /** One entry per map, in the order of `panels`. */
  area_km2: number[];
  percent: number[];
}

export interface SeriesClassStats {
  kind: "series_categorical";
  panels: string[];
  rows: SeriesClassRow[];
  area_km2: number | null;
}

export type Stats = ContinuousStats | CategoricalStats | SeriesStats | SeriesClassStats;

export interface GapFill {
  original_percent: number;
  filled_percent: number;
  days: number;
  window_start: string;
  window_end: string;
}

export interface MapStyle {
  /** "original" (the colours the map was made with) or the id of a ColorRamp. */
  ramp: string;
  palette: string[];
  min: number;
  max: number;
  /** Goes up with every change, so the browser fetches the redrawn map. */
  version: number;
  original: { palette: string[]; min: number; max: number };
}

export interface MapResult {
  title: string;
  region: string;
  period: string;
  map_label: string;
  value_label: string;
  is_rgb: boolean;
  file_base: string;
  dataset: {
    id: string;
    title: string;
    provider: string;
    coverage: string;
    resolution_m: number | null;
    bands: string[];
  };
  processing: {
    summary: string;
    images: number;
    cloud_mask: string | null;
    projection: string;
  };
  gap_fill: GapFill | null;
  /** Set when the figure holds several maps (monthly, annual, ...). */
  series: { kind: string; grid: string | null; maps: { label: string; images: number }[] } | null;
  original_rendered: boolean;
  /** Colour ramp and legend range; null for maps whose colours cannot be changed (colour images, classes). */
  style: MapStyle | null;
  stats: Stats | null;
  has_csv: boolean;
  geotiff: { scale_m: number; native_scale_m: number; resampled: boolean } | null;
  index: {
    name: string;
    long_name: string;
    formula: string;
    domain: string;
    bands: string[];
    reference: string;
  } | null;
  agent: Record<string, unknown> | null;
}

/** One of the datasets a request could mean ("NDVI using MODIS" fits several). */
export interface DatasetOption {
  id: string;
  title: string;
  provider: string;
  /** What sets this dataset apart from the other options. */
  note: string;
  resolution: string;
  cadence: string;
  coverage: string;
  /** The dataset Gee-Luma uses for this theme when nobody chooses. */
  standard?: boolean;
}

export interface DatasetChoice {
  /** The dataset name as the request wrote it, e.g. "MODIS"; empty when it names none. */
  named: string;
  options: DatasetOption[];
}

/** "choice": the job waits for the person to pick a dataset before it processes anything. */
export type JobStatus = "queued" | "running" | "choice" | "done" | "error";

export interface JobSummary {
  id: string;
  status: JobStatus;
  prompt: string;
  created: number;
  elapsed: number;
  /** Seconds the job spent waiting for a dataset choice (not counted in `elapsed`). */
  waited?: number;
  error: string | null;
  title: string | null;
  region: string | null;
}

export interface Job extends JobSummary {
  steps: Step[];
  notes: Note[];
  result: MapResult | null;
  choice?: DatasetChoice | null;
  /** A usage limit stopped the job: Earth Engine's (for this project) or the AI service's. */
  limit?: { kind: "earthengine" | "llm"; project: string } | null;
}

/** The settings in the .env file, and whether they work. */
export interface Setup {
  configured: boolean;
  signed_in: boolean;
  project: string;
  project_ok: boolean;
  project_problem: string | null;
  model: string;
  has_key: boolean;
  key_hint: string | null;
  env_file: string;
  register_url: string;
}

export interface RegionUpload {
  label: string;
  features: number;
  bounds: { lon_min: number; lon_max: number; lat_min: number; lat_max: number };
  geojson: unknown;
  fileName: string;
}

export interface MapRequest {
  prompt: string;
  title: string;
  palette: string;
  fill_gaps: boolean;
  region_geojson?: unknown;
}

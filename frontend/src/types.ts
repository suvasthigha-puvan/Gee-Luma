// Shapes of the JSON the Python server (server.py) returns.

export interface Palette {
  name: string;
  colors: string[] | null;
}

export interface ExampleRequest {
  label: string;
  text: string;
}

export interface Meta {
  ready: boolean;
  problems: string[];
  palettes: Palette[];
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
  area_km2: number;
  percent: number;
}

export interface CategoricalStats {
  kind: "categorical";
  rows: ClassRow[];
  area_km2: number | null;
  mapped_km2: number | null;
}

export type Stats = ContinuousStats | CategoricalStats;

export interface GapFill {
  original_percent: number;
  filled_percent: number;
  days: number;
  window_start: string;
  window_end: string;
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
  original_rendered: boolean;
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

export type JobStatus = "queued" | "running" | "done" | "error";

export interface JobSummary {
  id: string;
  status: JobStatus;
  prompt: string;
  created: number;
  elapsed: number;
  error: string | null;
  title: string | null;
  region: string | null;
}

export interface Job extends JobSummary {
  steps: Step[];
  notes: Note[];
  result: MapResult | null;
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

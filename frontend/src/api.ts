import type { Job, JobSummary, MapRequest, Meta, Setup } from "./types";

/** Error carrying the message the server wrote for the user. */
export class ApiError extends Error {
  /** HTTP status of the answer; 0 when the server could not be reached. */
  status: number;
  /** Messages per field, when the server checked a form. */
  details?: Record<string, string>;

  constructor(message: string, status = 0, details?: Record<string, string>) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

async function readJson<T>(response: Response): Promise<T> {
  let body: any = null;
  try {
    body = await response.json();
  } catch {
    /* not JSON */
  }
  if (!response.ok) {
    throw new ApiError(
      body?.error ?? `The server answered with an error (${response.status}).`,
      response.status,
      body?.errors,
    );
  }
  return body as T;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("The Gee-Luma server is not reachable. Check that server.py is running.");
  }
  return readJson<T>(response);
}

const postJson = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  meta: () => call<Meta>("/api/meta"),

  setup: () => call<Setup>("/api/setup"),

  saveSetup: (values: { project: string; model: string; api_key: string }) =>
    call<{ ok: true; setup: Setup }>("/api/setup", postJson(values)),

  startSignin: () => call<{ url: string }>("/api/setup/signin", { method: "POST" }),

  signinStatus: () =>
    call<{ state: "idle" | "waiting" | "done" | "error"; error: string | null; signed_in: boolean }>("/api/setup/signin"),

  checkRegion: (geojson: unknown) =>
    call<{ ok: true; label: string; features: number; bounds: any }>("/api/region", postJson(geojson)),

  createMap: (request: MapRequest) => call<{ id: string }>("/api/maps", postJson(request)),

  job: (id: string) => call<Job>(`/api/maps/${id}`),

  recent: () => call<{ jobs: JobSummary[] }>("/api/maps"),

  chooseDataset: (id: string, dataset: string) =>
    call<{ ok: true }>(`/api/maps/${id}/dataset`, postJson({ dataset })),

  renderOriginal: (id: string) => call<{ ok: true }>(`/api/maps/${id}/original`, { method: "POST" }),

  setStyle: (id: string, style: { ramp: string; min: number; max: number }) =>
    call<{ ok: true }>(`/api/maps/${id}/style`, postJson(style)),

  /** `version` changes when the map is redrawn (new colours), so a cached copy is not reused. */
  fileUrl: (id: string, name: string, download = false, version = 0) => {
    const query = [download ? "download=1" : "", version ? `v=${version}` : ""].filter(Boolean).join("&");
    return `/api/maps/${id}/file/${name}${query ? `?${query}` : ""}`;
  },

  /** Fetch a file that the server prepares on request (the GeoTIFF) and save it. */
  async saveFile(id: string, name: string, fileName: string) {
    let response: Response;
    try {
      response = await fetch(api.fileUrl(id, name, true));
    } catch {
      throw new ApiError("The Gee-Luma server is not reachable.");
    }
    if (!response.ok) {
      await readJson(response);
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },
};

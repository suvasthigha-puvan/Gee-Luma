import type { Job, JobSummary, MapRequest, Meta } from "./types";

/** Error carrying the message the server wrote for the user. */
export class ApiError extends Error {}

async function readJson<T>(response: Response): Promise<T> {
  let body: any = null;
  try {
    body = await response.json();
  } catch {
    /* not JSON */
  }
  if (!response.ok) {
    throw new ApiError(body?.error ?? `The server answered with an error (${response.status}).`);
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

  checkRegion: (geojson: unknown) =>
    call<{ ok: true; label: string; features: number; bounds: any }>("/api/region", postJson(geojson)),

  createMap: (request: MapRequest) => call<{ id: string }>("/api/maps", postJson(request)),

  job: (id: string) => call<Job>(`/api/maps/${id}`),

  recent: () => call<{ jobs: JobSummary[] }>("/api/maps"),

  renderOriginal: (id: string) => call<{ ok: true }>(`/api/maps/${id}/original`, { method: "POST" }),

  fileUrl: (id: string, name: string, download = false) =>
    `/api/maps/${id}/file/${name}${download ? "?download=1" : ""}`,

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

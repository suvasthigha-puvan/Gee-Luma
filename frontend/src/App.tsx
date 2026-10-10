import { useCallback, useEffect, useRef, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { api, ApiError } from "./api";
import type { Job, JobSummary, MapRequest, Meta, RegionUpload } from "./types";
import { Composer } from "./components/Composer";
import { Welcome } from "./components/Welcome";
import { Progress } from "./components/Progress";
import { ResultView } from "./components/ResultView";
import { Failure } from "./components/Failure";

const POLL_MS = 1500;

type Theme = "light" | "dark";

/** The open map is kept in the address bar (?map=id) so a refresh or a shared link returns to it. */
function mapIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("map");
}

function writeMapIdToUrl(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("map", id);
  else url.searchParams.delete("map");
  window.history.replaceState(null, "", url);
}

function initialTheme(): Theme {
  const fromUrl = new URLSearchParams(window.location.search).get("theme");
  if (fromUrl === "light" || fromUrl === "dark") return fromUrl;
  try {
    const saved = localStorage.getItem("gee-luma-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(initialTheme);

  // What the person is composing
  const [prompt, setPrompt] = useState("");
  const [title, setTitle] = useState("");
  const [palette, setPalette] = useState("Auto (index-based)");
  const [fillGaps, setFillGaps] = useState(true);
  const [region, setRegion] = useState<RegionUpload | null>(null);

  // The job on stage, and the session's earlier ones
  const [job, setJob] = useState<Job | null>(null);
  const [recent, setRecent] = useState<JobSummary[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollTimer = useRef<number | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("gee-luma-theme", theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);

  const refreshRecent = useCallback(() => {
    api.recent().then((r) => setRecent(r.jobs)).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.meta().then(setMeta).catch((e: Error) => setMetaError(e.message));
    refreshRecent();
  }, [refreshRecent]);

  const stopPolling = () => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  const follow = useCallback(
    (id: string) => {
      stopPolling();
      const tick = async () => {
        try {
          const next = await api.job(id);
          setJob(next);
          if (next.status === "queued" || next.status === "running") {
            pollTimer.current = window.setTimeout(tick, POLL_MS);
          } else {
            refreshRecent();
          }
        } catch (e) {
          setSubmitError(e instanceof ApiError ? e.message : "Lost contact with the server.");
          // A map from an earlier server run no longer exists: go back to the start.
          setJob((current) => (current && current.id === id && current.steps.length === 0 ? null : current));
          writeMapIdToUrl(null);
        }
      };
      writeMapIdToUrl(id);
      tick();
    },
    [refreshRecent],
  );

  useEffect(() => {
    const id = mapIdFromUrl();
    if (id) follow(id);
    return stopPolling;
  }, [follow]);

  const generate = async () => {
    if (!prompt.trim() || submitting) return;
    setSubmitError(null);
    setSubmitting(true);
    const request: MapRequest = { prompt: prompt.trim(), title: title.trim(), palette, fill_gaps: fillGaps };
    if (region) request.region_geojson = region.geojson;
    try {
      const { id } = await api.createMap(request);
      setJob({
        id, status: "queued", prompt: request.prompt, created: Date.now() / 1000, elapsed: 0,
        error: null, title: null, region: null, steps: [], notes: [], result: null,
      });
      follow(id);
      refreshRecent();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "The request could not be sent.");
    } finally {
      setSubmitting(false);
    }
  };

  const openJob = (id: string) => {
    setSubmitError(null);
    follow(id);
  };

  const busy = submitting || job?.status === "queued" || job?.status === "running";
  const problems = metaError ? [metaError] : meta?.problems ?? [];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/icon.png" alt="" className="brand-mark" />
          <div>
            <div className="brand-name">
              Gee<span>Luma</span>
            </div>
            <div className="brand-tag">Earth Engine map studio</div>
          </div>
        </div>
        <div className="topbar-right">
          {meta && (
            <div className={`status-pill ${problems.length ? "is-down" : "is-up"}`}>
              <span className="status-dot" />
              {problems.length ? "Setup needed" : "Earth Engine connected"}
              {!problems.length && <span className="status-sep">{meta.model}</span>}
            </div>
          )}
          <button
            className="icon-button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title={theme === "dark" ? "Light theme" : "Dark theme"}
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>

      <div className="workspace">
        <Composer
          meta={meta}
          prompt={prompt}
          onPrompt={setPrompt}
          title={title}
          onTitle={setTitle}
          palette={palette}
          onPalette={setPalette}
          fillGaps={fillGaps}
          onFillGaps={setFillGaps}
          region={region}
          onRegion={setRegion}
          busy={!!busy}
          disabled={problems.length > 0}
          onGenerate={generate}
          error={submitError}
          recent={recent}
          activeId={job?.id ?? null}
          onOpen={openJob}
        />

        <main className="stage">
          {problems.length > 0 && (
            <div className="banner banner-error" role="alert">
              <strong>The server is not ready.</strong>
              {problems.map((p) => (
                <div key={p}>{p}</div>
              ))}
            </div>
          )}

          {!job && <Welcome meta={meta} onPick={setPrompt} />}
          {job && (job.status === "queued" || job.status === "running") && <Progress job={job} />}
          {job && job.status === "error" && <Failure job={job} onRetry={generate} canRetry={!!prompt.trim()} />}
          {job && job.status === "done" && job.result && (
            <ResultView key={job.id} job={job} result={job.result} onJobChange={setJob} />
          )}
        </main>
      </div>
    </div>
  );
}

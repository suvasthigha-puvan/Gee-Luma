import { useCallback, useEffect, useRef, useState } from "react";
import { Moon, Settings, Sun } from "lucide-react";
import { api, ApiError } from "./api";
import type { Job, JobSummary, MapRequest, Meta, RegionUpload, Setup } from "./types";
import { Composer } from "./components/Composer";
import { Welcome } from "./components/Welcome";
import { Progress } from "./components/Progress";
import { ResultView } from "./components/ResultView";
import { Failure } from "./components/Failure";
import { DatasetChoice } from "./components/DatasetChoice";
import { SetupDialog, type SetupMode } from "./components/SetupDialog";

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
  const [setup, setSetup] = useState<Setup | null>(null);
  const [dialog, setDialog] = useState<{ mode: SetupMode; project?: string } | null>(null);

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
  const [missingMap, setMissingMap] = useState(false);    // a map link (?map=id) the server does not know
  const [submitting, setSubmitting] = useState(false);
  const pollTimer = useRef<number | null>(null);
  const missingMapBanner = useRef<HTMLDivElement | null>(null);

  // On a narrow screen the stage is below the composer: bring the notice into view.
  useEffect(() => {
    if (missingMap) missingMapBanner.current?.scrollIntoView({ block: "nearest" });
  }, [missingMap]);

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
    // The first time (nothing saved yet, or it no longer works) the setup window opens by itself.
    api
      .setup()
      .then((s) => {
        setSetup(s);
        if (!s.configured) setDialog({ mode: "setup" });
      })
      .catch(() => undefined);
  }, [refreshRecent]);

  const openSettings = (mode: SetupMode = "settings", project?: string) => {
    api
      .setup()
      .then((s) => {
        setSetup(s);
        setDialog({ mode, project });
      })
      .catch((e: Error) => setSubmitError(e.message));
  };

  const setupSaved = (s: Setup) => {
    setSetup(s);
    setDialog(null);
    setSubmitError(null);
    api.meta().then(setMeta).catch((e: Error) => setMetaError(e.message));
  };

  const stopPolling = () => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  const follow = useCallback(
    (id: string) => {
      stopPolling();
      setMissingMap(false);
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
          if (e instanceof ApiError && e.status === 404) {
            setMissingMap(true);        // shown on the stage, where the map was expected
          } else {
            setSubmitError(e instanceof ApiError ? e.message : "Lost contact with the server.");
          }
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

  const chooseDataset = async (id: string, dataset: string) => {
    setSubmitError(null);
    try {
      await api.chooseDataset(id, dataset);
      follow(id);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "The choice could not be sent.");
    }
  };

  const openJob = (id: string) => {
    setSubmitError(null);
    follow(id);
  };

  const busy = submitting || job?.status === "queued" || job?.status === "running";
  const ready = !metaError && !!meta?.ready;

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
            <button
              className={`status-pill ${ready ? "is-up" : "is-down"}`}
              onClick={() => openSettings(ready ? "settings" : "setup")}
              title={ready ? `Earth Engine project: ${setup?.project ?? ""}` : "Open the setup"}
            >
              <span className="status-dot" />
              {ready ? "Earth Engine connected" : "Setup needed"}
              {ready && <span className="status-sep">{setup?.project}</span>}
              {ready && <span className="status-sep">{meta.model}</span>}
            </button>
          )}
          <button
            className="icon-button"
            onClick={() => openSettings()}
            aria-label="Settings"
            title="Settings: Earth Engine project and AI key"
          >
            <Settings size={17} />
          </button>
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
          disabled={!ready}
          onGenerate={generate}
          error={submitError}
          recent={recent}
          activeId={job?.id ?? null}
          onOpen={openJob}
        />

        <main className="stage">
          {metaError && (
            <div className="banner banner-error" role="alert">
              <strong>The server is not ready.</strong>
              <div>{metaError}</div>
            </div>
          )}
          {meta && !ready && !dialog && (
            <div className="banner banner-info">
              <strong>Finish the setup to start making maps.</strong>{" "}
              <button className="link-button" onClick={() => openSettings("setup")}>
                Open the setup
              </button>
            </div>
          )}

          {missingMap && (
            <div className="banner banner-error" role="alert" ref={missingMapBanner}>
              <strong>This map could not be opened.</strong>
              <div>
                The link may be wrong, or the map is no longer kept: the server holds only its most recent maps,
                and none from before it restarted. Describe the map again to generate it.
              </div>
            </div>
          )}

          {!job && <Welcome meta={meta} onPick={setPrompt} />}
          {job && (job.status === "queued" || job.status === "running") && <Progress job={job} />}
          {job && job.status === "choice" && job.choice && (
            <DatasetChoice key={job.id} job={job} choice={job.choice} onChoose={(d) => chooseDataset(job.id, d)} />
          )}
          {job && job.status === "error" && (
            <Failure
              job={job}
              onRetry={generate}
              canRetry={!!prompt.trim() && ready}
              currentProject={setup?.project ?? ""}
              onSwitchProject={(project) => openSettings("switch-project", project)}
              onOpenSettings={() => openSettings()}
            />
          )}
          {job && job.status === "done" && job.result && (
            <ResultView key={job.id} job={job} result={job.result} onJobChange={setJob} ramps={meta?.ramps ?? []} />
          )}
        </main>
      </div>

      {dialog && setup && (
        <SetupDialog
          key={dialog.mode}
          mode={dialog.mode}
          setup={setup}
          limitedProject={dialog.project}
          onSaved={setupSaved}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

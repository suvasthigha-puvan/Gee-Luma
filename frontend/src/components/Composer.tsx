import { useRef, useState } from "react";
import { ArrowRight, Check, CircleAlert, Loader2, MapPinned, Upload, X } from "lucide-react";
import { api } from "../api";
import type { JobSummary, Meta, RegionUpload } from "../types";
import { timeAgo } from "../format";

interface Props {
  meta: Meta | null;
  prompt: string;
  onPrompt: (v: string) => void;
  title: string;
  onTitle: (v: string) => void;
  palette: string;
  onPalette: (v: string) => void;
  fillGaps: boolean;
  onFillGaps: (v: boolean) => void;
  region: RegionUpload | null;
  onRegion: (v: RegionUpload | null) => void;
  busy: boolean;
  disabled: boolean;
  onGenerate: () => void;
  error: string | null;
  recent: JobSummary[];
  activeId: string | null;
  onOpen: (id: string) => void;
}

export function Composer(p: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [regionError, setRegionError] = useState<string | null>(null);
  const [checkingRegion, setCheckingRegion] = useState(false);
  const [dragging, setDragging] = useState(false);

  const readRegion = async (file: File | undefined) => {
    if (!file) return;
    setRegionError(null);
    setCheckingRegion(true);
    try {
      const geojson = JSON.parse(await file.text());
      const info = await api.checkRegion(geojson);
      p.onRegion({ label: info.label, features: info.features, bounds: info.bounds, geojson, fileName: file.name });
    } catch (e) {
      p.onRegion(null);
      setRegionError(
        e instanceof SyntaxError ? "That file is not valid JSON." : e instanceof Error ? e.message : "The file could not be read.",
      );
    } finally {
      setCheckingRegion(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const canGenerate = p.prompt.trim().length > 0 && !p.busy && !p.disabled;

  return (
    <aside className="composer">
      <div className="composer-scroll">
        <section className="field">
          <label className="field-label" htmlFor="prompt">
            Describe your map
          </label>
          <textarea
            id="prompt"
            className="prompt"
            value={p.prompt}
            onChange={(e) => p.onPrompt(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && canGenerate) p.onGenerate();
            }}
            placeholder="e.g. NDVI for Jaffna district using Landsat 8, January 2023"
            rows={5}
            spellCheck
          />
          <div className="field-hint">Say what to map, where, when — and a dataset if you have one in mind.</div>
        </section>

        <section className="field">
          <label className="field-label" htmlFor="map-title">
            Map title <span className="optional">optional</span>
          </label>
          <input
            id="map-title"
            className="input"
            value={p.title}
            onChange={(e) => p.onTitle(e.target.value)}
            placeholder="Written automatically if left empty"
          />
        </section>

        <section className="field">
          <div className="field-label">Colour palette</div>
          <div className="palette-grid" role="radiogroup" aria-label="Colour palette">
            {(p.meta?.palettes ?? [{ name: "Auto (index-based)", colors: null }]).map((pal) => {
              const selected = pal.name === p.palette;
              return (
                <button
                  key={pal.name}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  className={`palette ${selected ? "is-selected" : ""}`}
                  onClick={() => p.onPalette(pal.name)}
                >
                  <span
                    className="palette-swatch"
                    style={
                      pal.colors
                        ? { background: `linear-gradient(90deg, ${pal.colors.join(", ")})` }
                        : undefined
                    }
                    data-auto={pal.colors ? undefined : "true"}
                  />
                  <span className="palette-name">{pal.colors ? pal.name : "Automatic"}</span>
                  {selected && <Check size={13} className="palette-check" />}
                </button>
              );
            })}
          </div>
        </section>

        <section className="field">
          <div className="field-label">
            Region <span className="optional">optional</span>
          </div>
          {p.region ? (
            <div className="region-card">
              <MapPinned size={18} />
              <div className="region-text">
                <div className="region-name">{p.region.label}</div>
                <div className="region-meta">
                  {p.region.features} polygon{p.region.features === 1 ? "" : "s"} · {p.region.fileName}
                </div>
              </div>
              <button className="icon-button small" onClick={() => p.onRegion(null)} aria-label="Remove region">
                <X size={15} />
              </button>
            </div>
          ) : (
            <button
              type="button"
              className={`dropzone ${dragging ? "is-dragging" : ""}`}
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                readRegion(e.dataTransfer.files?.[0]);
              }}
            >
              {checkingRegion ? <Loader2 size={17} className="spin" /> : <Upload size={17} />}
              <span>
                <strong>Upload a GeoJSON boundary</strong>
                <small>or name the place in your request</small>
              </span>
            </button>
          )}
          <input
            ref={fileInput}
            type="file"
            accept=".json,.geojson,application/geo+json,application/json"
            hidden
            onChange={(e) => readRegion(e.target.files?.[0])}
          />
          {regionError && <div className="field-error">{regionError}</div>}
        </section>

        <section className="field">
          <label className="switch-row">
            <span>
              <span className="switch-title">Fill cloud gaps</span>
              <span className="switch-hint">Use nearby dates where cloud hides the ground</span>
            </span>
            <input
              type="checkbox"
              className="switch"
              checked={p.fillGaps}
              onChange={(e) => p.onFillGaps(e.target.checked)}
            />
          </label>
        </section>

        {p.recent.length > 0 && (
          <section className="field recent">
            <div className="field-label">This session</div>
            <ul className="recent-list">
              {p.recent.map((j) => (
                <li key={j.id}>
                  <button
                    className={`recent-item ${j.id === p.activeId ? "is-active" : ""}`}
                    onClick={() => p.onOpen(j.id)}
                  >
                    <span className={`recent-dot is-${j.status}`} />
                    <span className="recent-text">
                      <span className="recent-title">{j.title ?? j.prompt}</span>
                      <span className="recent-meta">
                        {j.status === "done" && timeAgo(j.created)}
                        {j.status === "error" && "Failed"}
                        {(j.status === "running" || j.status === "queued") && "In progress"}
                        {j.status === "choice" && "Waiting for your dataset choice"}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <div className="composer-foot">
        {p.error && (
          <div className="field-error with-icon" role="alert">
            <CircleAlert size={15} /> {p.error}
          </div>
        )}
        <button className="primary" onClick={p.onGenerate} disabled={!canGenerate}>
          {p.busy ? (
            <>
              <Loader2 size={17} className="spin" /> Generating…
            </>
          ) : (
            <>
              Generate map <ArrowRight size={17} />
            </>
          )}
        </button>
        <div className="foot-hint">
          <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to generate · about 1–2 minutes
        </div>
      </div>
    </aside>
  );
}

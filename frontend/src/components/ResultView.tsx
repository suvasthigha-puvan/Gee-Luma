import { useState } from "react";
import { CalendarDays, CloudOff, Download, FileImage, FileSpreadsheet, FileText, Grid3x3, LayoutGrid, Layers, Loader2, Satellite } from "lucide-react";
import { api } from "../api";
import type { ColorRamp, Job, MapResult } from "../types";
import { MapViewer } from "./MapViewer";
import { StyleControls } from "./StyleControls";
import { StatsPanel } from "./StatsPanel";
import { Details } from "./Details";

interface Props {
  job: Job;
  result: MapResult;
  onJobChange: (job: Job) => void;
  /** Colour ramps the map can be restyled with. */
  ramps: ColorRamp[];
}

type Version = "filled" | "original";

export function ResultView({ job, result, onJobChange, ramps }: Props) {
  const [version, setVersion] = useState<Version>("filled");
  const [renderingOriginal, setRenderingOriginal] = useState(false);
  const [restyling, setRestyling] = useState(false);
  const [preparingTiff, setPreparingTiff] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fill = result.gap_fill;
  const showingOriginal = version === "original" && result.original_rendered;

  const renderOriginal = async () => {
    setRenderingOriginal(true);
    try {
      await api.renderOriginal(job.id);
      onJobChange(await api.job(job.id));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "The original map could not be rendered.");
      setVersion("filled");
    } finally {
      setRenderingOriginal(false);
    }
  };

  const pickVersion = async (next: Version) => {
    setActionError(null);
    setVersion(next);
    if (next === "original" && !result.original_rendered && !renderingOriginal) {
      await renderOriginal();
    }
  };

  const applyStyle = async (ramp: string, min: number, max: number) => {
    setActionError(null);
    setRestyling(true);
    try {
      await api.setStyle(job.id, { ramp, min, max });
      onJobChange(await api.job(job.id));
      // The original (not gap-filled) map is drawn again in the new colours.
      if (version === "original") await renderOriginal();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "The colours could not be changed.");
    } finally {
      setRestyling(false);
    }
  };

  const downloadTiff = async () => {
    setActionError(null);
    setPreparingTiff(true);
    try {
      await api.saveFile(job.id, "data.tif", `${result.file_base}.tif`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "The GeoTIFF could not be prepared.");
    } finally {
      setPreparingTiff(false);
    }
  };

  const imageName = showingOriginal ? "original.png" : "map.png";
  const pdfName = showingOriginal ? "original.pdf" : "map.pdf";
  const styleVersion = result.style?.version ?? 0;

  return (
    <div className="result">
      <header className="result-head">
        <div className="eyebrow">{result.region}</div>
        <h2>{result.title}</h2>
        <div className="chips">
          {result.period && (
            <span className="chip">
              <CalendarDays size={13} /> {result.period}
            </span>
          )}
          {result.series && (
            <span className="chip">
              <LayoutGrid size={13} /> {result.series.maps.length} maps
            </span>
          )}
          <span className="chip">
            <Satellite size={13} /> {result.dataset.title}
          </span>
          <span className="chip">
            <Layers size={13} /> {result.processing.images} image{result.processing.images === 1 ? "" : "s"}
          </span>
          {result.processing.cloud_mask && (
            <span className="chip">
              <CloudOff size={13} /> Cloud masked
            </span>
          )}
        </div>
      </header>

      {fill && (
        <div className="banner banner-info">
          Cloud left data over only <strong>{Math.round(fill.original_percent)}%</strong> of the region in this
          period. Gaps were filled with imagery from {fill.window_start} to {fill.window_end}; the map now covers{" "}
          <strong>{Math.round(fill.filled_percent)}%</strong>.
        </div>
      )}

      <div className="toolbar">
        {fill ? (
          <div className="segmented" role="tablist" aria-label="Map version">
            <button role="tab" aria-selected={version === "filled"} onClick={() => pickVersion("filled")}>
              Gap-filled
            </button>
            <button role="tab" aria-selected={version === "original"} onClick={() => pickVersion("original")}>
              Original
            </button>
          </div>
        ) : (
          <span />
        )}

        <div className="downloads">
          <a className="tool" href={api.fileUrl(job.id, imageName, true, styleVersion)}>
            <FileImage size={15} /> PNG
          </a>
          <a className="tool" href={api.fileUrl(job.id, pdfName, true, styleVersion)}>
            <FileText size={15} /> PDF
          </a>
          {result.has_csv && (
            <a className="tool" href={api.fileUrl(job.id, "stats.csv", true)}>
              <FileSpreadsheet size={15} /> CSV
            </a>
          )}
          {result.geotiff && (
            <button className="tool" onClick={downloadTiff} disabled={preparingTiff}>
              {preparingTiff ? <Loader2 size={15} className="spin" /> : <Grid3x3 size={15} />}
              {preparingTiff ? "Preparing…" : "GeoTIFF"}
            </button>
          )}
        </div>
      </div>

      {result.style && ramps.length > 0 && (
        <StyleControls style={result.style} ramps={ramps} busy={restyling || renderingOriginal} onApply={applyStyle} />
      )}

      {actionError && (
        <div className="banner banner-error" role="alert">
          {actionError}
        </div>
      )}

      <MapViewer
        src={api.fileUrl(job.id, imageName, false, styleVersion)}
        viewKey={`${job.id}/${imageName}`}
        alt={`${result.title}${showingOriginal ? " (original, no gap filling)" : ""}`}
        busyLabel={
          restyling ? "Applying the new colours…" : renderingOriginal ? "Rendering the original map…" : null
        }
      />

      {result.geotiff && (
        <p className="export-note">
          <Download size={13} /> GeoTIFF holds the data values at {result.geotiff.scale_m.toLocaleString("en-US")} m
          pixels in the map projection
          {result.geotiff.resampled
            ? ` (resampled from ${result.geotiff.native_scale_m.toLocaleString("en-US")} m to fit Earth Engine's download limit)`
            : ""}
          .{result.series ? " It has one band per map." : ""}
          {fill ? " Statistics and GeoTIFF describe the gap-filled map." : ""}
        </p>
      )}

      <div className="panels">
        <StatsPanel stats={result.stats} valueLabel={result.value_label} isRgb={result.is_rgb} />
        <Details result={result} notes={job.notes} />
      </div>
    </div>
  );
}

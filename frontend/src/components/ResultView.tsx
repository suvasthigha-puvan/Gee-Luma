import { useState } from "react";
import { CalendarDays, CloudOff, Download, FileImage, FileSpreadsheet, FileText, Grid3x3, Layers, Loader2, Satellite } from "lucide-react";
import { api } from "../api";
import type { Job, MapResult } from "../types";
import { MapViewer } from "./MapViewer";
import { StatsPanel } from "./StatsPanel";
import { Details } from "./Details";

interface Props {
  job: Job;
  result: MapResult;
  onJobChange: (job: Job) => void;
}

type Version = "filled" | "original";

export function ResultView({ job, result, onJobChange }: Props) {
  const [version, setVersion] = useState<Version>("filled");
  const [renderingOriginal, setRenderingOriginal] = useState(false);
  const [preparingTiff, setPreparingTiff] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fill = result.gap_fill;
  const showingOriginal = version === "original" && result.original_rendered;

  const pickVersion = async (next: Version) => {
    setActionError(null);
    setVersion(next);
    if (next === "original" && !result.original_rendered && !renderingOriginal) {
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
          <a className="tool" href={api.fileUrl(job.id, imageName, true)}>
            <FileImage size={15} /> PNG
          </a>
          <a className="tool" href={api.fileUrl(job.id, pdfName, true)}>
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

      {actionError && (
        <div className="banner banner-error" role="alert">
          {actionError}
        </div>
      )}

      <MapViewer
        src={api.fileUrl(job.id, imageName)}
        alt={`${result.title}${showingOriginal ? " (original, no gap filling)" : ""}`}
        busyLabel={renderingOriginal ? "Rendering the original map…" : null}
      />

      {result.geotiff && (
        <p className="export-note">
          <Download size={13} /> GeoTIFF holds the data values at {result.geotiff.scale_m.toLocaleString("en-US")} m
          pixels in the map projection
          {result.geotiff.resampled
            ? ` (resampled from ${result.geotiff.native_scale_m.toLocaleString("en-US")} m to fit Earth Engine's download limit)`
            : ""}
          .{fill ? " Statistics and GeoTIFF describe the gap-filled map." : ""}
        </p>
      )}

      <div className="panels">
        <StatsPanel stats={result.stats} valueLabel={result.value_label} isRgb={result.is_rgb} />
        <Details result={result} notes={job.notes} />
      </div>
    </div>
  );
}

import { ArrowUpRight, BarChart3, Database, FileDown, Layers } from "lucide-react";
import type { Meta } from "../types";

interface Props {
  meta: Meta | null;
  onPick: (text: string) => void;
}

export function Welcome({ meta, onPick }: Props) {
  return (
    <div className="welcome">
      <div className="welcome-hero">
        <div className="eyebrow">Google Earth Engine · plain-language maps</div>
        <h1>
          Turn a sentence into a <em>print-ready map</em>.
        </h1>
        <p>
          Describe what you want to see. Gee-Luma finds the dataset in Earth Engine, masks cloud, computes the
          result and lays it out as a finished map with statistics and exports.
        </p>
      </div>

      <div className="capabilities">
        <div className="capability">
          <Database size={18} />
          <div>
            <strong>Any image dataset</strong>
            <span>The whole Earth Engine catalog, read live — not a fixed list.</span>
          </div>
        </div>
        <div className="capability">
          <Layers size={18} />
          <div>
            <strong>{meta?.index_count ? `${meta.index_count} spectral indices` : "Spectral indices"}</strong>
            <span>NDVI, NDWI, NBR and the rest, on any optical sensor.</span>
          </div>
        </div>
        <div className="capability">
          <BarChart3 size={18} />
          <div>
            <strong>Statistics included</strong>
            <span>Means, ranges, histograms and class areas for the region.</span>
          </div>
        </div>
        <div className="capability">
          <FileDown size={18} />
          <div>
            <strong>Ready to use</strong>
            <span>PNG and PDF layouts, CSV statistics and GeoTIFF data.</span>
          </div>
        </div>
      </div>

      {meta && meta.examples.length > 0 && (
        <>
          <div className="section-title">Start from an example</div>
          <div className="examples">
            {meta.examples.map((ex) => (
              <button key={ex.text} className="example" onClick={() => onPick(ex.text)}>
                <span className="example-label">{ex.label}</span>
                <span className="example-text">{ex.text}</span>
                <ArrowUpRight size={15} className="example-arrow" />
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

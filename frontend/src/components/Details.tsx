import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { MapResult, Note } from "../types";
import { richText } from "../format";

export function Details({ result, notes }: { result: MapResult; notes: Note[] }) {
  const [showAgent, setShowAgent] = useState(false);
  const d = result.dataset;
  const p = result.processing;
  const remarks = notes.filter((n) => n.level === "warning" || n.level === "note");

  return (
    <section className="card">
      <h3 className="card-title">Source and method</h3>

      <dl className="kv stacked">
        <div>
          <dt>Dataset</dt>
          <dd>
            {d.title}
            {d.provider && <span className="muted"> · {d.provider}</span>}
          </dd>
        </div>
        <div>
          <dt>Earth Engine ID</dt>
          <dd>
            <code>{d.id}</code>
          </dd>
        </div>
        {d.resolution_m !== null && (
          <div>
            <dt>Native resolution</dt>
            <dd>{Number(d.resolution_m).toLocaleString("en-US")} m</dd>
          </div>
        )}
        {d.coverage && (
          <div>
            <dt>Dataset coverage</dt>
            <dd>{d.coverage}</dd>
          </div>
        )}
        <div>
          <dt>Processing</dt>
          <dd>{p.summary}</dd>
        </div>
        <div>
          <dt>Projection</dt>
          <dd>{p.projection}</dd>
        </div>
        {result.index && (
          <div>
            <dt>{result.index.name} formula</dt>
            <dd>
              <code>{result.index.formula}</code>
            </dd>
          </div>
        )}
      </dl>

      {remarks.length > 0 && (
        <div className="remarks">
          {remarks.map((n, i) => (
            <div key={i} className={`inline-note is-${n.level}`}>
              {richText(n.text)}
            </div>
          ))}
        </div>
      )}

      {result.agent && (
        <div className="disclosure">
          <button className="disclosure-toggle" onClick={() => setShowAgent(!showAgent)} aria-expanded={showAgent}>
            <ChevronDown size={15} className={showAgent ? "is-open" : ""} />
            How the request was interpreted
          </button>
          {showAgent && (
            <dl className="kv agent">
              {Object.entries(result.agent)
                .filter(([, v]) => v !== "" && v !== null && !(typeof v === "object" && Object.keys(v as object).length === 0))
                .map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replace(/_/g, " ")}</dt>
                    <dd>{typeof value === "object" ? <code>{JSON.stringify(value)}</code> : String(value)}</dd>
                  </div>
                ))}
            </dl>
          )}
        </div>
      )}
    </section>
  );
}

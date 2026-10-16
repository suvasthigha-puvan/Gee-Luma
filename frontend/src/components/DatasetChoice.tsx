import { useState } from "react";
import { ArrowRight, Database } from "lucide-react";
import type { DatasetChoice as Choice, Job } from "../types";

interface Props {
  job: Job;
  choice: Choice;
  /** Continue the job with this dataset ID, or with "auto" to leave the choice to Gee-Luma. */
  onChoose: (dataset: string) => Promise<void>;
}

/** Shown before any processing when the request fits several datasets of the family it names. */
export function DatasetChoice({ job, choice, onChoose }: Props) {
  const [picked, setPicked] = useState(choice.options[0].id);
  const [sending, setSending] = useState(false);

  const send = async (dataset: string) => {
    setSending(true);
    try {
      await onChoose(dataset);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="choice">
      <div className="choice-card">
        <div className="choice-icon">
          <Database size={20} />
        </div>
        <div className="eyebrow">Choose a dataset</div>
        <h2>{job.prompt}</h2>
        <p className="choice-lead">
          {choice.options.length} {choice.named && <strong>{choice.named} </strong>}datasets fit this request. Pick
          the one to use; nothing has been processed yet.
        </p>

        <div className="choice-list" role="radiogroup" aria-label="Dataset">
          {choice.options.map((option) => {
            const facts = [option.resolution, option.cadence, option.coverage].filter(Boolean);
            return (
              <label key={option.id} className={`choice-option ${picked === option.id ? "is-picked" : ""}`}>
                <input
                  type="radio"
                  name="dataset"
                  value={option.id}
                  checked={picked === option.id}
                  onChange={() => setPicked(option.id)}
                  disabled={sending}
                />
                <span className="choice-body">
                  <span className="choice-title">
                    {option.title}
                    {option.standard && <span className="choice-badge">Standard choice</span>}
                  </span>
                  <code className="choice-id">{option.id}</code>
                  {facts.length > 0 && (
                    <span className="choice-facts">
                      {facts.map((fact) => (
                        <span key={fact}>{fact}</span>
                      ))}
                    </span>
                  )}
                  {option.note && <span className="choice-note">{option.note}</span>}
                </span>
              </label>
            );
          })}
        </div>

        <div className="choice-actions">
          <button className="primary" onClick={() => send(picked)} disabled={sending}>
            Use this dataset <ArrowRight size={16} />
          </button>
          <button className="secondary" onClick={() => send("auto")} disabled={sending}>
            Let Gee-Luma choose
          </button>
        </div>
      </div>
    </div>
  );
}

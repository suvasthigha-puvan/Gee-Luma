import { CircleAlert, RotateCcw } from "lucide-react";
import type { Job } from "../types";
import { richText } from "../format";

interface Props {
  job: Job;
  onRetry: () => void;
  canRetry: boolean;
}

export function Failure({ job, onRetry, canRetry }: Props) {
  const errors = job.notes.filter((n) => n.level === "error");
  const others = job.notes.filter((n) => n.level === "warning" || n.level === "info");
  const completed = job.steps.filter((s) => s.state === "complete");

  return (
    <div className="failure">
      <div className="failure-card" role="alert">
        <div className="failure-icon">
          <CircleAlert size={22} />
        </div>
        <div className="eyebrow">No map was generated</div>
        <h2>{job.prompt}</h2>

        <div className="failure-messages">
          {(errors.length ? errors : [{ text: job.error ?? "The map could not be generated." }]).map((n, i) => (
            <p key={i}>{richText(n.text)}</p>
          ))}
          {others.map((n, i) => (
            <p key={`o${i}`} className="muted">
              {richText(n.text)}
            </p>
          ))}
        </div>

        {completed.length > 0 && (
          <div className="failure-progress">
            Got as far as: <span>{completed[completed.length - 1].label}</span>
          </div>
        )}

        <button className="secondary" onClick={onRetry} disabled={!canRetry}>
          <RotateCcw size={15} /> Try again
        </button>
      </div>
    </div>
  );
}

import { useState } from "react";
import { ArrowLeftRight, CircleAlert, Gauge, KeyRound, RotateCcw } from "lucide-react";
import type { Job } from "../types";
import { richText } from "../format";

interface Props {
  job: Job;
  onRetry: () => void;
  canRetry: boolean;
  /** The Earth Engine project in use now (it may differ from the one the job ran on). */
  currentProject: string;
  onSwitchProject: (limitedProject: string) => void;
  onOpenSettings: () => void;
}

export function Failure({ job, onRetry, canRetry, currentProject, onSwitchProject, onOpenSettings }: Props) {
  const [keepProject, setKeepProject] = useState(false);
  const errors = job.notes.filter((n) => n.level === "error");
  const others = job.notes.filter((n) => n.level === "warning" || n.level === "info");
  const completed = job.steps.filter((s) => s.state === "complete");
  const limit = job.limit;
  const switched = limit?.kind === "earthengine" && !!currentProject && currentProject !== limit.project;

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

        {limit?.kind === "earthengine" && !switched && !keepProject && (
          <div className="limit-question">
            <Gauge size={18} />
            <div>
              <p>
                The Earth Engine project <strong>{limit.project}</strong> has reached its usage limit.{" "}
                <strong>Would you like to switch to a different Earth Engine project?</strong>
              </p>
              <div className="limit-actions">
                <button className="primary limit-yes" onClick={() => onSwitchProject(limit.project)}>
                  <ArrowLeftRight size={15} /> Yes, switch project
                </button>
                <button className="secondary" onClick={() => setKeepProject(true)}>
                  No, keep {limit.project}
                </button>
              </div>
            </div>
          </div>
        )}
        {limit?.kind === "earthengine" && keepProject && !switched && (
          <p className="failure-progress">
            Earth Engine limits reset over time; try again later, or{" "}
            <button className="link-button" onClick={() => onSwitchProject(limit.project)}>
              switch project
            </button>{" "}
            after all.
          </p>
        )}
        {switched && (
          <div className="limit-question is-done">
            <ArrowLeftRight size={18} />
            <p>
              Now using the project <strong>{currentProject}</strong>. Try the map again.
            </p>
          </div>
        )}
        {limit?.kind === "llm" && (
          <div className="limit-question">
            <KeyRound size={18} />
            <div>
              <p>The AI service's usage limit was reached for your API key. Wait a minute, or use another key.</p>
              <div className="limit-actions">
                <button className="secondary" onClick={onOpenSettings}>
                  <KeyRound size={15} /> Change AI key
                </button>
              </div>
            </div>
          </div>
        )}

        <button className={switched ? "primary failure-retry" : "secondary"} onClick={onRetry} disabled={!canRetry}>
          <RotateCcw size={15} /> Try again
        </button>
      </div>
    </div>
  );
}

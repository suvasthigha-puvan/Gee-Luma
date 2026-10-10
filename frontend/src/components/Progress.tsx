import { useEffect, useState } from "react";
import { Check, CircleAlert, Loader2 } from "lucide-react";
import type { Job } from "../types";
import { formatDuration, richText } from "../format";

export function Progress({ job }: { job: Job }) {
  // Tick locally so the timer moves between polls.
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const elapsed = Math.max(job.elapsed, now - job.created);
  const messages = job.notes.filter((n) => n.level === "info" || n.level === "warning");

  return (
    <div className="progress-wrap">
      <div className="progress-card">
        <div className="progress-head">
          <div>
            <div className="eyebrow">Generating</div>
            <h2 className="progress-prompt">{job.prompt}</h2>
          </div>
          <div className="timer" aria-label="Elapsed time">
            {formatDuration(elapsed)}
          </div>
        </div>

        <ol className="steps">
          {job.steps.length === 0 && (
            <li className="step is-running">
              <span className="step-icon">
                <Loader2 size={15} className="spin" />
              </span>
              <span className="step-label">{job.status === "queued" ? "Waiting for the previous map to finish" : "Starting"}</span>
            </li>
          )}
          {job.steps.map((step, i) => (
            <li key={i} className={`step is-${step.state}`}>
              <span className="step-icon">
                {step.state === "running" && <Loader2 size={15} className="spin" />}
                {step.state === "complete" && <Check size={15} />}
                {step.state === "error" && <CircleAlert size={15} />}
              </span>
              <span className="step-label">{step.label}</span>
            </li>
          ))}
        </ol>

        {messages.length > 0 && (
          <div className="progress-notes">
            {messages.map((n, i) => (
              <div key={i} className={`inline-note is-${n.level}`}>
                {richText(n.text)}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="map-skeleton" aria-hidden="true">
        <div className="skeleton-frame" />
        <div className="skeleton-panel">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}

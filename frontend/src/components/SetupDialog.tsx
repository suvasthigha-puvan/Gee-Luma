import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, ExternalLink, KeyRound, LoaderCircle, LogIn, X } from "lucide-react";
import { api, ApiError } from "../api";
import type { Setup } from "../types";

/** "setup": first start, cannot be closed until it works. "switch-project": a project ran out of quota. */
export type SetupMode = "setup" | "settings" | "switch-project";

interface Props {
  mode: SetupMode;
  setup: Setup;
  /** The project whose limit was reached (switch-project mode). */
  limitedProject?: string;
  onSaved: (setup: Setup) => void;
  onClose: () => void;
}

const MODELS = [
  { id: "openai/gpt-4o-mini", label: "OpenAI GPT-4o mini (recommended, low cost)" },
  { id: "openai/gpt-4o", label: "OpenAI GPT-4o" },
  { id: "openai/gpt-4.1-mini", label: "OpenAI GPT-4.1 mini" },
  { id: "gemini/gemini-2.5-flash", label: "Google Gemini 2.5 Flash" },
];
const OTHER = "other";

const KEY_PAGES: Record<string, { name: string; url: string }> = {
  openai: { name: "OpenAI", url: "https://platform.openai.com/api-keys" },
  gemini: { name: "Google AI Studio", url: "https://aistudio.google.com/apikey" },
};

const SIGN_IN_POLL_MS = 1500;

export function SetupDialog({ mode, setup, limitedProject, onSaved, onClose }: Props) {
  const knownModel = MODELS.some((m) => m.id === setup.model);
  const [signedIn, setSignedIn] = useState(setup.signed_in);
  const [signingIn, setSigningIn] = useState(false);
  const [signInUrl, setSignInUrl] = useState<string | null>(null);   // when the browser blocked the new tab
  const [project, setProject] = useState(mode === "switch-project" ? "" : setup.project);
  const [modelChoice, setModelChoice] = useState(setup.model ? (knownModel ? setup.model : OTHER) : MODELS[0].id);
  const [otherModel, setOtherModel] = useState(knownModel ? "" : setup.model);
  const [apiKey, setApiKey] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>(
    mode === "setup" && setup.project_problem ? { project: setup.project_problem } : {},
  );
  const [saving, setSaving] = useState(false);
  const pollTimer = useRef<number | null>(null);
  const firstField = useRef<HTMLElement | null>(null);

  const closable = mode !== "setup" || setup.configured;
  const showAi = mode !== "switch-project";
  const model = modelChoice === OTHER ? otherModel.trim() : modelChoice;
  const keyPage = KEY_PAGES[model.split("/")[0]];

  useEffect(() => {
    firstField.current?.focus();
    return () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!closable) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [closable, saving, onClose]);

  const signIn = async () => {
    setErrors((e) => ({ ...e, signin: "" }));
    // Opened now, while the click still counts, so the browser does not block it.
    const tab = window.open("", "_blank");
    setSigningIn(true);
    try {
      const { url } = await api.startSignin();
      if (tab) tab.location.href = url;
      else setSignInUrl(url);
    } catch (e) {
      tab?.close();
      setSigningIn(false);
      setErrors((x) => ({ ...x, signin: e instanceof ApiError ? e.message : "The sign-in could not be started." }));
      return;
    }
    const poll = async () => {
      try {
        const status = await api.signinStatus();
        if (status.state === "done") {
          setSignedIn(true);
          setSigningIn(false);
          setSignInUrl(null);
          return;
        }
        if (status.state === "error") {
          setSigningIn(false);
          setErrors((x) => ({ ...x, signin: status.error ?? "The sign-in was not finished. Try again." }));
          return;
        }
      } catch {
        /* the server is busy; ask again */
      }
      pollTimer.current = window.setTimeout(poll, SIGN_IN_POLL_MS);
    };
    poll();
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setErrors({});
    try {
      const answer = await api.saveSetup({ project: project.trim(), model, api_key: apiKey.trim() });
      onSaved(answer.setup);
    } catch (err) {
      if (err instanceof ApiError && err.details) setErrors(err.details);
      else setErrors({ form: err instanceof Error ? err.message : "The settings could not be saved." });
    } finally {
      setSaving(false);
    }
  };

  const title =
    mode === "setup" ? "Set up Gee-Luma" : mode === "switch-project" ? "Switch Earth Engine project" : "Settings";

  return (
    <div className="dialog-backdrop">
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="setup-title" onSubmit={save}>
        <header className="dialog-head">
          <div>
            <h2 id="setup-title">{title}</h2>
            {mode === "setup" && (
              <p className="dialog-lead">
                Three quick steps, needed once. Your details are saved on this computer only, in the{" "}
                <code>.env</code> file, and used every time you open Gee-Luma.
              </p>
            )}
            {mode === "switch-project" && (
              <p className="dialog-lead">
                {limitedProject ? (
                  <>
                    The project <strong>{limitedProject}</strong> has reached its Earth Engine usage limit.
                  </>
                ) : (
                  "This project has reached its Earth Engine usage limit."
                )}{" "}
                Enter another project ID. If that project belongs to a different Google account, sign in with
                that account first.
              </p>
            )}
          </div>
          {closable && (
            <button type="button" className="icon-button" onClick={onClose} aria-label="Close" disabled={saving}>
              <X size={17} />
            </button>
          )}
        </header>

        <ol className="setup-steps">
          <li className="setup-step">
            <StepMark n={1} done={signedIn} />
            <div className="setup-body">
              <div className="setup-title">Sign in to Google Earth Engine</div>
              <p className="field-hint">
                Use the Google account that has access to Earth Engine. A Google page opens in a new tab; come
                back here when it says the sign-in worked.
              </p>
              <div className="setup-row">
                {signedIn && !signingIn && (
                  <span className="setup-ok">
                    <Check size={15} /> Signed in
                  </span>
                )}
                <button
                  type="button"
                  className="secondary"
                  onClick={signIn}
                  disabled={saving}
                  ref={(el) => {
                    if (!signedIn) firstField.current = el;
                  }}
                >
                  {signingIn ? <LoaderCircle size={15} className="spin" /> : <LogIn size={15} />}
                  {signingIn ? "Waiting for Google…" : signedIn ? "Use another Google account" : "Sign in with Google"}
                </button>
              </div>
              {signingIn && signInUrl && (
                <p className="field-hint">
                  Your browser blocked the new tab.{" "}
                  <a href={signInUrl} target="_blank" rel="noreferrer">
                    Open the Google sign-in page <ExternalLink size={11} />
                  </a>
                </p>
              )}
              {signingIn && !signInUrl && (
                <p className="field-hint">Finish the sign-in in the new tab. This page updates by itself.</p>
              )}
              {errors.signin && <p className="field-error">{errors.signin}</p>}
            </div>
          </li>

          <li className="setup-step">
            <StepMark n={2} done={!!setup.project && setup.project_ok && project.trim() === setup.project} />
            <div className="setup-body">
              <label className="setup-title" htmlFor="setup-project">
                Earth Engine project ID
              </label>
              <input
                id="setup-project"
                className="input"
                placeholder="for example my-earthengine-project"
                value={project}
                autoComplete="off"
                spellCheck={false}
                disabled={saving}
                onChange={(e) => setProject(e.target.value)}
                ref={(el) => {
                  if (signedIn) firstField.current = el;
                }}
              />
              <p className="field-hint">
                The project's ID, not its name. No project yet?{" "}
                <a href={setup.register_url} target="_blank" rel="noreferrer">
                  Register one for Earth Engine <ExternalLink size={11} />
                </a>{" "}
                (free for non-commercial use).
              </p>
              {errors.project && <p className="field-error">{errors.project}</p>}
            </div>
          </li>

          {showAi && (
            <li className="setup-step">
              <StepMark n={3} done={setup.has_key && !!setup.model && !apiKey && model === setup.model} />
              <div className="setup-body">
                <label className="setup-title" htmlFor="setup-model">
                  AI model and API key
                </label>
                <select
                  id="setup-model"
                  className="input"
                  value={modelChoice}
                  disabled={saving}
                  onChange={(e) => setModelChoice(e.target.value)}
                >
                  {MODELS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                  <option value={OTHER}>Another model…</option>
                </select>
                {modelChoice === OTHER && (
                  <input
                    className="input"
                    aria-label="Model, as provider/model"
                    placeholder="provider/model, for example openai/gpt-4o"
                    value={otherModel}
                    spellCheck={false}
                    disabled={saving}
                    onChange={(e) => setOtherModel(e.target.value)}
                  />
                )}
                <div className="setup-key">
                  <KeyRound size={15} />
                  <input
                    className="input"
                    type="password"
                    aria-label="API key"
                    placeholder={setup.has_key ? `Saved key (${setup.key_hint}) — leave empty to keep it` : "Paste your API key"}
                    value={apiKey}
                    autoComplete="off"
                    disabled={saving}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </div>
                {keyPage && (
                  <p className="field-hint">
                    Get a key at{" "}
                    <a href={keyPage.url} target="_blank" rel="noreferrer">
                      {keyPage.name} <ExternalLink size={11} />
                    </a>
                    . The key stays on this computer.
                  </p>
                )}
                {errors.llm && <p className="field-error">{errors.llm}</p>}
              </div>
            </li>
          )}
        </ol>

        {errors.form && (
          <p className="field-error with-icon" role="alert">
            {errors.form}
          </p>
        )}

        <footer className="dialog-foot">
          <span className="field-hint">Saved to {setup.env_file}</span>
          <button className="primary dialog-save" type="submit" disabled={saving || (signingIn && !signedIn)}>
            {saving ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}
            {saving ? "Checking…" : mode === "switch-project" ? "Check and switch" : "Check and save"}
          </button>
        </footer>
      </form>
    </div>
  );
}

function StepMark({ n, done }: { n: number; done: boolean }) {
  return <span className={`setup-mark${done ? " is-done" : ""}`}>{done ? <Check size={14} /> : n}</span>;
}

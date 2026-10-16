import { useEffect, useState, type FormEvent } from "react";
import { Check, Palette, RotateCcw } from "lucide-react";
import type { ColorRamp, MapStyle } from "../types";

interface Props {
  style: MapStyle;
  ramps: ColorRamp[];
  busy: boolean;
  /** Redraw the map with this ramp and legend range. */
  onApply: (ramp: string, min: number, max: number) => void;
}

/** A legend value as typed into a box: short, but exact enough to keep the map unchanged. */
function asText(value: number): string {
  return String(Number(value.toPrecision(6)));
}

function gradient(colors: string[]): string {
  const css = colors.map((c) => (/^[0-9a-f]{3}([0-9a-f]{3})?$/i.test(c) ? `#${c}` : c));
  return `linear-gradient(90deg, ${css.join(", ")})`;
}

/** Colour ramp and legend range of a finished map, changed in place. */
export function StyleControls({ style, ramps, busy, onApply }: Props) {
  const [minText, setMinText] = useState(asText(style.min));
  const [maxText, setMaxText] = useState(asText(style.max));
  const [error, setError] = useState<string | null>(null);

  // Follow the map's style when it changes (a new map, a reset, another tab's change).
  useEffect(() => {
    setMinText(asText(style.min));
    setMaxText(asText(style.max));
    setError(null);
  }, [style.version, style.min, style.max]);

  const range = (): [number, number] | null => {
    const min = Number(minText);
    const max = Number(maxText);
    if (minText.trim() === "" || maxText.trim() === "" || !Number.isFinite(min) || !Number.isFinite(max)) {
      setError("Type a number for both the minimum and the maximum.");
      return null;
    }
    if (max <= min) {
      setError("The maximum must be greater than the minimum.");
      return null;
    }
    setError(null);
    return [min, max];
  };

  const pickRamp = (ramp: string) => {
    const r = range();
    if (r) onApply(ramp, r[0], r[1]);
  };

  const applyRange = (e: FormEvent) => {
    e.preventDefault();
    const r = range();
    if (r) onApply(style.ramp, r[0], r[1]);
  };

  const groups = Array.from(new Set(ramps.map((r) => r.group)));
  const current = style.ramp === "original" ? style.original.palette : (ramps.find((r) => r.id === style.ramp)?.colors ?? style.palette);
  const rangeChanged = minText !== asText(style.min) || maxText !== asText(style.max);
  const isOriginal =
    style.ramp === "original" && style.min === style.original.min && style.max === style.original.max;

  return (
    <form className="style-bar" onSubmit={applyRange} aria-label="Map colours">
      <div className="style-field style-field-ramp">
        <label htmlFor="style-ramp">
          <Palette size={13} /> Colour ramp
        </label>
        <div className="style-ramp">
          <span className="ramp-swatch" style={{ background: gradient(current) }} aria-hidden="true" />
          <select
            id="style-ramp"
            className="input style-input"
            value={style.ramp}
            disabled={busy}
            onChange={(e) => pickRamp(e.target.value)}
          >
            <optgroup label="This map">
              <option value="original">Original colours</option>
            </optgroup>
            {groups.map((group) => (
              <optgroup key={group} label={group === "QGIS" ? "QGIS colour ramps" : `${group} palettes`}>
                {ramps
                  .filter((r) => r.group === group)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </div>
      </div>

      <div className="style-field">
        <label htmlFor="style-min">Legend min</label>
        <input
          id="style-min"
          className="input style-input style-number"
          type="number"
          step="any"
          value={minText}
          disabled={busy}
          onChange={(e) => setMinText(e.target.value)}
        />
      </div>
      <div className="style-field">
        <label htmlFor="style-max">Legend max</label>
        <input
          id="style-max"
          className="input style-input style-number"
          type="number"
          step="any"
          value={maxText}
          disabled={busy}
          onChange={(e) => setMaxText(e.target.value)}
        />
      </div>

      <div className="style-actions">
        <button className="tool" type="submit" disabled={busy || !rangeChanged}>
          <Check size={15} /> Apply
        </button>
        <button
          className="tool"
          type="button"
          disabled={busy || isOriginal}
          onClick={() => {
            setError(null);
            onApply("original", style.original.min, style.original.max);
          }}
          title="Back to the colours and range the map was made with"
        >
          <RotateCcw size={15} /> Reset
        </button>
      </div>

      {error && (
        <div className="field-error style-error" role="alert">
          {error}
        </div>
      )}
    </form>
  );
}

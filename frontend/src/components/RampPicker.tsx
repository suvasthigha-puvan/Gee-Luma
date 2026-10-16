import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown } from "lucide-react";

export interface RampChoice {
  id: string;
  name: string;
  colors: string[];
}

export interface RampGroup {
  label: string;
  ramps: RampChoice[];
}

interface Props {
  id: string;
  value: string;
  groups: RampGroup[];
  disabled?: boolean;
  onChange: (id: string) => void;
}

export function rampGradient(colors: string[]): string {
  const css = colors.map((c) => (/^[0-9a-f]{3}([0-9a-f]{3})?$/i.test(c) ? `#${c}` : c));
  return `linear-gradient(90deg, ${css.join(", ")})`;
}

/**
 * A dropdown of colour ramps, each shown with its colour bar - which a
 * native <select> cannot draw. Works with the mouse and the keyboard
 * (arrows, Home/End, Enter, Escape) like a select.
 */
export function RampPicker({ id, value, groups, disabled, onChange }: Props) {
  const all = groups.flatMap((g) => g.ramps);
  const current = all.find((r) => r.id === value) ?? all[0];
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  const show = () => {
    setActive(Math.max(0, all.findIndex((r) => r.id === value)));
    setOpen(true);
  };
  const close = (focusTrigger = true) => {
    setOpen(false);
    if (focusTrigger) trigger.current?.focus();
  };
  const choose = (ramp: RampChoice) => {
    close();
    if (ramp.id !== value) onChange(ramp.id);
  };

  // Close when the person clicks anywhere else.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Keep the highlighted ramp in view, and the list focused for the keyboard.
  useEffect(() => {
    if (!open) return;
    list.current?.focus();
    document.getElementById(`${id}-opt-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, id]);

  const onTriggerKey = (e: KeyboardEvent) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      show();
    }
  };

  const onListKey = (e: KeyboardEvent) => {
    const last = all.length - 1;
    const moves: Record<string, number> = {
      ArrowDown: Math.min(last, active + 1), ArrowUp: Math.max(0, active - 1), Home: 0, End: last,
      PageDown: Math.min(last, active + 8), PageUp: Math.max(0, active - 8),
    };
    if (e.key in moves) {
      e.preventDefault();
      setActive(moves[e.key]);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      choose(all[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "Tab") {
      close(false);
    }
  };

  let index = -1;
  return (
    <div className="ramp-picker" ref={root}>
      <button
        ref={trigger}
        id={id}
        type="button"
        className="input style-input ramp-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => (open ? close() : show())}
        onKeyDown={onTriggerKey}
      >
        <span className="ramp-name">{current?.name}</span>
        {current && <span className="ramp-bar" style={{ background: rampGradient(current.colors) }} />}
        <ChevronDown size={15} className="ramp-chevron" />
      </button>

      {open && (
        <ul
          ref={list}
          className="ramp-menu"
          role="listbox"
          aria-labelledby={id}
          tabIndex={-1}
          aria-activedescendant={`${id}-opt-${active}`}
          onKeyDown={onListKey}
        >
          {groups.map((group) => (
            <li key={group.label} role="presentation">
              <div className="ramp-group">{group.label}</div>
              <ul role="group" aria-label={group.label}>
                {group.ramps.map((ramp) => {
                  index += 1;
                  const i = index;
                  return (
                    <li
                      key={ramp.id}
                      id={`${id}-opt-${i}`}
                      role="option"
                      aria-selected={ramp.id === value}
                      className={`ramp-option${i === active ? " is-active" : ""}`}
                      onMouseEnter={() => setActive(i)}
                      onClick={() => choose(ramp)}
                    >
                      <span className="ramp-name">{ramp.name}</span>
                      <span className="ramp-bar" style={{ background: rampGradient(ramp.colors) }} />
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

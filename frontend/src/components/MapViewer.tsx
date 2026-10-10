import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Maximize2, Minus, Plus, ScanSearch } from "lucide-react";

interface Props {
  src: string;
  alt: string;
  /** Shown over the map while something is being prepared (e.g. the original render). */
  busyLabel?: string | null;
}

const MIN_SCALE = 1;
const MAX_SCALE = 8;

/** The map image with wheel/pinch-free zoom, drag to pan and a fit button. */
export function MapViewer({ src, alt, busyLabel }: Props) {
  const frame = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const [loaded, setLoaded] = useState(false);
  const drag = useRef<{ startX: number; startY: number; x: number; y: number } | null>(null);

  // A new image starts fitted to the frame.
  useEffect(() => {
    setView({ scale: 1, x: 0, y: 0 });
    setLoaded(false);
  }, [src]);

  const clamp = useCallback((scale: number, x: number, y: number) => {
    const el = frame.current;
    if (!el) return { scale, x, y };
    // Keep the image from being dragged entirely out of the frame.
    const maxX = (el.clientWidth * (scale - 1)) / 2;
    const maxY = (el.clientHeight * (scale - 1)) / 2;
    return { scale, x: Math.min(maxX, Math.max(-maxX, x)), y: Math.min(maxY, Math.max(-maxY, y)) };
  }, []);

  const zoomAt = useCallback(
    (factor: number, clientX?: number, clientY?: number) => {
      setView((v) => {
        const el = frame.current;
        const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale * factor));
        if (!el || scale === v.scale) return v;
        const rect = el.getBoundingClientRect();
        // Zoom about the pointer (or the centre when using the buttons).
        const px = (clientX ?? rect.left + rect.width / 2) - rect.left - rect.width / 2;
        const py = (clientY ?? rect.top + rect.height / 2) - rect.top - rect.height / 2;
        const ratio = scale / v.scale;
        return clamp(scale, px - (px - v.x) * ratio, py - (py - v.y) * ratio);
      });
    },
    [clamp],
  );

  // Wheel must be registered as non-passive to stop the page scrolling while zooming.
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && view.scale === 1 && e.deltaY > 0) return; // let the page scroll past a fitted map
      e.preventDefault();
      zoomAt(e.deltaY < 0 ? 1.18 : 1 / 1.18, e.clientX, e.clientY);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt, view.scale]);

  const zoomed = view.scale > 1.001;

  return (
    <div className="viewer">
      <div
        ref={frame}
        className={`viewer-frame ${zoomed ? "is-zoomed" : ""}`}
        onPointerDown={(e) => {
          if (!zoomed) return;
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          drag.current = { startX: e.clientX, startY: e.clientY, x: view.x, y: view.y };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          setView((v) => clamp(v.scale, d.x + e.clientX - d.startX, d.y + e.clientY - d.startY));
        }}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        onDoubleClick={(e) => zoomAt(zoomed ? 1 / view.scale : 2.2, e.clientX, e.clientY)}
      >
        {!loaded && (
          <div className="viewer-loading">
            <Loader2 size={20} className="spin" />
          </div>
        )}
        <img
          src={src}
          alt={alt}
          draggable={false}
          onLoad={() => setLoaded(true)}
          style={{
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
            opacity: loaded ? 1 : 0,
          }}
        />
        {busyLabel && (
          <div className="viewer-busy">
            <Loader2 size={18} className="spin" /> {busyLabel}
          </div>
        )}
      </div>

      <div className="viewer-controls" role="group" aria-label="Map zoom">
        <button onClick={() => zoomAt(1.4)} aria-label="Zoom in" title="Zoom in" disabled={view.scale >= MAX_SCALE}>
          <Plus size={16} />
        </button>
        <button onClick={() => zoomAt(1 / 1.4)} aria-label="Zoom out" title="Zoom out" disabled={!zoomed}>
          <Minus size={16} />
        </button>
        <button onClick={() => setView({ scale: 1, x: 0, y: 0 })} aria-label="Fit map" title="Fit" disabled={!zoomed}>
          <ScanSearch size={16} />
        </button>
        <a href={src} target="_blank" rel="noreferrer" aria-label="Open full size" title="Open full size">
          <Maximize2 size={15} />
        </a>
      </div>
      <div className="viewer-hint">{zoomed ? `${Math.round(view.scale * 100)}% · drag to move` : "Scroll or double-click to zoom"}</div>
    </div>
  );
}

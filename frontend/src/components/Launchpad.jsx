import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import "./launchpad.css";

const ResponsiveGridLayout = WidthProvider(Responsive);
const STORAGE_KEY = "bt.launchpad.layouts.v1";
const HIDDEN_KEY = "bt.launchpad.hidden.v1";

const BREAKPOINTS = { lg: 1280, md: 960, sm: 720, xs: 480 };
const COLS = { lg: 12, md: 12, sm: 6, xs: 4 };

function readJson(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage disabled / quota — non-fatal
  }
}

export default function Launchpad({ panels, defaultLayouts, editMode, resetKey, flash }) {
  const [layouts, setLayouts] = useState(
    () => readJson(STORAGE_KEY) ?? defaultLayouts
  );
  const [hidden, setHidden] = useState(() => new Set(readJson(HIDDEN_KEY) ?? []));

  useEffect(() => {
    // External reset (triggered by the RESET mnemonic) wipes overrides.
    setLayouts(defaultLayouts);
    setHidden(new Set());
    writeJson(STORAGE_KEY, defaultLayouts);
    writeJson(HIDDEN_KEY, []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const onLayoutChange = useCallback((_current, allLayouts) => {
    setLayouts(allLayouts);
    writeJson(STORAGE_KEY, allLayouts);
  }, []);

  const toggleHidden = useCallback((id) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      writeJson(HIDDEN_KEY, Array.from(next));
      return next;
    });
  }, []);

  const visiblePanels = useMemo(
    () => panels.filter((p) => !hidden.has(p.id)),
    [panels, hidden]
  );

  // Scroll the flashed panel into view when a command fires. Without this
  // you can type "AAPL EXPLAIN" and see nothing happen because the panel
  // is below the fold in the dense grid.
  const tileRefs = useRef({});
  useEffect(() => {
    if (!flash) return;
    const el = tileRefs.current[flash];
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
    }
  }, [flash]);

  return (
    <div className={editMode ? "launchpad edit-mode" : "launchpad"}>
      {editMode ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-terminal-amber/60 bg-terminal-panelAlt px-2 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
          <span className="text-terminal-amber">LAYOUT EDIT</span>
          <span>Drag panel headers · resize from corners · toggle panels ↓</span>
          <div className="ml-auto flex flex-wrap gap-1">
            {panels.map((p) => (
              <button
                key={p.id}
                onClick={() => toggleHidden(p.id)}
                className={`px-2 py-0.5 border ${
                  hidden.has(p.id)
                    ? "border-terminal-border text-terminal-muted"
                    : "border-terminal-amber text-terminal-amber"
                }`}
              >
                {hidden.has(p.id) ? "＋" : "✓"} {p.id}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <ResponsiveGridLayout
        className="layout"
        breakpoints={BREAKPOINTS}
        cols={COLS}
        rowHeight={44}
        margin={[8, 8]}
        layouts={layouts}
        onLayoutChange={onLayoutChange}
        draggableHandle=".panel-drag-handle"
        isDraggable={editMode}
        isResizable={editMode}
        compactType="vertical"
        useCSSTransforms
      >
        {visiblePanels.map((p) => (
          <div
            key={p.id}
            ref={(node) => {
              if (node) tileRefs.current[p.id] = node;
              else delete tileRefs.current[p.id];
            }}
            className={`flex min-h-0 ${flash === p.id ? "panel-flash" : ""}`}
          >
            {p.render()}
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
}

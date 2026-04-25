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

// Merge any panel ids in `defaults` that are missing from `saved`.
// Preserves the user's hand-arranged positions for panels they already
// have, and slots in factory positions for newly added panels (otherwise
// react-grid-layout autoplaces them at 0,0 with minimum size — which is
// what produces the "scrunched in the bottom-left corner" bug after a
// release adds new panels).
function mergeMissing(saved, defaults) {
  if (!saved) return defaults;
  const out = {};
  for (const bp of Object.keys(defaults)) {
    const savedRows = Array.isArray(saved[bp]) ? saved[bp] : [];
    const havingIds = new Set(savedRows.map((r) => r.i));
    const missing = (defaults[bp] || []).filter((r) => !havingIds.has(r.i));
    out[bp] = [...savedRows, ...missing];
  }
  return out;
}

export default function Launchpad({
  panels,
  defaultLayouts,
  editMode,
  resetKey,
  flash,
  // When provided, the parent owns layout persistence (e.g. syncing to a
  // logged-in user's Postgres state). The component still falls back to
  // localStorage for unauthenticated sessions.
  controlledLayouts,
  controlledHidden,
  onLayoutsChange,
  onHiddenChange,
  // Optional Share button slot — Terminal supplies a click handler that
  // opens the share dialog for signed-in users. Hidden for everyone else.
  onShare,
  readOnly = false,
}) {
  const controlled = controlledLayouts != null;

  const [localLayouts, setLocalLayouts] = useState(
    () => mergeMissing(readJson(STORAGE_KEY), defaultLayouts)
  );
  const [localHidden, setLocalHidden] = useState(
    () => new Set(readJson(HIDDEN_KEY) ?? [])
  );

  // When the parent supplies a saved layout (after login), seed it through
  // the same merge step so a release adding new panels doesn't strand them.
  const layouts = useMemo(() => {
    if (!controlled) return localLayouts;
    const incoming =
      controlledLayouts && Object.keys(controlledLayouts).length
        ? controlledLayouts
        : null;
    return mergeMissing(incoming, defaultLayouts);
  }, [controlled, controlledLayouts, localLayouts, defaultLayouts]);

  const hidden = useMemo(() => {
    if (controlled) return new Set(controlledHidden || []);
    return localHidden;
  }, [controlled, controlledHidden, localHidden]);

  useEffect(() => {
    // External reset (triggered by the RESET mnemonic) wipes overrides.
    if (controlled) {
      onLayoutsChange?.(defaultLayouts);
      onHiddenChange?.([]);
    } else {
      setLocalLayouts(defaultLayouts);
      setLocalHidden(new Set());
      writeJson(STORAGE_KEY, defaultLayouts);
      writeJson(HIDDEN_KEY, []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  // After a release adds new panels, persist the merged layout once so we
  // don't re-merge on every refresh and so saved positions for the new
  // panels survive a future panel removal.
  useEffect(() => {
    if (!controlled) writeJson(STORAGE_KEY, layouts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onLayoutChange = useCallback(
    (_current, allLayouts) => {
      if (controlled) {
        onLayoutsChange?.(allLayouts);
      } else {
        setLocalLayouts(allLayouts);
        writeJson(STORAGE_KEY, allLayouts);
      }
    },
    [controlled, onLayoutsChange]
  );

  const toggleHidden = useCallback(
    (id) => {
      if (controlled) {
        const next = new Set(controlledHidden || []);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        onHiddenChange?.(Array.from(next));
        return;
      }
      setLocalHidden((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        writeJson(HIDDEN_KEY, Array.from(next));
        return next;
      });
    },
    [controlled, controlledHidden, onHiddenChange]
  );

  const visiblePanels = useMemo(
    () => panels.filter((p) => !hidden.has(p.id)),
    [panels, hidden]
  );

  // Scroll the flashed panel into view ONLY if it isn't already visible.
  // Clicking a chip for a panel that's already on screen used to jump the
  // viewport (centering "the active panel") which felt like a glitch — the
  // amber flash is enough visual feedback when the panel is in view. We
  // still scroll when the panel is fully or mostly off-screen so chips for
  // panels lower in the layout actually go somewhere.
  const tileRefs = useRef({});
  useEffect(() => {
    if (!flash) return;
    const el = tileRefs.current[flash];
    if (!el || typeof el.getBoundingClientRect !== "function") return;
    const rect = el.getBoundingClientRect();
    const viewportH = window.innerHeight || document.documentElement.clientHeight;
    // Treat "in view" as: at least 30% of the panel's height is on screen.
    // This still fires the scroll when the panel is barely peeking from
    // the top/bottom edge — those cases benefit from being centered.
    const visibleTop = Math.max(0, rect.top);
    const visibleBottom = Math.min(viewportH, rect.bottom);
    const visibleHeight = Math.max(0, visibleBottom - visibleTop);
    const inView = rect.height > 0 && visibleHeight / rect.height >= 0.3;
    if (inView) return;
    el.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  }, [flash]);

  return (
    <div className={editMode ? "launchpad edit-mode" : "launchpad"}>
      {editMode ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-terminal-amber/60 bg-terminal-panelAlt px-2 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
          <span className="text-terminal-amber">LAYOUT EDIT</span>
          <span>Drag panel headers · resize from corners · toggle panels ↓</span>
          {onShare ? (
            <button
              onClick={onShare}
              className="border border-terminal-amber px-2 py-0.5 text-terminal-amber hover:bg-terminal-amber/10"
            >
              ↗ SHARE
            </button>
          ) : null}
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

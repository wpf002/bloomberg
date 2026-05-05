import { useEffect, useId, useMemo, useRef, useState } from "react";
import Panel from "./Panel.jsx";
import { useTranslation } from "../i18n/index.jsx";

const TV_SCRIPT_SRC = "https://s3.tradingview.com/tv.js";
const TV_SCRIPT_ID = "tradingview-widget-loader";

const INTERVALS = [
  ["1m",  "1"],
  ["5m",  "5"],
  ["10m", "10"],
  ["15m", "15"],
  ["30m", "30"],
  ["1h",  "60"],
  ["2h",  "120"],
  ["3h",  "180"],
  ["6h",  "360"],
  ["12h", "720"],
  ["1D",  "D"],
  ["1W",  "W"],
  ["1M",  "M"],
];

const STORAGE_KEY = "bt.chart.interval.v1";
const DEFAULT_INTERVAL = "D";

function loadInterval() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v && INTERVALS.some(([, code]) => code === v)) return v;
  } catch {
    // ignore
  }
  return DEFAULT_INTERVAL;
}

function persistInterval(code) {
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // ignore
  }
}

let tvScriptPromise = null;
function loadTradingViewScript() {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.TradingView) return Promise.resolve(window.TradingView);
  if (tvScriptPromise) return tvScriptPromise;
  tvScriptPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById(TV_SCRIPT_ID);
    if (existing) {
      existing.addEventListener("load", () => resolve(window.TradingView));
      existing.addEventListener("error", reject);
      return;
    }
    const s = document.createElement("script");
    s.id = TV_SCRIPT_ID;
    s.src = TV_SCRIPT_SRC;
    s.async = true;
    s.onload = () => resolve(window.TradingView);
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return tvScriptPromise;
}

// TradingView only ships locales for a fixed set; map ours.
function tvLocale(code) {
  if (code === "es") return "es";
  if (code === "pt") return "pt";
  if (code === "zh") return "zh_CN";
  return "en";
}

export default function Chart({ symbol }) {
  const { t, locale } = useTranslation();
  const containerId = useId().replace(/[:]/g, "_") + "_tv";
  const [interval, setInterval] = useState(() => loadInterval());
  const [error, setError] = useState(null);
  const containerRef = useRef(null);
  const widgetRef = useRef(null);

  const tvSymbol = useMemo(() => (symbol ? String(symbol).toUpperCase() : "AAPL"), [symbol]);

  useEffect(() => {
    persistInterval(interval);
  }, [interval]);

  useEffect(() => {
    let cancelled = false;
    setError(null);

    loadTradingViewScript()
      .then((TV) => {
        if (cancelled || !TV || !containerRef.current) return;
        // Clear any previous widget render in the container.
        containerRef.current.innerHTML = "";
        try {
          // eslint-disable-next-line new-cap
          widgetRef.current = new TV.widget({
            container_id: containerId,
            symbol: tvSymbol,
            interval,
            theme: "dark",
            autosize: true,
            locale: tvLocale(locale),
            timezone: "Etc/UTC",
            style: "1", // candles
            hide_top_toolbar: false,
            hide_legend: false,
            save_image: false,
            allow_symbol_change: false,
            withdateranges: false,
            extended_hours: true,
            toolbar_bg: "#0b0d10",
            backgroundColor: "#0b0d10",
            gridColor: "#1f242c",
            studies: [],
          });
        } catch (e) {
          setError(e?.message || "TradingView widget failed to mount");
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || "Failed to load TradingView");
      });

    return () => {
      cancelled = true;
      if (containerRef.current) containerRef.current.innerHTML = "";
      widgetRef.current = null;
    };
  }, [tvSymbol, interval, locale, containerId]);

  return (
    <Panel
      title={t("p.chart.title", { sym: tvSymbol })}
      accent="blue"
      actions={
        <div className="flex flex-wrap items-center gap-1">
          {INTERVALS.map(([label, code]) => (
            <button
              key={code}
              onClick={() => setInterval(code)}
              className={`px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                code === interval
                  ? "bg-terminal-amber text-black"
                  : "text-terminal-muted hover:text-terminal-text"
              }`}
              title={t("p.chart.interval_title", { label })}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      <div className="flex h-full flex-col">
        {error ? (
          <div className="text-xs text-terminal-muted">
            {t("p.chart.tv_error", { msg: error })}
          </div>
        ) : null}
        <div className="flex-1 min-h-[320px]">
          <div
            id={containerId}
            ref={containerRef}
            className="h-full w-full"
            style={{ minHeight: 320 }}
          />
        </div>
      </div>
    </Panel>
  );
}

import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

function relativeTime(iso) {
  const delta = (Date.now() - new Date(iso).getTime()) / 1000;
  if (delta < 60) return `${Math.floor(delta)}s`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
  return `${Math.floor(delta / 86400)}d`;
}

export default function NewsFeed({ symbols }) {
  const { t } = useTranslation();
  const { data, error, loading } = usePolling(
    () => api.news(symbols, 30),
    60_000,
    [symbols.join(",")]
  );

  return (
    <Panel
      title={t("panels.news")}
      accent="amber"
      actions={<span className="text-terminal-muted">{symbols.join(" · ")}</span>}
    >
      {loading && !data ? (
        <div className="text-terminal-muted">{t("p.news.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (data || []).length === 0 ? (
        <div className="text-terminal-muted">{t("p.news.none")}</div>
      ) : (
        <ul className="divide-y divide-terminal-border/60">
          {data.map((item) => (
            <li key={item.id} className="py-2">
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer noopener"
                className="group block"
              >
                <div className="flex items-baseline gap-2 text-[10px] uppercase tracking-wider text-terminal-muted">
                  <span className="text-terminal-amber">{item.source}</span>
                  <span>{relativeTime(item.published_at)}</span>
                  {item.symbols?.length ? (
                    <span className="text-terminal-blue">
                      {item.symbols.slice(0, 4).join(" · ")}
                    </span>
                  ) : null}
                </div>
                <div className="text-sm text-terminal-text group-hover:text-terminal-amber">
                  {item.headline}
                </div>
                {item.summary ? (
                  <p className="mt-1 line-clamp-2 text-xs text-terminal-muted">
                    {item.summary}
                  </p>
                ) : null}
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const FORM_STYLE = {
  "10-K": "text-terminal-amber",
  "10-Q": "text-terminal-blue",
  "8-K": "text-terminal-green",
  DEF: "text-terminal-muted",
};

function styleFor(form) {
  const key = Object.keys(FORM_STYLE).find((k) => form.startsWith(k));
  return key ? FORM_STYLE[key] : "text-terminal-text";
}

export default function FilingsPanel({ symbol }) {
  const { t } = useTranslation();
  const { data, error, loading } = usePolling(
    () => api.filings(symbol),
    5 * 60_000,
    [symbol]
  );

  return (
    <Panel
      title={t("p.filings.title", { sym: symbol })}
      accent="amber"
      actions={
        <span className="text-terminal-muted">
          {data?.length ? t("p.filings.count", { count: data.length }) : ""}
        </span>
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">{t("p.filings.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (data || []).length === 0 ? (
        <div className="text-terminal-muted">{t("p.filings.none")}</div>
      ) : (
        <ul className="divide-y divide-terminal-border/60">
          {data.map((f) => (
            <li key={f.accession_number} className="py-1.5">
              <a
                href={f.url}
                target="_blank"
                rel="noreferrer noopener"
                className="group block"
              >
                <div className="flex items-baseline gap-2 text-[10px] uppercase tracking-wider text-terminal-muted">
                  <span className={`font-bold ${styleFor(f.form_type)}`}>
                    {f.form_type}
                  </span>
                  <span>{new Date(f.filed_at).toLocaleDateString()}</span>
                  <span className="ml-auto text-terminal-muted/60">{f.accession_number}</span>
                </div>
                <div className="truncate text-xs text-terminal-text group-hover:text-terminal-amber">
                  {f.company}
                </div>
                {f.primary_document ? (
                  <div className="truncate text-[10px] text-terminal-muted">
                    {f.primary_document}
                  </div>
                ) : null}
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

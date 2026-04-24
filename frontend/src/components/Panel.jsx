import clsx from "clsx";

export default function Panel({ title, accent = "amber", actions, children, className }) {
  const accentColor =
    accent === "green"
      ? "text-terminal-green"
      : accent === "red"
        ? "text-terminal-red"
        : accent === "blue"
          ? "text-terminal-blue"
          : "text-terminal-amber";

  return (
    <section
      className={clsx(
        "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border border-terminal-border bg-terminal-panel shadow-panel",
        className
      )}
    >
      <header className="panel-drag-handle flex items-center justify-between border-b border-terminal-border bg-terminal-panelAlt px-3 py-1.5 select-none">
        <h2 className={clsx("text-[11px] font-bold uppercase tracking-widest", accentColor)}>
          {title}
        </h2>
        {actions ? (
          <div
            className="flex items-center gap-2 text-xs"
            onMouseDown={(e) => e.stopPropagation()}
          >
            {actions}
          </div>
        ) : null}
      </header>
      <div className="flex-1 min-h-0 overflow-auto p-3 text-sm">{children}</div>
    </section>
  );
}

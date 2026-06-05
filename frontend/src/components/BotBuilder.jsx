import { useMemo, useState } from "react";
import clsx from "clsx";
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

// Strategy templates: each declares its tunable params with sane defaults.
// Kept in sync with backend/core/bots/strategies.py.
const STRATEGIES = [
  {
    key: "threshold_dca",
    label: "Threshold DCA",
    blurb: "Buy a fixed $ amount every time price drops N% from the prior close.",
    params: [
      { key: "drop_pct", label: "Drop %", default: 2, step: 0.1 },
      { key: "notional", label: "Buy $", default: 100, step: 10 },
    ],
  },
  {
    key: "ma_crossover",
    label: "MA crossover",
    blurb: "Buy on a fast/slow SMA golden cross; sell the position on a death cross.",
    params: [
      { key: "fast", label: "Fast SMA", default: 10, step: 1 },
      { key: "slow", label: "Slow SMA", default: 30, step: 1 },
      { key: "qty", label: "Shares", default: 1, step: 1 },
    ],
  },
  {
    key: "rsi_reversion",
    label: "RSI reversion",
    blurb: "Buy when RSI is oversold; sell the position when overbought.",
    params: [
      { key: "period", label: "Period", default: 14, step: 1 },
      { key: "low", label: "Oversold <", default: 30, step: 1 },
      { key: "high", label: "Overbought >", default: 70, step: 1 },
      { key: "qty", label: "Shares", default: 1, step: 1 },
    ],
  },
  {
    key: "bollinger",
    label: "Bollinger reversion",
    blurb: "Buy when price closes below the lower band; sell the position above the upper band.",
    params: [
      { key: "period", label: "Period", default: 20, step: 1 },
      { key: "std", label: "Std-dev mult", default: 2, step: 0.1 },
      { key: "qty", label: "Shares", default: 1, step: 1 },
    ],
  },
  {
    key: "breakout",
    label: "Donchian breakout",
    blurb: "Buy when price breaks the N-day high; sell the position when it breaks the N-day low.",
    params: [
      { key: "lookback", label: "Lookback (days)", default: 20, step: 1 },
      { key: "qty", label: "Shares", default: 1, step: 1 },
    ],
  },
  {
    key: "take_profit_stop",
    label: "Take-profit / stop",
    blurb: "Exit an open position at a take-profit or stop-loss threshold.",
    params: [
      { key: "take_profit_pct", label: "Take-profit %", default: 10, step: 0.5 },
      { key: "stop_loss_pct", label: "Stop-loss %", default: 5, step: 0.5 },
    ],
  },
  {
    key: "rebalance",
    label: "Rebalance",
    blurb: "Drift the position toward a target weight of account equity.",
    params: [
      { key: "target_weight", label: "Target weight (0–1)", default: 0.25, step: 0.05 },
      { key: "band_pct", label: "No-trade band %", default: 5, step: 0.5 },
    ],
  },
];

function defaultsFor(stratKey) {
  const s = STRATEGIES.find((x) => x.key === stratKey) || STRATEGIES[0];
  const out = {};
  s.params.forEach((p) => (out[p.key] = p.default));
  return out;
}

function Num({ label, value, onChange, step }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-terminal-muted">{label}</span>
      <input
        type="number"
        step={step ?? "any"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
      />
    </label>
  );
}

export default function BotBuilder({ defaultSymbol, status = {}, onCreated, onCancel }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [strategy, setStrategy] = useState("threshold_dca");
  const [symbols, setSymbols] = useState(defaultSymbol || "");
  const [params, setParams] = useState(defaultsFor("threshold_dca"));
  const [hybrid, setHybrid] = useState(false);
  const [requireApproval, setRequireApproval] = useState(true);
  const [broker, setBroker] = useState("alpaca");
  const [mode, setMode] = useState("paper");
  // guardrails
  const [maxPos, setMaxPos] = useState(1000);
  const [dailyLoss, setDailyLoss] = useState(200);
  const [maxOrders, setMaxOrders] = useState(10);
  const [cooldown, setCooldown] = useState(300);

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [armed, setArmed] = useState(false); // dry-run gate before create

  const strat = useMemo(() => STRATEGIES.find((s) => s.key === strategy), [strategy]);

  const onStrategyChange = (key) => {
    setStrategy(key);
    setParams(defaultsFor(key));
    setBacktest(null);
    setArmed(false);
  };

  const setParam = (k, v) => setParams((p) => ({ ...p, [k]: v }));

  const buildPayload = () => {
    const symList = symbols
      .split(/[,\s]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    const numericParams = {};
    Object.entries(params).forEach(([k, v]) => (numericParams[k] = Number(v)));
    return {
      name: name.trim() || `${strat.label} bot`,
      broker,
      mode,
      decision_mode: hybrid ? "hybrid" : "rule",
      require_approval: requireApproval,
      config: { strategy, symbols: symList, params: numericParams },
      guardrails: {
        max_position_usd: Number(maxPos),
        daily_loss_limit_usd: dailyLoss === "" ? null : Number(dailyLoss),
        max_orders_per_day: Number(maxOrders),
        per_symbol_cooldown_seconds: Number(cooldown),
        symbol_allowlist: symList,
      },
    };
  };

  const runDryRun = async () => {
    setBusy(true);
    setErr(null);
    try {
      const result = await api.backtestBot(buildPayload());
      setBacktest(result);
      setArmed(true);
    } catch (e) {
      setErr(e?.detail || e?.message || String(e));
      setArmed(false);
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      const bot = await api.createBot(buildPayload());
      onCreated?.(bot);
    } catch (e) {
      setErr(e?.detail || e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border border-terminal-border bg-terminal-bg p-2 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-terminal-amber">
          {t("p.bots.new_bot")}
        </span>
        <span className="rounded border border-terminal-green/60 px-1 text-[9px] uppercase tracking-widest text-terminal-green">
          {t("p.bots.paper")}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="col-span-2 flex flex-col gap-0.5">
          <span className="text-[10px] uppercase tracking-wider text-terminal-muted">{t("p.bots.name")}</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={strat?.label}
            className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
          />
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] uppercase tracking-wider text-terminal-muted">{t("p.bots.strategy")}</span>
          <select
            value={strategy}
            onChange={(e) => onStrategyChange(e.target.value)}
            className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
          >
            {STRATEGIES.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] uppercase tracking-wider text-terminal-muted">{t("p.bots.symbols")}</span>
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value.toUpperCase())}
            placeholder="AAPL"
            className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 uppercase tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
          />
        </label>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] uppercase tracking-wider text-terminal-muted">{t("p.bots.broker")}</span>
          <select
            value={broker}
            onChange={(e) => setBroker(e.target.value)}
            className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
          >
            <option value="alpaca">Alpaca</option>
            <option value="robinhood" disabled={!status.robinhood_enabled}>
              Robinhood {status.robinhood_enabled ? "" : `· ${t("p.bots.unavailable")}`}
            </option>
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] uppercase tracking-wider text-terminal-muted">{t("p.bots.mode")}</span>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            title={status.live_enabled ? undefined : t("p.bots.live_disabled_hint")}
            className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
          >
            <option value="paper">{t("p.bots.paper")}</option>
            <option value="live" disabled={!status.live_enabled}>
              {t("p.bots.live")} {status.live_enabled ? "" : `· ${t("p.bots.unavailable")}`}
            </option>
          </select>
        </label>
      </div>

      <p className="my-2 text-[11px] leading-relaxed text-terminal-muted">{strat?.blurb}</p>

      <div className="grid grid-cols-3 gap-2">
        {strat?.params.map((p) => (
          <Num key={p.key} label={p.label} step={p.step} value={params[p.key]} onChange={(v) => setParam(p.key, v)} />
        ))}
      </div>

      <div className="mt-2 text-[10px] uppercase tracking-widest text-terminal-muted">{t("p.bots.guardrails")}</div>
      <div className="grid grid-cols-4 gap-2">
        <Num label={t("p.bots.max_pos")} value={maxPos} onChange={setMaxPos} step={50} />
        <Num label={t("p.bots.daily_loss")} value={dailyLoss} onChange={setDailyLoss} step={25} />
        <Num label={t("p.bots.max_orders")} value={maxOrders} onChange={setMaxOrders} step={1} />
        <Num label={t("p.bots.cooldown")} value={cooldown} onChange={setCooldown} step={30} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1 text-terminal-muted">
          <input type="checkbox" checked={requireApproval} onChange={(e) => setRequireApproval(e.target.checked)} />
          {t("p.bots.require_approval")}
        </label>
        <label className="flex items-center gap-1 text-terminal-muted">
          <input type="checkbox" checked={hybrid} onChange={(e) => setHybrid(e.target.checked)} />
          {t("p.bots.hybrid")}
        </label>
      </div>

      {backtest && (
        <div className="mt-2 border border-terminal-border/60 bg-terminal-panelAlt p-2">
          <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{t("p.bots.dry_run_result")}</div>
          <div className="mt-1 grid grid-cols-4 gap-2 tabular">
            <Stat label={t("p.bots.pnl")} value={`${backtest.pnl >= 0 ? "+" : ""}${backtest.pnl_pct}%`}
                  tone={backtest.pnl >= 0 ? "green" : "red"} />
            <Stat label={t("p.bots.trades")} value={backtest.num_trades} />
            <Stat label={t("p.bots.max_dd")} value={`-${backtest.max_drawdown_pct}%`} tone="red" />
            <Stat label={t("p.bots.bars")} value={backtest.bars} />
          </div>
          {backtest.equity_curve?.length > 1 && (
            <div className="mt-2 h-24">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={backtest.equity_curve} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <YAxis hide domain={["dataMin", "dataMax"]} />
                  <Tooltip
                    contentStyle={{ background: "#1a1a1a", border: "1px solid #333", fontSize: 11 }}
                    formatter={(v) => [`$${v}`, "equity"]}
                    labelFormatter={() => ""}
                  />
                  <Line
                    type="monotone"
                    dataKey="equity"
                    stroke={backtest.pnl >= 0 ? "#26d07c" : "#ff5c5c"}
                    dot={false}
                    strokeWidth={1.5}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {err && <div className="mt-2 text-[11px] text-terminal-red">{err}</div>}

      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={runDryRun}
          disabled={busy || !symbols.trim()}
          className="border border-terminal-blue px-2 py-1 uppercase tracking-wider text-terminal-blue hover:bg-terminal-blue/10 disabled:opacity-50"
        >
          {busy ? t("p.common.creating") : t("p.bots.dry_run")}
        </button>
        <button
          onClick={create}
          disabled={busy || !armed}
          title={!armed ? t("p.bots.dry_run_first") : undefined}
          className={clsx(
            "border px-2 py-1 uppercase tracking-wider disabled:opacity-50",
            armed ? "border-terminal-amber text-terminal-amber hover:bg-terminal-amber/10" : "border-terminal-border text-terminal-muted"
          )}
        >
          {t("p.bots.create")}
        </button>
        {onCancel && (
          <button onClick={onCancel} className="ml-auto text-terminal-muted hover:text-terminal-text">
            {t("p.common.cancel")}
          </button>
        )}
      </div>
      {!armed && <p className="mt-1 text-[10px] text-terminal-muted">{t("p.bots.dry_run_first")}</p>}
    </div>
  );
}

function Stat({ label, value, tone }) {
  const color = tone === "green" ? "text-terminal-green" : tone === "red" ? "text-terminal-red" : "text-terminal-text";
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-wider text-terminal-muted">{label}</span>
      <span className={clsx("font-bold", color)}>{value}</span>
    </div>
  );
}

export { STRATEGIES };

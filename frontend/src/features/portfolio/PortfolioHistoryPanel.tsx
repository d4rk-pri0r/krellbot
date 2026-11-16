import { useEffect, useRef, useState, type JSX } from "react";
import "./PortfolioHistoryPanel.signal.css";
import type {
  PortfolioClient,
  PortfolioDeployment,
  PortfolioHistory,
} from "./client";

/**
 * Cross-deployment portfolio history from
 * ``GET /api/v1/portfolio/history`` (KRELL-SIGNAL-20261010).
 *
 * Renders the combined equity series and one card per deployment when
 * evidence exists. Empty or failed reads stay unavailable — never
 * fabricated sample bots or a flat zero equity path.
 */

export type PortfolioHistoryPanelProps = {
  client: PortfolioClient;
  /** Bumped to force a fresh read (e.g. after refresh / arm). */
  refreshKey?: number;
};

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; history: PortfolioHistory }
  | { status: "failed"; message: string };

const CHART_WIDTH = 640;
const CHART_HEIGHT = 200;
const PAD_TOP = 16;
const PAD_RIGHT = 12;
const PAD_BOTTOM = 28;
const PAD_LEFT = 52;

function readFinite(value: string): number | null {
  if (typeof value !== "string" || value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatCashTick(value: number): string {
  if (!Number.isFinite(value)) {
    return "—";
  }
  const abs = Math.abs(value);
  if (abs >= 1000) {
    return value.toFixed(0);
  }
  if (abs >= 1) {
    return value.toFixed(2);
  }
  return value.toFixed(4);
}

function deploymentCountLabel(count: number): string {
  return count === 1 ? "1 deployment" : `${count} deployments`;
}

export function PortfolioHistoryPanel({
  client,
  refreshKey = 0,
}: PortfolioHistoryPanelProps): JSX.Element {
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const epochRef = useRef(0);

  useEffect(() => {
    const epoch = ++epochRef.current;
    setState({ status: "loading" });
    client
      .getHistory()
      .then((history) => {
        if (epoch !== epochRef.current) {
          return;
        }
        setState({ status: "ready", history });
      })
      .catch((reason: unknown) => {
        if (epoch !== epochRef.current) {
          return;
        }
        const message =
          reason instanceof Error && reason.message
            ? reason.message
            : "Portfolio history unavailable";
        setState({ status: "failed", message });
      });
    return () => {
      epochRef.current += 1;
    };
  }, [client, refreshKey]);

  const history = state.status === "ready" ? state.history : null;
  const equityValues =
    history?.equity
      .map((point) => readFinite(point.value))
      .filter((value): value is number => value !== null) ?? [];
  const deployments = history?.deployments ?? [];

  return (
    <section
      className="kbot-portfolio"
      data-testid="portfolio-history-panel"
      aria-label="Portfolio history"
    >
      <header className="kbot-portfolio__header">
        <div>
          <h2 className="kbot-portfolio__title">Portfolio history</h2>
          <p className="kbot-portfolio__source">
            journal + paper fills · cross-deployment equity
          </p>
        </div>
        {state.status === "ready" ? (
          <span
            className="kbot-portfolio__count"
            data-testid="portfolio-history-count"
          >
            {deploymentCountLabel(deployments.length)}
          </span>
        ) : null}
      </header>

      {state.status === "loading" || state.status === "idle" ? (
        <p
          className="kbot-portfolio__empty"
          data-testid="portfolio-history-loading"
        >
          Reading portfolio history…
        </p>
      ) : null}

      {state.status === "failed" ? (
        <p
          className="kbot-portfolio__empty"
          role="alert"
          data-testid="portfolio-history-unavailable"
        >
          Portfolio history unavailable: {state.message}
        </p>
      ) : null}

      {state.status === "ready" ? (
        <>
          <EquityPanel series={equityValues.length > 0 ? equityValues : null} />
          <DeploymentsPanel deployments={deployments} />
        </>
      ) : null}
    </section>
  );
}

function EquityPanel({ series }: { series: number[] | null }): JSX.Element {
  return (
    <div
      className="kbot-portfolio__panel"
      data-testid="portfolio-equity-chart"
      aria-label="Portfolio equity"
    >
      <h3 className="kbot-portfolio__panel-title">Equity</h3>
      {series === null ? (
        <p
          className="kbot-portfolio__empty"
          data-testid="portfolio-equity-unavailable"
        >
          unavailable — no fill evidence with known starting cash yet
        </p>
      ) : (
        <EquitySvg series={series} />
      )}
    </div>
  );
}

function EquitySvg({ series }: { series: number[] }): JSX.Element {
  const plotWidth = CHART_WIDTH - PAD_LEFT - PAD_RIGHT;
  const plotHeight = CHART_HEIGHT - PAD_TOP - PAD_BOTTOM;
  let min = Math.min(...series);
  let max = Math.max(...series);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const range = max - min;

  const points = series
    .map((value, index) => {
      const x =
        PAD_LEFT +
        (series.length === 1 ? plotWidth / 2 : (index / (series.length - 1)) * plotWidth);
      const y = PAD_TOP + plotHeight - ((value - min) / range) * plotHeight;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const ticks = [min, (min + max) / 2, max];

  return (
    <svg
      className="kbot-portfolio__svg"
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={`Portfolio equity, ${series.length} points`}
      data-testid="portfolio-equity-chart-svg"
    >
      <rect
        className="kbot-portfolio__plot"
        x={PAD_LEFT}
        y={PAD_TOP}
        width={plotWidth}
        height={plotHeight}
      />
      {ticks.map((tick) => {
        const y = PAD_TOP + plotHeight - ((tick - min) / range) * plotHeight;
        return (
          <g key={tick}>
            <line
              className="kbot-portfolio__grid"
              x1={PAD_LEFT}
              x2={PAD_LEFT + plotWidth}
              y1={y}
              y2={y}
            />
            <text
              className="kbot-portfolio__axis"
              x={PAD_LEFT - 6}
              y={y + 3}
              textAnchor="end"
            >
              {formatCashTick(tick)}
            </text>
          </g>
        );
      })}
      <polyline
        className="kbot-portfolio__line"
        points={points}
        data-testid="portfolio-equity-chart-line"
      />
      <text
        className="kbot-portfolio__axis"
        x={PAD_LEFT + plotWidth / 2}
        y={CHART_HEIGHT - 6}
        textAnchor="middle"
      >
        fill index
      </text>
    </svg>
  );
}

function DeploymentsPanel({
  deployments,
}: {
  deployments: PortfolioDeployment[];
}): JSX.Element {
  return (
    <div
      className="kbot-portfolio__panel"
      data-testid="portfolio-deployments"
      aria-label="Deployments"
    >
      <h3 className="kbot-portfolio__panel-title">Deployments</h3>
      {deployments.length === 0 ? (
        <p
          className="kbot-portfolio__empty"
          data-testid="portfolio-deployments-empty"
        >
          No journalled or armed deployments yet.
        </p>
      ) : (
        <div className="kbot-portfolio__cards">
          {deployments.map((dep) => (
            <DeploymentCard
              key={`${dep.venue}|${dep.pack_id}|${dep.pair}|${dep.first_ts_ms}`}
              deployment={dep}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DeploymentCard({
  deployment,
}: {
  deployment: PortfolioDeployment;
}): JSX.Element {
  const statusTone =
    deployment.status === "active" ? "kbot-portfolio__status--active" : "";
  const pnlText =
    deployment.last_pnl !== null && deployment.last_pnl !== ""
      ? deployment.last_pnl
      : null;

  return (
    <article
      className="kbot-portfolio__card"
      data-testid="portfolio-deployment-card"
      aria-label={`${deployment.pair} ${deployment.pack_id}`}
    >
      <span className={`kbot-portfolio__status ${statusTone}`}>
        {deployment.status}
      </span>
      <p className="kbot-portfolio__card-pair">{deployment.pair}</p>
      <p className="kbot-portfolio__card-meta">
        {deployment.venue} · {deployment.pack_id} · {deployment.fills_total}{" "}
        {deployment.fills_total === 1 ? "fill" : "fills"}
      </p>
      {pnlText !== null ? (
        <p
          className="kbot-portfolio__card-pnl"
          data-testid="portfolio-deployment-pnl"
        >
          last P&L {pnlText}
        </p>
      ) : (
        <p
          className="kbot-portfolio__card-pnl kbot-portfolio__card-pnl--absent"
          data-testid="portfolio-deployment-pnl-absent"
        >
          P&L unavailable
        </p>
      )}
    </article>
  );
}

import { useEffect, useRef, useState, type JSX } from "react";
import "./PaperPnlPositionChart.signal.css";
import type { PaperChart, PaperClient } from "./client";

/**
 * Armed-paper P&L + position (or mark) charts from
 * ``GET /api/v1/paper/chart`` (KRELL-SIGNAL-20261010).
 *
 * Series come from journal ticks and paper-state fills. Empty or
 * failed reads stay unavailable — never a fabricated flat path.
 */

export type PaperPnlPositionChartProps = {
  /** Paper client; ``getChart`` may be absent on legacy test fakes. */
  client: Pick<PaperClient, "getChart">;
  /** When false the charts unmount; armed paper only. */
  armed: boolean;
  /** Bumped to force a fresh read (e.g. after refresh / arm). */
  refreshKey?: number;
};

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; chart: PaperChart }
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

export function PaperPnlPositionChart({
  client,
  armed,
  refreshKey = 0,
}: PaperPnlPositionChartProps): JSX.Element | null {
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const epochRef = useRef(0);

  useEffect(() => {
    if (!armed) {
      setState({ status: "idle" });
      return;
    }
    const getChart = client.getChart;
    if (typeof getChart !== "function") {
      setState({
        status: "failed",
        message: "Paper chart client unavailable",
      });
      return;
    }
    const epoch = ++epochRef.current;
    setState({ status: "loading" });
    getChart
      .call(client)
      .then((chart) => {
        if (epoch !== epochRef.current) {
          return;
        }
        setState({ status: "ready", chart });
      })
      .catch((reason: unknown) => {
        if (epoch !== epochRef.current) {
          return;
        }
        const message =
          reason instanceof Error && reason.message
            ? reason.message
            : "Paper chart unavailable";
        setState({ status: "failed", message });
      });
    return () => {
      epochRef.current += 1;
    };
  }, [client, armed, refreshKey]);

  if (!armed) {
    return null;
  }

  const chart = state.status === "ready" ? state.chart : null;
  const pnlValues =
    chart?.armed === true
      ? chart.pnl
          .map((point) => readFinite(point.value))
          .filter((value): value is number => value !== null)
      : [];
  const positionValues =
    chart?.armed === true
      ? chart.position
          .map((point) => readFinite(point.qty))
          .filter((value): value is number => value !== null)
      : [];
  const markValues =
    chart?.armed === true
      ? chart.marks
          .map((point) => readFinite(point.price))
          .filter((value): value is number => value !== null)
      : [];

  // Prefer position-over-time; fall back to mark series when the journal
  // has no owned-qty points (milestone allows either).
  const secondaryKind: "position" | "marks" =
    positionValues.length > 0 ? "position" : "marks";
  const secondaryValues =
    secondaryKind === "position" ? positionValues : markValues;

  return (
    <div
      className="kbot-paper-chart"
      data-testid="paper-pnl-position-chart"
      aria-label="Paper P&L and position charts"
    >
      {state.status === "loading" || state.status === "idle" ? (
        <p
          className="kbot-paper-chart__empty"
          data-testid="paper-chart-loading"
        >
          Reading paper chart…
        </p>
      ) : null}
      {state.status === "failed" ? (
        <p
          className="kbot-paper-chart__empty"
          role="alert"
          data-testid="paper-chart-unavailable"
        >
          Paper chart unavailable: {state.message}
        </p>
      ) : null}
      {state.status === "ready" && chart?.armed !== true ? (
        <p
          className="kbot-paper-chart__empty"
          data-testid="paper-chart-unavailable"
        >
          unavailable
        </p>
      ) : null}
      {state.status === "ready" && chart?.armed === true ? (
        <>
          <SeriesChart
            title="P&L"
            source="paper fills · cash + qty×mark − starting_cash"
            testId="paper-pnl-chart"
            series={pnlValues.length > 0 ? pnlValues : null}
            formatTick={formatCashTick}
            axisLabel="fill index"
          />
          <SeriesChart
            title={secondaryKind === "position" ? "Position" : "Marks"}
            source={
              secondaryKind === "position"
                ? "journal.owned_qty_after · base qty over time"
                : "paper fills · mark price series"
            }
            testId={
              secondaryKind === "position"
                ? "paper-position-chart"
                : "paper-marks-chart"
            }
            series={secondaryValues.length > 0 ? secondaryValues : null}
            formatTick={
              secondaryKind === "position" ? formatQtyTick : formatCashTick
            }
            axisLabel={
              secondaryKind === "position" ? "tick index" : "fill index"
            }
          />
        </>
      ) : null}
    </div>
  );
}

type SeriesChartProps = {
  title: string;
  source: string;
  testId: string;
  series: number[] | null;
  formatTick: (value: number) => string;
  axisLabel: string;
};

function SeriesChart({
  title,
  source,
  testId,
  series,
  formatTick,
  axisLabel,
}: SeriesChartProps): JSX.Element {
  return (
    <section
      className="kbot-paper-chart__panel"
      data-testid={testId}
      aria-label={title}
    >
      <div className="kbot-paper-chart__head">
        <h3 className="kbot-paper-chart__title">{title}</h3>
        <p className="kbot-paper-chart__source">{source}</p>
      </div>
      {series === null ? (
        <p
          className="kbot-paper-chart__empty"
          data-testid={`${testId}-unavailable`}
        >
          unavailable
        </p>
      ) : (
        <SeriesSvg
          series={series}
          testId={testId}
          formatTick={formatTick}
          axisLabel={axisLabel}
          ariaLabel={`${title}, ${series.length} points`}
        />
      )}
    </section>
  );
}

function SeriesSvg({
  series,
  testId,
  formatTick,
  axisLabel,
  ariaLabel,
}: {
  series: number[];
  testId: string;
  formatTick: (value: number) => string;
  axisLabel: string;
  ariaLabel: string;
}): JSX.Element {
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
        (series.length === 1
          ? plotWidth / 2
          : (index / (series.length - 1)) * plotWidth);
      const y = PAD_TOP + ((max - value) / range) * plotHeight;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const zeroInRange = min <= 0 && max >= 0;
  const zeroY = PAD_TOP + ((max - 0) / range) * plotHeight;
  const yTicks = [max, (max + min) / 2, min];

  return (
    <svg
      className="kbot-paper-chart__svg"
      data-testid={`${testId}-svg`}
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={ariaLabel}
    >
      <rect
        className="kbot-paper-chart__plot"
        x={PAD_LEFT}
        y={PAD_TOP}
        width={plotWidth}
        height={plotHeight}
      />
      {zeroInRange ? (
        <line
          className="kbot-paper-chart__zero"
          x1={PAD_LEFT}
          y1={zeroY}
          x2={PAD_LEFT + plotWidth}
          y2={zeroY}
        />
      ) : null}
      {yTicks.map((tick, index) => {
        const y = PAD_TOP + ((max - tick) / range) * plotHeight;
        return (
          <g key={`ytick-${index}`}>
            <line
              className="kbot-paper-chart__grid"
              x1={PAD_LEFT}
              y1={y}
              x2={PAD_LEFT + plotWidth}
              y2={y}
            />
            <text
              className="kbot-paper-chart__tick"
              x={PAD_LEFT - 8}
              y={y + 3}
              textAnchor="end"
            >
              {formatTick(tick)}
            </text>
          </g>
        );
      })}
      <polyline
        className="kbot-paper-chart__line"
        data-testid={`${testId}-line`}
        fill="none"
        points={points}
      />
      <text
        className="kbot-paper-chart__axis"
        x={PAD_LEFT + plotWidth / 2}
        y={CHART_HEIGHT - 6}
        textAnchor="middle"
      >
        {axisLabel}
      </text>
    </svg>
  );
}

function formatCashTick(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1000) {
    return value.toFixed(0);
  }
  if (abs >= 10) {
    return value.toFixed(2);
  }
  return value.toFixed(4);
}

function formatQtyTick(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 100) {
    return value.toFixed(1);
  }
  if (abs >= 1) {
    return value.toFixed(2);
  }
  return value.toFixed(4);
}

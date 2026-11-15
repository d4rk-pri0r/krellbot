import type { JSX } from "react";

/**
 * Read ``receipt.equity_curve`` as a finite percent-return series.
 *
 * Production receipts carry a downsampled percentage series (not cash).
 * Wrong-shape, empty, or non-finite entries yield null — never a
 * fabricated flat zero curve.
 */
export function readEquityCurve(
  receipt: Record<string, unknown>,
): number[] | null {
  const raw = receipt.equity_curve;
  if (!Array.isArray(raw) || raw.length === 0) {
    return null;
  }
  const points: number[] = [];
  for (const value of raw) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return null;
    }
    points.push(value);
  }
  return points;
}

const CHART_WIDTH = 640;
const CHART_HEIGHT = 200;
const PAD_TOP = 16;
const PAD_RIGHT = 12;
const PAD_BOTTOM = 28;
const PAD_LEFT = 52;

export type EquityCurveChartProps = {
  series: number[] | null;
};

/**
 * Equity series chart for a research receipt (KRELL-SIGNAL-20261010).
 *
 * Renders an SVG polyline from the typed percent-return series when
 * present. Absent or wrong-shape data shows an unavailable state with
 * no invented path.
 */
export function EquityCurveChart({
  series,
}: EquityCurveChartProps): JSX.Element {
  return (
    <section
      className="kbot-research__equity-curve"
      data-testid="research-equity-curve"
      aria-label="Equity curve"
    >
      <div className="kbot-research__equity-curve-head">
        <h2 className="kbot-research__equity-curve-title">Equity curve</h2>
        <p className="kbot-research__equity-curve-source">
          receipt.equity_curve · percent return series
        </p>
      </div>
      {series === null ? (
        <p
          className="kbot-research__equity-curve-empty"
          data-testid="research-equity-curve-unavailable"
        >
          unavailable
        </p>
      ) : (
        <EquityCurveSvg series={series} />
      )}
    </section>
  );
}

function EquityCurveSvg({ series }: { series: number[] }): JSX.Element {
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
      className="kbot-research__equity-curve-svg"
      data-testid="research-equity-curve-svg"
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={`Equity curve, ${series.length} points from ${series[0]}% to ${series[series.length - 1]}%`}
    >
      <rect
        className="kbot-research__equity-curve-plot"
        x={PAD_LEFT}
        y={PAD_TOP}
        width={plotWidth}
        height={plotHeight}
      />
      {zeroInRange ? (
        <line
          className="kbot-research__equity-curve-zero"
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
              className="kbot-research__equity-curve-grid"
              x1={PAD_LEFT}
              y1={y}
              x2={PAD_LEFT + plotWidth}
              y2={y}
            />
            <text
              className="kbot-research__equity-curve-tick"
              x={PAD_LEFT - 8}
              y={y + 3}
              textAnchor="end"
            >
              {formatPctTick(tick)}
            </text>
          </g>
        );
      })}
      <polyline
        className="kbot-research__equity-curve-line"
        data-testid="research-equity-curve-line"
        fill="none"
        points={points}
      />
      <text
        className="kbot-research__equity-curve-axis"
        x={PAD_LEFT + plotWidth / 2}
        y={CHART_HEIGHT - 6}
        textAnchor="middle"
      >
        sample index
      </text>
    </svg>
  );
}

function formatPctTick(value: number): string {
  const rounded = Math.abs(value) >= 10 ? value.toFixed(1) : value.toFixed(2);
  return `${rounded}%`;
}

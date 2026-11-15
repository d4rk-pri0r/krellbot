import type { JSX } from "react";

/**
 * Price series + trade markers from a research result/trace
 * (KRELL-SIGNAL-20261010).
 *
 * Price comes from finite ``trace[].input.close`` values. Markers come
 * from ``trace[].target.reason`` entry/exit decisions (and optionally
 * ``receipt.trades`` rows that carry a linkable ``bar_ts``/``ts_ms`` and
 * side). Missing or wrong-shape data stays unavailable — never a
 * fabricated flat path or invented marker positions.
 */

export type PricePoint = {
  barTs: number;
  close: number;
  index: number;
};

export type TradeMarker = {
  barTs: number;
  close: number;
  side: "buy" | "sell";
  index: number;
  source: "trace.target" | "receipt.trades";
};

function readFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function readBarTs(bar: Record<string, unknown>, index: number): number | null {
  const direct = readFiniteNumber(bar.bar_ts);
  if (direct !== null) {
    return direct;
  }
  const input = bar.input;
  if (input && typeof input === "object" && !Array.isArray(input)) {
    const fromInput = readFiniteNumber((input as Record<string, unknown>).ts_ms);
    if (fromInput !== null) {
      return fromInput;
    }
  }
  // Index is a last-resort stable x key only when the bar itself is
  // otherwise readable; callers that need a real series still require
  // a finite close.
  return index;
}

function readClose(bar: Record<string, unknown>): number | null {
  const input = bar.input;
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return null;
  }
  return readFiniteNumber((input as Record<string, unknown>).close);
}

function readTargetReason(bar: Record<string, unknown>): string | null {
  const target = bar.target;
  if (!target || typeof target !== "object" || Array.isArray(target)) {
    return null;
  }
  const reason = (target as Record<string, unknown>).reason;
  return typeof reason === "string" ? reason : null;
}

function sideFromReason(reason: string): "buy" | "sell" | null {
  if (reason === "entry") {
    return "buy";
  }
  if (reason === "exit") {
    return "sell";
  }
  return null;
}

function sideFromTrade(value: unknown): "buy" | "sell" | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === "buy" || normalized === "entry") {
    return "buy";
  }
  if (normalized === "sell" || normalized === "exit") {
    return "sell";
  }
  return null;
}

/**
 * Read a finite close series from the decision trace. Empty, missing, or
 * non-finite closes yield null — never a fabricated zero series.
 */
export function readPriceSeries(
  trace: Array<Record<string, unknown>>,
): PricePoint[] | null {
  if (!Array.isArray(trace) || trace.length === 0) {
    return null;
  }
  const points: PricePoint[] = [];
  for (let index = 0; index < trace.length; index += 1) {
    const bar = trace[index];
    if (!bar || typeof bar !== "object" || Array.isArray(bar)) {
      return null;
    }
    const close = readClose(bar);
    const barTs = readBarTs(bar, index);
    if (close === null || barTs === null) {
      return null;
    }
    points.push({ barTs, close, index });
  }
  return points;
}

/**
 * Trade markers from result/trace.
 *
 * Primary: ``trace[].target.reason`` of ``entry`` / ``exit`` at that
 * bar's close. Secondary: ``receipt.trades`` rows with a finite
 * ``bar_ts`` or ``ts_ms`` that matches a trace bar and a readable side.
 * Side-only trades without timestamps are ignored (no invented x).
 */
export function readTradeMarkers(
  receipt: Record<string, unknown>,
  trace: Array<Record<string, unknown>>,
): TradeMarker[] {
  const series = readPriceSeries(trace);
  if (series === null) {
    return [];
  }
  const byTs = new Map<number, PricePoint>();
  for (const point of series) {
    byTs.set(point.barTs, point);
  }

  const markers: TradeMarker[] = [];
  const seen = new Set<string>();

  for (let index = 0; index < trace.length; index += 1) {
    const bar = trace[index];
    if (!bar || typeof bar !== "object" || Array.isArray(bar)) {
      continue;
    }
    const reason = readTargetReason(bar);
    if (reason === null) {
      continue;
    }
    const side = sideFromReason(reason);
    if (side === null) {
      continue;
    }
    const point = series[index];
    const key = `${point.barTs}:${side}:trace`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    markers.push({
      barTs: point.barTs,
      close: point.close,
      side,
      index: point.index,
      source: "trace.target",
    });
  }

  const trades = receipt.trades;
  if (Array.isArray(trades)) {
    for (const raw of trades) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        continue;
      }
      const trade = raw as Record<string, unknown>;
      const side = sideFromTrade(trade.side ?? trade.reason);
      const ts =
        readFiniteNumber(trade.bar_ts) ?? readFiniteNumber(trade.ts_ms);
      if (side === null || ts === null) {
        continue;
      }
      const point = byTs.get(ts);
      if (point === undefined) {
        continue;
      }
      const key = `${point.barTs}:${side}:receipt`;
      if (seen.has(key) || seen.has(`${point.barTs}:${side}:trace`)) {
        continue;
      }
      seen.add(key);
      markers.push({
        barTs: point.barTs,
        close: point.close,
        side,
        index: point.index,
        source: "receipt.trades",
      });
    }
  }

  markers.sort((a, b) => a.index - b.index || a.barTs - b.barTs);
  return markers;
}

const CHART_WIDTH = 640;
const CHART_HEIGHT = 200;
const PAD_TOP = 16;
const PAD_RIGHT = 12;
const PAD_BOTTOM = 28;
const PAD_LEFT = 52;

export type PriceWithTradesChartProps = {
  series: PricePoint[] | null;
  markers: TradeMarker[];
};

/**
 * Price chart with trade markers for a research result.
 */
export function PriceWithTradesChart({
  series,
  markers,
}: PriceWithTradesChartProps): JSX.Element {
  return (
    <section
      className="kbot-research__price-trades"
      data-testid="research-price-with-trades"
      aria-label="Price with trades"
    >
      <div className="kbot-research__price-trades-head">
        <h2 className="kbot-research__price-trades-title">Price with trades</h2>
        <p className="kbot-research__price-trades-source">
          trace.input.close · markers from trace.target / receipt.trades
        </p>
      </div>
      {series === null ? (
        <p
          className="kbot-research__price-trades-empty"
          data-testid="research-price-with-trades-unavailable"
        >
          unavailable
        </p>
      ) : (
        <PriceWithTradesSvg series={series} markers={markers} />
      )}
    </section>
  );
}

function PriceWithTradesSvg({
  series,
  markers,
}: {
  series: PricePoint[];
  markers: TradeMarker[];
}): JSX.Element {
  const plotWidth = CHART_WIDTH - PAD_LEFT - PAD_RIGHT;
  const plotHeight = CHART_HEIGHT - PAD_TOP - PAD_BOTTOM;
  let min = Math.min(...series.map((point) => point.close));
  let max = Math.max(...series.map((point) => point.close));
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const range = max - min;

  const xAt = (index: number): number =>
    PAD_LEFT +
    (series.length === 1
      ? plotWidth / 2
      : (index / (series.length - 1)) * plotWidth);
  const yAt = (value: number): number =>
    PAD_TOP + ((max - value) / range) * plotHeight;

  const points = series
    .map((point) => `${xAt(point.index).toFixed(2)},${yAt(point.close).toFixed(2)}`)
    .join(" ");

  const yTicks = [max, (max + min) / 2, min];
  const buys = markers.filter((marker) => marker.side === "buy").length;
  const sells = markers.filter((marker) => marker.side === "sell").length;

  return (
    <svg
      className="kbot-research__price-trades-svg"
      data-testid="research-price-with-trades-svg"
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={`Price with trades, ${series.length} bars, ${buys} buy and ${sells} sell markers`}
    >
      <rect
        className="kbot-research__price-trades-plot"
        x={PAD_LEFT}
        y={PAD_TOP}
        width={plotWidth}
        height={plotHeight}
      />
      {yTicks.map((tick, index) => {
        const y = yAt(tick);
        return (
          <g key={`ytick-${index}`}>
            <line
              className="kbot-research__price-trades-grid"
              x1={PAD_LEFT}
              y1={y}
              x2={PAD_LEFT + plotWidth}
              y2={y}
            />
            <text
              className="kbot-research__price-trades-tick"
              x={PAD_LEFT - 8}
              y={y + 3}
              textAnchor="end"
            >
              {formatPriceTick(tick)}
            </text>
          </g>
        );
      })}
      <polyline
        className="kbot-research__price-trades-line"
        data-testid="research-price-with-trades-line"
        fill="none"
        points={points}
      />
      {markers.map((marker) => {
        const x = xAt(marker.index);
        const y = yAt(marker.close);
        const isBuy = marker.side === "buy";
        // Triangles: buy points up, sell points down — at the signal close.
        const path = isBuy
          ? `M ${x.toFixed(2)} ${(y - 6).toFixed(2)} L ${(x + 5).toFixed(2)} ${(y + 4).toFixed(2)} L ${(x - 5).toFixed(2)} ${(y + 4).toFixed(2)} Z`
          : `M ${x.toFixed(2)} ${(y + 6).toFixed(2)} L ${(x + 5).toFixed(2)} ${(y - 4).toFixed(2)} L ${(x - 5).toFixed(2)} ${(y - 4).toFixed(2)} Z`;
        return (
          <path
            key={`${marker.barTs}-${marker.side}-${marker.source}`}
            className={
              isBuy
                ? "kbot-research__price-trades-marker kbot-research__price-trades-marker--buy"
                : "kbot-research__price-trades-marker kbot-research__price-trades-marker--sell"
            }
            data-testid={`research-price-trade-marker-${marker.side}`}
            data-side={marker.side}
            data-bar-ts={String(marker.barTs)}
            d={path}
          />
        );
      })}
      <text
        className="kbot-research__price-trades-axis"
        x={PAD_LEFT + plotWidth / 2}
        y={CHART_HEIGHT - 6}
        textAnchor="middle"
      >
        bar index
      </text>
    </svg>
  );
}

function formatPriceTick(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1000) {
    return value.toFixed(0);
  }
  if (abs >= 10) {
    return value.toFixed(2);
  }
  return value.toFixed(4);
}

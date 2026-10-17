/**
 * Shared fixture generators for the NS20 e2e harness.
 *
 * The probe (``fixture_probe.py``) is the source of truth for the
 * edit.csv shape; the in-harness generator mirrors the same zig-zag
 * so a Playwright run never depends on Python. The 100k CSV uses a
 * random walk so the trace has visible variation and the backtest
 * does not accumulate large cash positions that trigger an engine
 * ``Decimal`` precision ceiling (the engine code is not in scope for
 * NS20 edits; the brief forbids touching ``src/krellbot/``).
 */

import { writeFileSync } from "node:fs";

export type CsvSpec = {
  rows: number;
  baseTsMs?: number;
  tfMs?: number;
};

const HEADER = ["ts_ms", "open", "high", "low", "close", "volume"] as const;

export function createCsv(path: string, spec: CsvSpec): void {
  const { rows } = spec;
  const baseTsMs = spec.baseTsMs ?? 1_700_000_000_000;
  const tfMs = spec.tfMs ?? 3_600_000;
  const lines: string[] = [HEADER.join(",")];
  if (rows <= 1000) {
    // Match the Python probe: deterministic zig-zag so the small
    // edit.csv stays identical between the probe and the harness.
    for (let index = 0; index < rows; index += 1) {
      const tsMs = baseTsMs + index * tfMs;
      const slow = 12 * Math.sin(index / 18);
      const zig = index % 2 === 0 ? 1.5 : -1.5;
      const close = 100 + slow + zig;
      const open = close - 0.5;
      const high = Math.max(open, close) + 0.25;
      const low = Math.min(open, close) - 0.25;
      lines.push(
        `${tsMs},${open.toFixed(4)},${high.toFixed(4)},${low.toFixed(4)},${close.toFixed(4)},1`,
      );
    }
  } else {
    // Use a seeded PRNG so the 100k CSV is byte-identical across runs.
    const rng = mulberry32(0x4e5ee2d3);
    let close = 100;
    for (let index = 0; index < rows; index += 1) {
      const tsMs = baseTsMs + index * tfMs;
      // Random walk so the SMA(2) cross count stays modest; zig-zag
      // (used by the Python probe and small fixtures) is fine for the
      // 400-row edit fixture but produces too many trades at 100k.
      close = clamp(close + gauss(rng, 0, 0.5), 50, 200);
      const open = close + gauss(rng, 0, 0.05);
      const high = Math.max(open, close) + Math.abs(gauss(rng, 0, 0.1));
      const low = Math.min(open, close) - Math.abs(gauss(rng, 0, 0.1));
      const volume = Math.max(1, gauss(rng, 50, 10));
      lines.push(
        `${tsMs},${open.toFixed(4)},${high.toFixed(4)},${low.toFixed(4)},${close.toFixed(4)},${volume.toFixed(4)}`,
      );
    }
  }
  const body = lines.join("\n") + "\n";
  writeFileSync(path, body, "utf8");
}

function clamp(value: number, lo: number, hi: number): number {
  return value < lo ? lo : value > hi ? hi : value;
}

function gauss(rng: () => number, mean: number, std: number): number {
  // Box-Muller transform.
  const u1 = rng();
  const u2 = rng();
  const z = Math.sqrt(-2 * Math.log(u1 || 1e-9)) * Math.cos(2 * Math.PI * u2);
  return mean + std * z;
}

function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return (): number => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
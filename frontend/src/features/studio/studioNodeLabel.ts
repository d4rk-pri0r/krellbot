/**
 * Human-readable Studio graph node labels.
 *
 * Pack node ids are machine keys (`pack`, `entry`, `sma2`, `n0`). The
 * default canvas used to paint those raw ids; this helper turns them into
 * prose the operator can scan without decoding the key.
 */

const ROLE_LABELS: Readonly<Record<string, string>> = {
  pack: "Pack",
  entry: "Entry",
  exit: "Exit",
};

const INDICATOR_PREFIXES = [
  "sma",
  "ema",
  "wma",
  "rsi",
  "atr",
  "macd",
  "bb",
  "vwap",
] as const;

/**
 * Map a Studio node id to a short human-readable label for the canvas.
 * Unknown ids are title-cased with digit boundaries preserved
 * (`sma2` → `SMA 2`, `ema_fast` → `EMA fast`).
 */
export function studioNodeLabel(id: string): string {
  if (typeof id !== "string" || id.trim() === "") {
    return "Node";
  }
  const key = id.trim();
  const role = ROLE_LABELS[key];
  if (role !== undefined) {
    return role;
  }
  if (/^n\d+$/i.test(key)) {
    return `Demo ${key.slice(1)}`;
  }
  if (/^w\d+$/i.test(key)) {
    return `Sample ${key.slice(1)}`;
  }
  return humanizeToken(key);
}

function humanizeToken(raw: string): string {
  const spaced = raw
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/([A-Za-z])(\d)/g, "$1 $2")
    .replace(/(\d)([A-Za-z])/g, "$1 $2")
    .trim();
  if (spaced === "") {
    return "Node";
  }
  return spaced
    .split(/\s+/)
    .map((part) => formatPart(part))
    .join(" ");
}

function formatPart(part: string): string {
  const lower = part.toLowerCase();
  if ((INDICATOR_PREFIXES as readonly string[]).includes(lower)) {
    return lower.toUpperCase();
  }
  if (/^\d+$/.test(part)) {
    return part;
  }
  if (part.length <= 3 && part === part.toUpperCase()) {
    return part;
  }
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

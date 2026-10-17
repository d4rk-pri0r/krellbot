export type PromotionPack = Record<string, unknown>;

export const PROMOTION_FIELDS: readonly string[] = [
  "schema_version",
  "id",
  "timeframe",
  "indicators",
  "entry",
  "exit",
  "risk",
  "markets",
];

function hasOwn(obj: PromotionPack, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function canonicalize(value: unknown): string {
  if (value === null) {
    return "null";
  }
  if (value === undefined) {
    return "undef";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    if (Number.isNaN(value)) {
      return "nan";
    }
    if (!Number.isFinite(value)) {
      return value > 0 ? "+inf" : "-inf";
    }
    return `n:${value}`;
  }
  if (typeof value === "string") {
    return `s:${value}`;
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalize(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort();
    return `{${keys
      .map((k) => `${JSON.stringify(k)}:${canonicalize(obj[k])}`)
      .join(",")}}`;
  }
  return "unknown";
}

export function promotionPin(pack: PromotionPack): string {
  const parts: string[] = [];
  for (const field of PROMOTION_FIELDS) {
    if (hasOwn(pack, field)) {
      parts.push(`${field}:p:${canonicalize(pack[field])}`);
    } else {
      parts.push(`${field}:a`);
    }
  }
  return parts.join("|");
}

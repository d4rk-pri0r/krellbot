export type StatefulFn = "ema" | "atr" | "roofing_filter";

export type ObserveNodeInput = {
  fn?: string | null;
  bar_index?: number | null;
  checkpoint?: unknown;
};

export type ObserveUnavailable =
  | { available: false; reason: "bar missing" }
  | { available: false; reason: "future bar" }
  | { available: false; reason: "checkpoint missing"; checkpoint: "missing" };

export type ObserveAvailable = {
  available: true;
  checkpoint: "present";
};

export type ObserveResult = ObserveUnavailable | ObserveAvailable;

const STATEFUL_FN_SET: ReadonlySet<string> = new Set<StatefulFn>([
  "ema",
  "atr",
  "roofing_filter",
]);

function isStatefulFn(fn: unknown): fn is StatefulFn {
  return typeof fn === "string" && STATEFUL_FN_SET.has(fn);
}

function isDictCheckpoint(checkpoint: unknown): boolean {
  return (
    typeof checkpoint === "object" &&
    checkpoint !== null &&
    !Array.isArray(checkpoint)
  );
}

export function observeNode(
  node: ObserveNodeInput,
  decisionBar: number,
): ObserveResult {
  if (typeof node.bar_index !== "number" || !Number.isInteger(node.bar_index)) {
    return { available: false, reason: "bar missing" };
  }
  if (node.bar_index > decisionBar) {
    return { available: false, reason: "future bar" };
  }
  if (isStatefulFn(node.fn) && !isDictCheckpoint(node.checkpoint)) {
    return {
      available: false,
      reason: "checkpoint missing",
      checkpoint: "missing",
    };
  }
  return { available: true, checkpoint: "present" };
}

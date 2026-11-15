/**
 * Studio graph ↔ pack DSL conversion and mutators (M6.3).
 *
 * The canvas projects a pack into nodes via ``nodesFromPack``. These
 * helpers are the reverse path: add / connect / delete update a pack so
 * Save execution can PUT validating IR/JSON. Editor layout chrome is
 * never written into the pack body.
 */

import type { StudioEdge } from "./packNodes";

const PRICE_FIELDS = new Set(["open", "high", "low", "close", "volume"]);
const ROLE_NODES = new Set(["pack", "entry", "exit"]);
const MAX_CONDITION_DEPTH = 3;
const INDICATOR_NAME_PATTERN = /^[a-z][a-z0-9_]*$/;

export type PackGraphIndicator = {
  fn: string;
  src?: string;
  len: number;
  [key: string]: unknown;
};

export type PackFromGraphInput = {
  /** Pack metadata, risk, markets, and any fields other than the graph. */
  base: Record<string, unknown>;
  /** Indicator map that will become ``pack.indicators``. */
  indicators: Record<string, PackGraphIndicator>;
  /**
   * Graph edges that encode DSL wiring. An edge from an indicator id to
   * ``entry`` or ``exit`` places that indicator into the corresponding
   * condition leaf (``close`` vs indicator).
   */
  edges: ReadonlyArray<StudioEdge>;
};

export type PackGraphRefusal =
  | "pack required"
  | "indicator required"
  | "last indicator"
  | "role node"
  | "unknown node"
  | "depth exceeded"
  | "invalid target";

export type PackGraphResult =
  | { ok: true; pack: Record<string, unknown> }
  | { ok: false; reason: PackGraphRefusal };

const DEFAULT_INDICATOR: PackGraphIndicator = {
  fn: "sma",
  src: "close",
  len: 20,
};

function clonePack(pack: Record<string, unknown>): Record<string, unknown> {
  return structuredClone(pack);
}

function indicatorMap(
  pack: Record<string, unknown>,
): Record<string, PackGraphIndicator> {
  const raw = pack.indicators;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  const out: Record<string, PackGraphIndicator> = {};
  for (const [name, spec] of Object.entries(raw as Record<string, unknown>)) {
    if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
      continue;
    }
    const row = spec as Record<string, unknown>;
    const fn = typeof row.fn === "string" ? row.fn : "sma";
    const len = typeof row.len === "number" ? row.len : 20;
    const next: PackGraphIndicator = { fn, len };
    if (typeof row.src === "string") {
      next.src = row.src;
    }
    for (const [key, value] of Object.entries(row)) {
      if (key === "fn" || key === "src" || key === "len") {
        continue;
      }
      next[key] = value;
    }
    out[name] = next;
  }
  return out;
}

function isLeaf(condition: unknown): condition is [unknown, string, unknown] {
  return Array.isArray(condition) && condition.length === 3;
}

function conditionDepth(condition: unknown): number {
  if (isLeaf(condition)) {
    return 1;
  }
  if (condition && typeof condition === "object" && !Array.isArray(condition)) {
    const row = condition as Record<string, unknown>;
    const children = [
      ...(Array.isArray(row.all) ? row.all : []),
      ...(Array.isArray(row.any) ? row.any : []),
    ];
    if (children.length === 0) {
      return 1;
    }
    return 1 + Math.max(...children.map(conditionDepth));
  }
  return 0;
}

function walkIndicatorOperands(condition: unknown, into: Set<string>): void {
  if (isLeaf(condition)) {
    for (const index of [0, 2] as const) {
      const operand = condition[index];
      if (typeof operand === "string" && !PRICE_FIELDS.has(operand)) {
        into.add(operand);
      }
    }
    return;
  }
  if (condition && typeof condition === "object" && !Array.isArray(condition)) {
    const row = condition as Record<string, unknown>;
    for (const key of ["all", "any"] as const) {
      const children = row[key];
      if (!Array.isArray(children)) {
        continue;
      }
      for (const child of children) {
        walkIndicatorOperands(child, into);
      }
    }
  }
}

function referencedIndicators(pack: Record<string, unknown>): Set<string> {
  const used = new Set<string>();
  walkIndicatorOperands(pack.entry, used);
  walkIndicatorOperands(pack.exit, used);
  return used;
}

function leafFor(side: "entry" | "exit", indicator: string): [string, string, string] {
  return side === "entry"
    ? ["close", ">", indicator]
    : ["close", "<", indicator];
}

function conditionAlreadyReferences(
  condition: unknown,
  indicator: string,
): boolean {
  const used = new Set<string>();
  walkIndicatorOperands(condition, used);
  return used.has(indicator);
}

/**
 * Attach ``indicator`` to ``entry`` or ``exit`` without exceeding nesting
 * depth 3. Leaves that already reference the indicator are left alone.
 */
function wireIndicator(
  condition: unknown,
  side: "entry" | "exit",
  indicator: string,
): { ok: true; condition: unknown } | { ok: false; reason: PackGraphRefusal } {
  if (conditionAlreadyReferences(condition, indicator)) {
    return { ok: true, condition };
  }
  const leaf = leafFor(side, indicator);
  if (condition === undefined || condition === null) {
    return { ok: true, condition: leaf };
  }
  if (isLeaf(condition)) {
    const next = { all: [condition, leaf] };
    if (conditionDepth(next) > MAX_CONDITION_DEPTH) {
      return { ok: false, reason: "depth exceeded" };
    }
    return { ok: true, condition: next };
  }
  if (condition && typeof condition === "object" && !Array.isArray(condition)) {
    const row = condition as Record<string, unknown>;
    if (Array.isArray(row.all)) {
      const next = { all: [...row.all, leaf] };
      if (conditionDepth(next) > MAX_CONDITION_DEPTH) {
        return { ok: false, reason: "depth exceeded" };
      }
      return { ok: true, condition: next };
    }
    if (Array.isArray(row.any)) {
      // Preserve existing any-group by wrapping once in all.
      const next = { all: [condition, leaf] };
      if (conditionDepth(next) > MAX_CONDITION_DEPTH) {
        return { ok: false, reason: "depth exceeded" };
      }
      return { ok: true, condition: next };
    }
  }
  return { ok: true, condition: leaf };
}

function scrubIndicator(condition: unknown, indicator: string): unknown | undefined {
  if (isLeaf(condition)) {
    const [left, , right] = condition;
    if (left === indicator || right === indicator) {
      return undefined;
    }
    return condition;
  }
  if (condition && typeof condition === "object" && !Array.isArray(condition)) {
    const row = condition as Record<string, unknown>;
    if (Array.isArray(row.all)) {
      const next = row.all
        .map((child) => scrubIndicator(child, indicator))
        .filter((child) => child !== undefined);
      if (next.length === 0) {
        return undefined;
      }
      if (next.length === 1) {
        return next[0];
      }
      return { all: next };
    }
    if (Array.isArray(row.any)) {
      const next = row.any
        .map((child) => scrubIndicator(child, indicator))
        .filter((child) => child !== undefined);
      if (next.length === 0) {
        return undefined;
      }
      if (next.length === 1) {
        return next[0];
      }
      return { any: next };
    }
  }
  return condition;
}

function ensureSideHasIndicator(
  condition: unknown | undefined,
  side: "entry" | "exit",
  fallback: string,
): unknown {
  if (condition !== undefined) {
    return condition;
  }
  return leafFor(side, fallback);
}

function nextIndicatorName(
  existing: Record<string, PackGraphIndicator>,
  prefix = "sma",
): string {
  let index = Object.keys(existing).length + 1;
  while (true) {
    const candidate = `${prefix}${index}`;
    if (INDICATOR_NAME_PATTERN.test(candidate) && !(candidate in existing)) {
      return candidate;
    }
    index += 1;
  }
}

/**
 * Build a pack body from graph-authored indicators and wiring edges.
 * Preserves ``base`` metadata (id, risk, markets, …). Entry/exit ops
 * default to close-versus-indicator leaves; multiple edges to the same
 * side nest under ``{all: [...]}``.
 */
export function packFromGraph(input: PackFromGraphInput): Record<string, unknown> {
  const names = Object.keys(input.indicators);
  if (names.length === 0) {
    throw new Error("packFromGraph requires at least one indicator");
  }
  const entryNames: string[] = [];
  const exitNames: string[] = [];
  for (const edge of input.edges) {
    if (!(edge.source in input.indicators)) {
      continue;
    }
    if (edge.target === "entry" && !entryNames.includes(edge.source)) {
      entryNames.push(edge.source);
    }
    if (edge.target === "exit" && !exitNames.includes(edge.source)) {
      exitNames.push(edge.source);
    }
  }
  // Lint forbids unused indicators: any indicator missing a side edge
  // is wired to entry so the emitted pack stays check()-clean.
  for (const name of names) {
    if (!entryNames.includes(name) && !exitNames.includes(name)) {
      entryNames.push(name);
    }
  }
  if (entryNames.length === 0) {
    entryNames.push(names[0]!);
  }
  if (exitNames.length === 0) {
    exitNames.push(names[0]!);
  }

  const toCondition = (
    side: "entry" | "exit",
    ids: ReadonlyArray<string>,
  ): unknown => {
    const leaves = ids.map((id) => leafFor(side, id));
    return leaves.length === 1 ? leaves[0]! : { all: leaves };
  };

  const { indicators: _drop, entry: _e, exit: _x, editor: _ed, ...rest } =
    input.base;
  return {
    ...rest,
    indicators: structuredClone(input.indicators),
    entry: toCondition("entry", entryNames),
    exit: toCondition("exit", exitNames),
  };
}

/**
 * Derive canvas edges from pack entry/exit indicator operands so the
 * graph shows DSL wiring without requiring a saved editor meta blob.
 */
export function edgesFromPack(pack: Record<string, unknown>): StudioEdge[] {
  const edges: StudioEdge[] = [];
  const seen = new Set<string>();
  const push = (source: string, target: string): void => {
    const key = `${source}\0${target}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    edges.push({ source, target });
  };
  const entryRefs = new Set<string>();
  const exitRefs = new Set<string>();
  walkIndicatorOperands(pack.entry, entryRefs);
  walkIndicatorOperands(pack.exit, exitRefs);
  for (const name of entryRefs) {
    push(name, "entry");
  }
  for (const name of exitRefs) {
    push(name, "exit");
  }
  return edges;
}

/** Add a default SMA indicator and wire it into entry so lint stays clean. */
export function addIndicatorNode(
  pack: Record<string, unknown>,
  options?: Partial<PackGraphIndicator> & { name?: string },
): PackGraphResult & { nodeId?: string } {
  if (!pack || typeof pack !== "object") {
    return { ok: false, reason: "pack required" };
  }
  const indicators = indicatorMap(pack);
  const name =
    typeof options?.name === "string" &&
    INDICATOR_NAME_PATTERN.test(options.name) &&
    !(options.name in indicators)
      ? options.name
      : nextIndicatorName(indicators);
  const spec: PackGraphIndicator = {
    ...DEFAULT_INDICATOR,
    ...options,
    fn: options?.fn ?? DEFAULT_INDICATOR.fn,
    src: options?.src ?? DEFAULT_INDICATOR.src,
    len: options?.len ?? DEFAULT_INDICATOR.len,
  };
  delete (spec as { name?: string }).name;

  const next = clonePack(pack);
  const nextIndicators = { ...indicators, [name]: spec };
  next.indicators = nextIndicators;

  const wired = wireIndicator(next.entry, "entry", name);
  if (!wired.ok) {
    return wired;
  }
  next.entry = wired.condition;
  return { ok: true, pack: next, nodeId: name };
}

/**
 * Connect an indicator node into entry/exit (pack DSL). Other endpoint
 * pairs are a no-op on the pack (visual-only) and return the input pack.
 */
export function connectPackNodes(
  pack: Record<string, unknown>,
  source: string,
  target: string,
): PackGraphResult {
  if (!pack || typeof pack !== "object") {
    return { ok: false, reason: "pack required" };
  }
  const indicators = indicatorMap(pack);
  if (!(source in indicators)) {
    // Non-indicator sources (pack/entry/demo) keep current visual-only edges.
    return { ok: true, pack };
  }
  if (target !== "entry" && target !== "exit") {
    return { ok: true, pack };
  }
  if (conditionAlreadyReferences(pack[target], source)) {
    return { ok: true, pack };
  }
  const next = clonePack(pack);
  const wired = wireIndicator(next[target], target, source);
  if (!wired.ok) {
    return wired;
  }
  next[target] = wired.condition;
  return { ok: true, pack: next };
}

/**
 * Delete an indicator node and scrub it from entry/exit. Role nodes and
 * the last remaining indicator are refused so the pack stays schema-legal.
 */
export function deletePackNode(
  pack: Record<string, unknown>,
  nodeId: string,
): PackGraphResult {
  if (!pack || typeof pack !== "object") {
    return { ok: false, reason: "pack required" };
  }
  if (ROLE_NODES.has(nodeId)) {
    return { ok: false, reason: "role node" };
  }
  const indicators = indicatorMap(pack);
  if (!(nodeId in indicators)) {
    return { ok: false, reason: "unknown node" };
  }
  const remainingNames = Object.keys(indicators).filter((name) => name !== nodeId);
  if (remainingNames.length === 0) {
    return { ok: false, reason: "last indicator" };
  }
  const fallback = remainingNames[0]!;
  const nextIndicators = { ...indicators };
  delete nextIndicators[nodeId];

  const next = clonePack(pack);
  next.indicators = nextIndicators;
  let entry = scrubIndicator(next.entry, nodeId);
  let exit = scrubIndicator(next.exit, nodeId);
  entry = ensureSideHasIndicator(entry, "entry", fallback);
  exit = ensureSideHasIndicator(exit, "exit", fallback);
  // Re-home any indicator that scrubbing left unreferenced.
  next.entry = entry;
  next.exit = exit;
  const used = referencedIndicators(next);
  for (const name of remainingNames) {
    if (used.has(name)) {
      continue;
    }
    const wired = wireIndicator(next.entry, "entry", name);
    if (!wired.ok) {
      return wired;
    }
    next.entry = wired.condition;
    used.add(name);
  }
  return { ok: true, pack: next };
}

export function isIndicatorNodeId(
  pack: Record<string, unknown>,
  nodeId: string | null | undefined,
): boolean {
  if (typeof nodeId !== "string" || nodeId === "") {
    return false;
  }
  return nodeId in indicatorMap(pack);
}

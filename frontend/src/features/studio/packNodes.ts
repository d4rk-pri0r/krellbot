import type { GraphCanvasNode } from "./GraphCanvas";

export type LayoutPoint = {
  x: number;
  y: number;
};

export type StudioEditor = {
  layout?: Record<string, LayoutPoint>;
};

export function nodesFromPack(
  pack: Record<string, unknown>,
  editor?: StudioEditor | null,
): GraphCanvasNode[] {
  const layout = editor?.layout ?? {};
  const timeframe = typeof pack.timeframe === "string" ? pack.timeframe : "1h";
  const specs: Array<{ id: string }> = [];
  if (typeof pack.id === "string" && pack.id !== "") {
    specs.push({ id: "pack" });
  }
  const indicators = pack.indicators;
  if (indicators && typeof indicators === "object" && !Array.isArray(indicators)) {
    for (const name of Object.keys(indicators)) {
      specs.push({ id: name });
    }
  }
  if (pack.entry !== undefined) {
    specs.push({ id: "entry" });
  }
  if (pack.exit !== undefined) {
    specs.push({ id: "exit" });
  }
  return specs.map((spec, index) => {
    const placed = layout[spec.id];
    return {
      id: spec.id,
      type: "default",
      position: placed ?? { x: index * 180, y: 0 },
      data: { timeframe },
    };
  });
}

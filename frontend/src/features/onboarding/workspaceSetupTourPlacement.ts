/**
 * Viewport placement for the setup-tour callout (KRELL-SIGNAL-20261010).
 *
 * The card stays fully inside the viewport and off the target. A side
 * that would have to be clamped on top of the control is discarded in
 * favor of a corner that leaves the control readable.
 */

export const SETUP_TOUR_MARGIN = 12;
const TARGET_GAP = 18;

export type Box = {
  top: number;
  left: number;
  width: number;
  height: number;
};

export type Viewport = {
  width: number;
  height: number;
};

export type ArrowLine = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export type SetupTourPlacement = {
  card: { top: number; left: number; width: number; height: number };
  spotlight: Box | null;
  arrow: ArrowLine | null;
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function intersects(a: Box, b: Box): boolean {
  return (
    a.left < b.left + b.width &&
    a.left + a.width > b.left &&
    a.top < b.top + b.height &&
    a.top + a.height > b.top
  );
}

function expand(box: Box, pad: number): Box {
  return {
    top: box.top - pad,
    left: box.left - pad,
    width: box.width + pad * 2,
    height: box.height + pad * 2,
  };
}

function center(box: Box): { x: number; y: number } {
  return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
}

function edgePoint(
  box: Box,
  towardX: number,
  towardY: number,
): { x: number; y: number } {
  const cx = box.left + box.width / 2;
  const cy = box.top + box.height / 2;
  const dx = towardX - cx;
  const dy = towardY - cy;
  if (dx === 0 && dy === 0) {
    return { x: cx, y: cy };
  }
  const sx =
    dx === 0
      ? Number.POSITIVE_INFINITY
      : ((dx > 0 ? box.left + box.width : box.left) - cx) / dx;
  const sy =
    dy === 0
      ? Number.POSITIVE_INFINITY
      : ((dy > 0 ? box.top + box.height : box.top) - cy) / dy;
  const scale = Math.min(sx, sy);
  return { x: cx + dx * scale, y: cy + dy * scale };
}

function arrowBetween(card: Box, target: Box): ArrowLine {
  const from = center(card);
  const to = center(target);
  const start = edgePoint(card, to.x, to.y);
  const end = edgePoint(target, from.x, from.y);
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length = Math.hypot(dx, dy) || 1;
  const pull = Math.min(14, length / 3);
  return {
    x1: start.x,
    y1: start.y,
    x2: end.x - (dx / length) * pull,
    y2: end.y - (dy / length) * pull,
  };
}

function usableTarget(target: Box | null): target is Box {
  return target !== null && target.width > 2 && target.height > 2;
}

/**
 * Place the callout beside the target when that side fits, otherwise
 * in the free corner. Card and arrow coordinates stay inside the viewport.
 */
export function placeSetupTourCallout(input: {
  viewport: Viewport;
  target: Box | null;
  card: { width: number; height: number };
  avoid?: Box[];
}): SetupTourPlacement {
  const margin = SETUP_TOUR_MARGIN;
  const { viewport, avoid = [] } = input;
  const cardW = Math.min(
    input.card.width,
    Math.max(160, viewport.width - margin * 2),
  );
  const cardH = Math.min(
    input.card.height,
    Math.max(96, viewport.height - margin * 2),
  );
  const clampCard = (top: number, left: number): { top: number; left: number } => ({
    top: clamp(top, margin, Math.max(margin, viewport.height - cardH - margin)),
    left: clamp(left, margin, Math.max(margin, viewport.width - cardW - margin)),
  });
  const cardBox = (pos: { top: number; left: number }): Box => ({
    top: pos.top,
    left: pos.left,
    width: cardW,
    height: cardH,
  });
  const target = usableTarget(input.target) ? input.target : null;
  const spotlight = target
    ? {
        top: target.top - 4,
        left: target.left - 4,
        width: target.width + 8,
        height: target.height + 8,
      }
    : null;
  const guarded = target ? expand(target, 8) : null;

  const bottomCenter = clampCard(
    viewport.height - cardH - margin,
    (viewport.width - cardW) / 2,
  );
  if (!target || !guarded) {
    return { card: cardBox(bottomCenter), spotlight: null, arrow: null };
  }

  const alignedLeft = target.left + target.width / 2 - cardW / 2;
  const alignedTop = target.top + target.height / 2 - cardH / 2;
  const raw: Array<{ top: number; left: number }> = [
    { top: target.top + target.height + TARGET_GAP, left: alignedLeft },
    { top: target.top - TARGET_GAP - cardH, left: alignedLeft },
    { top: alignedTop, left: target.left + target.width + TARGET_GAP },
    { top: alignedTop, left: target.left - TARGET_GAP - cardW },
    { top: viewport.height - cardH - margin, left: margin },
    {
      top: viewport.height - cardH - margin,
      left: viewport.width - cardW - margin,
    },
    { top: viewport.height - cardH - margin, left: alignedLeft },
    { top: margin, left: margin },
    { top: margin, left: viewport.width - cardW - margin },
    { top: margin, left: alignedLeft },
  ];
  for (const block of avoid) {
    raw.push({
      top: block.top - TARGET_GAP - cardH,
      left: alignedLeft,
    });
    raw.push({
      top: block.top - TARGET_GAP - cardH,
      left: (viewport.width - cardW) / 2,
    });
  }

  const targetCenter = center(target);
  let best: Box | null = null;
  let bestScore = Number.POSITIVE_INFINITY;
  for (const candidate of raw) {
    const box = cardBox(clampCard(candidate.top, candidate.left));
    let hits = 0;
    if (intersects(box, guarded)) {
      hits += 5;
    }
    for (const block of avoid) {
      if (block.width > 2 && block.height > 2 && intersects(box, expand(block, 10))) {
        hits += 1;
      }
    }
    const cardCenter = center(box);
    const distance = Math.hypot(
      cardCenter.x - targetCenter.x,
      cardCenter.y - targetCenter.y,
    );
    const score = hits * 5000 + distance;
    if (score < bestScore) {
      best = box;
      bestScore = score;
    }
  }

  const placed = best ?? cardBox(bottomCenter);
  const rawArrow = arrowBetween(placed, target);
  const limit = (value: number, max: number): number =>
    clamp(value, 2, Math.max(2, max - 2));
  return {
    card: placed,
    spotlight,
    arrow: {
      x1: limit(rawArrow.x1, viewport.width),
      y1: limit(rawArrow.y1, viewport.height),
      x2: limit(rawArrow.x2, viewport.width),
      y2: limit(rawArrow.y2, viewport.height),
    },
  };
}

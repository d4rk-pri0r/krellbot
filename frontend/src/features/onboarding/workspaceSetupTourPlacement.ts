/**
 * Viewport placement for the setup-tour callout (KRELL-SIGNAL-20261010).
 *
 * The card sits 20px off the target — beside a right-rail field, under a
 * wide control, or to the right of a left-side card. It is never parked
 * at the far edge of the viewport, which stretched the arrow across the
 * page. A corner is used only when no adjacent side fits.
 */

export const SETUP_TOUR_MARGIN = 12;
const TARGET_GAP = 20;

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

function hitsAny(box: Box, regions: Box[], pad: number): boolean {
  return regions.some(
    (region) =>
      region.width > 2 &&
      region.height > 2 &&
      intersects(box, expand(region, pad)),
  );
}

/**
 * Place the callout snug against the target. `blocked` sides are rejected
 * (nav, the paper CTA, the sticky header). `avoid` only breaks ties.
 */
export function placeSetupTourCallout(input: {
  viewport: Viewport;
  target: Box | null;
  card: { width: number; height: number };
  blocked?: Box[];
  avoid?: Box[];
}): SetupTourPlacement {
  const margin = SETUP_TOUR_MARGIN;
  const { viewport, blocked = [], avoid = [] } = input;
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
  const bottomCenter = clampCard(
    viewport.height - cardH - margin,
    (viewport.width - cardW) / 2,
  );
  if (!target) {
    return { card: cardBox(bottomCenter), spotlight: null, arrow: null };
  }

  const alignedLeft = target.left + target.width / 2 - cardW / 2;
  const alignedTop = target.top + target.height / 2 - cardH / 2;
  const adjacent: Array<{ top: number; left: number }> = [
    { top: target.top + target.height + TARGET_GAP, left: alignedLeft },
    { top: target.top - TARGET_GAP - cardH, left: alignedLeft },
    { top: alignedTop, left: target.left + target.width + TARGET_GAP },
    { top: alignedTop, left: target.left - TARGET_GAP - cardW },
  ];

  const tryPlace = (raw: { top: number; left: number }): Box | null => {
    let pos = clampCard(raw.top, raw.left);
    let box = cardBox(pos);
    for (let pass = 0; pass < 3; pass += 1) {
      const block = blocked.find(
        (region) =>
          region.width > 2 &&
          region.height > 2 &&
          intersects(box, expand(region, 4)),
      );
      if (!block) {
        break;
      }
      // Only slide down off a bar that sits above the target (the sticky
      // header). A control below the target, such as Open paper run,
      // rejects this side instead of lengthening the arrow through it.
      const blockMid = block.top + block.height / 2;
      const belowBlock = block.top + block.height + 8;
      if (
        blockMid < target.top &&
        belowBlock + cardH <= viewport.height - margin &&
        belowBlock > pos.top
      ) {
        pos = clampCard(belowBlock, pos.left);
        box = cardBox(pos);
        continue;
      }
      return null;
    }
    if (intersects(box, expand(target, 6))) {
      return null;
    }
    if (hitsAny(box, blocked, 4)) {
      return null;
    }
    if (
      box.top < margin - 1 ||
      box.left < margin - 1 ||
      box.top + box.height > viewport.height - margin + 1 ||
      box.left + box.width > viewport.width - margin + 1
    ) {
      return null;
    }
    return box;
  };

  const narrow = viewport.width <= 720;
  const wideTarget = target.width >= viewport.width * 0.42;
  const onRight = target.left + target.width / 2 >= viewport.width * 0.62;
  const order = narrow || wideTarget ? [0, 1, 2, 3] : onRight ? [3, 0, 1, 2] : [2, 0, 3, 1];
  const feasible = order
    .map((index) => tryPlace(adjacent[index]!))
    .filter((box): box is Box => box !== null);
  const preferClean = !narrow && !wideTarget;
  const clean = preferClean
    ? feasible.find((box) => !hitsAny(box, avoid, 8))
    : undefined;
  const placed = clean ?? feasible[0] ?? cardBox(bottomCenter);
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

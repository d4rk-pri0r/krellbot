/**
 * Consumer-facing titles and plain-English blurbs for the home starter
 * chooser (M25.5). Keeps catalogue pack bytes unchanged; presentation only.
 *
 * Titles match the plan verbatim. Each description is ≤20 words and avoids
 * JSON/seed jargon, venue pair codes, and glued Educational-name typos.
 */

export type ConsumerStarterCard = {
  id: string;
  title: string;
  description: string;
};

/** Stable order for the three home cards. */
export const CONSUMER_STARTER_CARD_ORDER: ReadonlyArray<string> = [
  "starter-dual-ma-crossover",
  "starter-mean-reversion-band",
  "starter-range-breakout",
];

export const CONSUMER_STARTER_CARDS: Readonly<
  Record<string, ConsumerStarterCard>
> = {
  "starter-dual-ma-crossover": {
    id: "starter-dual-ma-crossover",
    title: "Dual moving average",
    description:
      "Buys when a short average rises above a long one; sells when it falls back below.",
  },
  "starter-mean-reversion-band": {
    id: "starter-mean-reversion-band",
    title: "Mean reversion",
    description:
      "Buys when price dips below its recent average and sells when it returns.",
  },
  "starter-range-breakout": {
    id: "starter-range-breakout",
    title: "Range breakout",
    description:
      "Buys when price pushes above a recent high range and exits if it fades.",
  },
};

const EDUCATIONAL_SUFFIX = /\s*\(educational example\)\s*$/i;
const EDUCATIONAL_PREFIX = /^Educational example\.\s*/i;

/**
 * Strip educational-example suffixes/prefixes without gluing the leftover
 * name into an Educational typo (never concatenate "Educational").
 */
export function plainStarterLabel(raw: string): string {
  return raw.replace(EDUCATIONAL_SUFFIX, "").trim();
}

export function plainStarterDescription(raw: string): string {
  return raw.replace(EDUCATIONAL_PREFIX, "").trim();
}

export function wordCount(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) {
    return 0;
  }
  return trimmed.split(/\s+/).length;
}

export function consumerCardForExample(example: {
  id: string;
  label: string;
  description: string;
}): ConsumerStarterCard {
  const known = CONSUMER_STARTER_CARDS[example.id];
  if (known) {
    return known;
  }
  return {
    id: example.id,
    title: plainStarterLabel(example.label),
    description: plainStarterDescription(example.description),
  };
}

/**
 * Consumer chooser shows the three known cards in plan order when present
 * in the catalogue; never invents rows that the catalogue omitted.
 */
export function orderConsumerStarterExamples<T extends { id: string }>(
  examples: ReadonlyArray<T>,
): T[] {
  const byId = new Map(examples.map((example) => [example.id, example]));
  const ordered: T[] = [];
  for (const id of CONSUMER_STARTER_CARD_ORDER) {
    const row = byId.get(id);
    if (row) {
      ordered.push(row);
    }
  }
  return ordered;
}

/**
 * Launch pack family honesty copy (M21.2) — single Paid 1.0 family (DCA).
 * Mirrors `krellbot.packs.launch_family` / docs/launch-pack-family.md.
 * Contract: KRELL-SIGNAL-20261010.
 */

export const LAUNCH_PACK_FAMILY_SKU = "paid-launch-dca";

export const LAUNCH_PACK_FAMILY_LABEL = "DCA mode pack family";

/** Helper copy shown on the signed catalogue when the launch SKU is present. */
export const LAUNCH_PACK_FAMILY_HONESTY =
  "Launch pack family (DCA): tools only — not personalized advice. Fixture and backtest results stay labeled; no returns promises. Installed bytes must match the signed catalogue pack_sha256.";

export const LAUNCH_PACK_FAMILY_REQUIRED_PHRASES = [
  "not personalized advice",
  "fixture",
  "backtest",
] as const;

const RETURNS_PROMISE_PATTERNS: RegExp[] = [
  /guaranteed\s+returns?/i,
  /guaranteed\s+profit/i,
  /profit\s+guaranteed/i,
  /will\s+profit/i,
  /promised?\s+returns?/i,
  /risk[- ]free\s+returns?/i,
  /\bdouble\s+your\s+money\b/i,
  /\bget\s+rich\b/i,
];

export function isLaunchPackFamilySku(id: string): boolean {
  return id === LAUNCH_PACK_FAMILY_SKU;
}

/** True when copy satisfies required honesty phrases and has no returns promises. */
export function launchPackFamilyCopyIsHonest(text: string): boolean {
  const lowered = text.toLowerCase();
  for (const phrase of LAUNCH_PACK_FAMILY_REQUIRED_PHRASES) {
    if (!lowered.includes(phrase.toLowerCase())) {
      return false;
    }
  }
  for (const pattern of RETURNS_PROMISE_PATTERNS) {
    if (pattern.test(text)) {
      return false;
    }
  }
  return true;
}

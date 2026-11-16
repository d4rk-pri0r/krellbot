/**
 * Wave Kraken BTC/USD naming (M2.4 / M6.1).
 *
 * One human display label and one stored venue symbol. Live grants and
 * paper arms match the exact (venue, pair) string, so every default,
 * picker, and seed must use the same spelling — not BTC/USD, BTCUSD,
 * XBTUSD, or XBT/USD as the stored pair.
 */

export const KRAKEN_BTC_USD_VENUE_SYMBOL = "XXBTZUSD";
export const KRAKEN_BTC_USD_DISPLAY = "BTC/USD";

export type KrakenWavePairOption = {
  readonly venueSymbol: typeof KRAKEN_BTC_USD_VENUE_SYMBOL;
  readonly display: typeof KRAKEN_BTC_USD_DISPLAY;
};

/** Constrained picker options for the BTC/USD wave (single spelling). */
export const KRAKEN_WAVE_PAIR_OPTIONS: readonly KrakenWavePairOption[] = [
  {
    venueSymbol: KRAKEN_BTC_USD_VENUE_SYMBOL,
    display: KRAKEN_BTC_USD_DISPLAY,
  },
] as const;

export function isKrakenWavePairSymbol(pair: string): boolean {
  return KRAKEN_WAVE_PAIR_OPTIONS.some((option) => option.venueSymbol === pair);
}

export function krakenWavePairLabel(pair: string): string {
  const match = KRAKEN_WAVE_PAIR_OPTIONS.find(
    (option) => option.venueSymbol === pair,
  );
  if (!match) {
    return pair;
  }
  return `${match.display} (${match.venueSymbol})`;
}

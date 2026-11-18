/**
 * Wave Coinbase BTC/USD naming (M11.2 / M23.4).
 *
 * Live grants and paper arms match the exact (venue, pair) string.
 * Coinbase Advanced uses the BASE-QUOTE product id — not BTCUSD or BTC/USD
 * as the stored pair.
 */

export const COINBASE_BTC_USD_VENUE_SYMBOL = "BTC-USD";
export const COINBASE_BTC_USD_DISPLAY = "BTC/USD";

export type CoinbaseWavePairOption = {
  readonly venueSymbol: typeof COINBASE_BTC_USD_VENUE_SYMBOL;
  readonly display: typeof COINBASE_BTC_USD_DISPLAY;
};

/** Constrained picker options for the Coinbase BTC/USD wave. */
export const COINBASE_WAVE_PAIR_OPTIONS: readonly CoinbaseWavePairOption[] = [
  {
    venueSymbol: COINBASE_BTC_USD_VENUE_SYMBOL,
    display: COINBASE_BTC_USD_DISPLAY,
  },
] as const;

export function isCoinbaseWavePairSymbol(pair: string): boolean {
  return COINBASE_WAVE_PAIR_OPTIONS.some((option) => option.venueSymbol === pair);
}

export function coinbaseWavePairLabel(pair: string): string {
  const match = COINBASE_WAVE_PAIR_OPTIONS.find(
    (option) => option.venueSymbol === pair,
  );
  if (!match) {
    return pair;
  }
  return `${match.display} (${match.venueSymbol})`;
}

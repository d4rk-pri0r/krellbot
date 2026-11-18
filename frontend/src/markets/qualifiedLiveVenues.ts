/**
 * Distribution-gate qualified live venues (M23.4).
 *
 * Matches `krellbot.application.distribution_venues.QUALIFIED_LIVE_VENUES`.
 * Binance stays paper-only; do not add it here.
 */

export const QUALIFIED_LIVE_VENUES = ["kraken", "coinbase"] as const;
export type QualifiedLiveVenue = (typeof QUALIFIED_LIVE_VENUES)[number];

export const SECOND_DISTRIBUTION_VENUE = "coinbase" as const;

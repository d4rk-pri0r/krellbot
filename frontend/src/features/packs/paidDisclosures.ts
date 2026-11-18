/**
 * Paid disclosures copy (M21.5) — Packs + Settings.
 * Mirrors docs/paid-disclosures.md. Contract: KRELL-SIGNAL-20261010.
 */

import { REFERRAL_PACKS_DISCLOSURE } from "../referral/copy";

export const PAID_DISCLOSURES_DOC_URL =
  "https://github.com/d4rkpr10r-Labs/krellbot/blob/main/docs/paid-disclosures.md";

export const PAID_DISCLOSURES_REFUNDS_URL =
  "https://github.com/d4rkpr10r-Labs/krellbot/blob/main/docs/refunds.md";

export const PAID_DISCLOSURES_TELEMETRY_URL =
  "https://github.com/d4rkpr10r-Labs/krellbot/blob/main/docs/telemetry.md";

/** Packs / Settings summary: packs are tools, not personalized advice. */
export const PAID_DISCLOSURES_NOT_ADVICE =
  "Packs are tools — not personalized advice. Fixture and backtest results stay labeled. Does not promise gains.";

/** Refund window pointer (owner-set terms at M21.6; path in docs/refunds.md). */
export const PAID_DISCLOSURES_REFUND_WINDOW =
  "Refund window: request a pack refund from Packs for a catalogue SKU. On success the local entitlement is revoked. See docs/refunds.md for the refund path and refund-window pointer.";

/** Telemetry stays opt-in; default off. */
export const PAID_DISCLOSURES_TELEMETRY_OPT_IN =
  "Telemetry is opt-in (default off). Nothing leaves the machine until the operator enables it; payloads never include keys, secrets, or strategy source.";

/** Fee share / referral line when that earn path is shown. */
export const PAID_DISCLOSURES_FEE_SHARE_REFERRAL = REFERRAL_PACKS_DISCLOSURE;

export const PAID_DISCLOSURES_TITLE = "Paid disclosures";

export const PAID_DISCLOSURES_LEDE =
  "Paid catalogue purchases stay honest: fee share / referral when shown, packs not advice, refund window pointer, telemetry opt-in.";

/** Phrases the M21.5 accept command must find in docs/ + frontend/src. */
export const PAID_DISCLOSURES_ACCEPT_PHRASES = [
  "not personalized advice",
  "refund",
  "opt-in",
  "fee share",
  "referral",
] as const;

export function paidDisclosuresCopyIsComplete(text: string): boolean {
  const lowered = text.toLowerCase();
  for (const phrase of PAID_DISCLOSURES_ACCEPT_PHRASES) {
    if (!lowered.includes(phrase.toLowerCase())) {
      return false;
    }
  }
  if (/guaranteed\s+returns?/i.test(text) || /guaranteed\s+profit/i.test(text)) {
    return false;
  }
  return true;
}

/**
 * Paid disclosures panel — Packs + Settings (M21.5).
 * Contract: KRELL-SIGNAL-20261010.
 */
import type { JSX } from "react";
import {
  PAID_DISCLOSURES_DOC_URL,
  PAID_DISCLOSURES_FEE_SHARE_REFERRAL,
  PAID_DISCLOSURES_LEDE,
  PAID_DISCLOSURES_NOT_ADVICE,
  PAID_DISCLOSURES_REFUND_WINDOW,
  PAID_DISCLOSURES_REFUNDS_URL,
  PAID_DISCLOSURES_TELEMETRY_OPT_IN,
  PAID_DISCLOSURES_TELEMETRY_URL,
  PAID_DISCLOSURES_TITLE,
} from "./paidDisclosures";
import "./PaidDisclosuresPanel.signal.css";

export type PaidDisclosuresPanelProps = {
  /** Compact Packs strip vs Settings body. */
  variant?: "packs" | "settings";
};

export function PaidDisclosuresPanel({
  variant = "settings",
}: PaidDisclosuresPanelProps): JSX.Element {
  const isPacks = variant === "packs";

  return (
    <section
      className={
        isPacks
          ? "kbot-paid-disclosures kbot-paid-disclosures--packs"
          : "kbot-paid-disclosures"
      }
      aria-labelledby="kbot-paid-disclosures-title"
      data-testid="paid-disclosures-panel"
      data-variant={variant}
    >
      <h3
        className="kbot-paid-disclosures__title"
        id="kbot-paid-disclosures-title"
      >
        {PAID_DISCLOSURES_TITLE}
      </h3>
      <p
        className="kbot-paid-disclosures__lede"
        data-testid="paid-disclosures-lede"
      >
        {PAID_DISCLOSURES_LEDE}
      </p>
      <ul
        className="kbot-paid-disclosures__list"
        data-testid="paid-disclosures-list"
      >
        <li data-testid="paid-disclosures-fee-share">
          {PAID_DISCLOSURES_FEE_SHARE_REFERRAL}
        </li>
        <li data-testid="paid-disclosures-not-advice">
          {PAID_DISCLOSURES_NOT_ADVICE}
        </li>
        <li data-testid="paid-disclosures-refund">
          {PAID_DISCLOSURES_REFUND_WINDOW}
        </li>
        <li data-testid="paid-disclosures-telemetry">
          {PAID_DISCLOSURES_TELEMETRY_OPT_IN}
        </li>
      </ul>
      <p
        className="kbot-paid-disclosures__links"
        data-testid="paid-disclosures-links"
      >
        <a href={PAID_DISCLOSURES_DOC_URL} target="_blank" rel="noreferrer">
          Paid disclosures
        </a>
        <span aria-hidden="true"> · </span>
        <a href={PAID_DISCLOSURES_REFUNDS_URL} target="_blank" rel="noreferrer">
          Refund window
        </a>
        <span aria-hidden="true"> · </span>
        <a
          href={PAID_DISCLOSURES_TELEMETRY_URL}
          target="_blank"
          rel="noreferrer"
        >
          Telemetry opt-in
        </a>
      </p>
    </section>
  );
}

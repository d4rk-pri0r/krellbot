/**
 * Paid disclosures copy — M21.5 / docs/paid-disclosures.md.
 */
import { describe, expect, it } from "vitest";
import {
  PAID_DISCLOSURES_ACCEPT_PHRASES,
  PAID_DISCLOSURES_DOC_URL,
  PAID_DISCLOSURES_FEE_SHARE_REFERRAL,
  PAID_DISCLOSURES_LEDE,
  PAID_DISCLOSURES_NOT_ADVICE,
  PAID_DISCLOSURES_REFUND_WINDOW,
  PAID_DISCLOSURES_TELEMETRY_OPT_IN,
  paidDisclosuresCopyIsComplete,
} from "./paidDisclosures";

describe("paidDisclosures copy", () => {
  it("ships closed phrases for the M21.5 accept command", () => {
    const combined = [
      PAID_DISCLOSURES_LEDE,
      PAID_DISCLOSURES_FEE_SHARE_REFERRAL,
      PAID_DISCLOSURES_NOT_ADVICE,
      PAID_DISCLOSURES_REFUND_WINDOW,
      PAID_DISCLOSURES_TELEMETRY_OPT_IN,
    ].join("\n");
    expect(paidDisclosuresCopyIsComplete(combined)).toBe(true);
    for (const phrase of PAID_DISCLOSURES_ACCEPT_PHRASES) {
      expect(combined.toLowerCase()).toContain(phrase.toLowerCase());
    }
  });

  it("keeps not-advice and fee share / referral without promising profit", () => {
    expect(PAID_DISCLOSURES_NOT_ADVICE.toLowerCase()).toContain(
      "not personalized advice",
    );
    expect(PAID_DISCLOSURES_FEE_SHARE_REFERRAL.toLowerCase()).toContain(
      "fee share",
    );
    expect(PAID_DISCLOSURES_FEE_SHARE_REFERRAL.toLowerCase()).toContain(
      "referral",
    );
    expect(PAID_DISCLOSURES_REFUND_WINDOW.toLowerCase()).toContain("refund");
    expect(PAID_DISCLOSURES_TELEMETRY_OPT_IN.toLowerCase()).toContain("opt-in");
    const text = [
      PAID_DISCLOSURES_LEDE,
      PAID_DISCLOSURES_NOT_ADVICE,
      PAID_DISCLOSURES_REFUND_WINDOW,
      PAID_DISCLOSURES_TELEMETRY_OPT_IN,
    ].join(" ");
    expect(text.toLowerCase()).not.toMatch(/guaranteed\s+returns?/);
    expect(text.toLowerCase()).not.toMatch(/\breturns\b/);
  });

  it("points at the paid disclosures doc", () => {
    expect(PAID_DISCLOSURES_DOC_URL).toContain("docs/paid-disclosures.md");
  });
});

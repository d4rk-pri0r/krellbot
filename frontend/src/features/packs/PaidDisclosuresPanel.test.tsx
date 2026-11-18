/**
 * Paid disclosures panel — Packs + Settings (M21.5).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { PaidDisclosuresPanel } from "./PaidDisclosuresPanel";
import {
  PAID_DISCLOSURES_DOC_URL,
  PAID_DISCLOSURES_FEE_SHARE_REFERRAL,
  PAID_DISCLOSURES_NOT_ADVICE,
  PAID_DISCLOSURES_REFUND_WINDOW,
  PAID_DISCLOSURES_REFUNDS_URL,
  PAID_DISCLOSURES_TELEMETRY_OPT_IN,
  PAID_DISCLOSURES_TELEMETRY_URL,
} from "./paidDisclosures";

afterEach(() => {
  cleanup();
});

describe("PaidDisclosuresPanel", () => {
  it("renders fee share / referral, not advice, refund window, telemetry opt-in", () => {
    render(<PaidDisclosuresPanel variant="settings" />);
    expect(screen.getByTestId("paid-disclosures-panel")).toBeTruthy();
    expect(screen.getByTestId("paid-disclosures-fee-share").textContent).toBe(
      PAID_DISCLOSURES_FEE_SHARE_REFERRAL,
    );
    expect(screen.getByTestId("paid-disclosures-not-advice").textContent).toBe(
      PAID_DISCLOSURES_NOT_ADVICE,
    );
    expect(screen.getByTestId("paid-disclosures-refund").textContent).toBe(
      PAID_DISCLOSURES_REFUND_WINDOW,
    );
    expect(screen.getByTestId("paid-disclosures-telemetry").textContent).toBe(
      PAID_DISCLOSURES_TELEMETRY_OPT_IN,
    );
    expect(
      screen.getByTestId("paid-disclosures-not-advice").textContent?.toLowerCase(),
    ).toContain("not personalized advice");
    expect(
      screen.getByTestId("paid-disclosures-fee-share").textContent?.toLowerCase(),
    ).toMatch(/fee share/);
    expect(
      screen.getByTestId("paid-disclosures-fee-share").textContent?.toLowerCase(),
    ).toMatch(/referral/);
    expect(
      screen.getByTestId("paid-disclosures-refund").textContent?.toLowerCase(),
    ).toMatch(/refund/);
    expect(
      screen.getByTestId("paid-disclosures-telemetry").textContent?.toLowerCase(),
    ).toMatch(/opt-in/);
  });

  it("links docs for paid disclosures, refund window, and telemetry opt-in", () => {
    render(<PaidDisclosuresPanel variant="packs" />);
    const links = screen.getByTestId("paid-disclosures-links");
    const hrefs = Array.from(links.querySelectorAll("a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toContain(PAID_DISCLOSURES_DOC_URL);
    expect(hrefs).toContain(PAID_DISCLOSURES_REFUNDS_URL);
    expect(hrefs).toContain(PAID_DISCLOSURES_TELEMETRY_URL);
    expect(screen.getByTestId("paid-disclosures-panel").getAttribute("data-variant")).toBe(
      "packs",
    );
  });
});

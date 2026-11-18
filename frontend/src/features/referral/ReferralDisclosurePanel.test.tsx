import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReferralDisclosurePanel } from "./ReferralDisclosurePanel";
import type { ReferralClient, ReferralStatus } from "./client";
import {
  REFERRAL_DISCLOSURE_BODY,
  REFERRAL_DISCLOSURE_HEADLINE,
  REFERRAL_PACKS_DISCLOSURE,
} from "./copy";

function status(over: Partial<ReferralStatus> = {}): ReferralStatus {
  return {
    schema_version: "1",
    headline: REFERRAL_DISCLOSURE_HEADLINE,
    body: REFERRAL_DISCLOSURE_BODY,
    packs_body: REFERRAL_PACKS_DISCLOSURE,
    earn_rule: "1",
    source: "docs/product-direction.md",
    receipt_count: 0,
    receipts: [],
    ...over,
  };
}

function clientStub(
  over: Partial<ReferralClient> = {},
): ReferralClient {
  return {
    getStatus: vi.fn().mockResolvedValue(status()),
    attribute: vi.fn().mockResolvedValue({
      schema_version: "1",
      ok: true,
      code: "referral_attributed",
      message: "attribution recorded",
      receipt_id: "r1",
      kind: "exchange_signup",
      server_posted: true,
      disclosure: {
        schema_version: "1",
        headline: REFERRAL_DISCLOSURE_HEADLINE,
        body: REFERRAL_DISCLOSURE_BODY,
        packs_body: REFERRAL_PACKS_DISCLOSURE,
        earn_rule: "1",
        source: "docs/product-direction.md",
      },
    }),
    ...over,
  };
}

describe("ReferralDisclosurePanel", () => {
  it("shows earn-rule disclosure copy from product direction", async () => {
    render(<ReferralDisclosurePanel client={clientStub()} />);
    await waitFor(() => {
      expect(screen.getByTestId("referral-disclosure-body").textContent).toBe(
        REFERRAL_DISCLOSURE_BODY,
      );
    });
    expect(screen.getByText(REFERRAL_DISCLOSURE_HEADLINE)).toBeTruthy();
    expect(REFERRAL_DISCLOSURE_BODY).toMatch(/referral path/);
    expect(REFERRAL_PACKS_DISCLOSURE.toLowerCase()).toContain("fee share");
  });

  it("records disclosed exchange signup attribution", async () => {
    const client = clientStub({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce(status())
        .mockResolvedValueOnce(status({ receipt_count: 1 })),
    });
    render(<ReferralDisclosurePanel client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("referral-receipt-count").textContent).toContain(
        "0",
      );
    });
    fireEvent.click(screen.getByTestId("referral-attribute-exchange"));
    await waitFor(() => {
      expect(client.attribute).toHaveBeenCalledWith({
        kind: "exchange_signup",
        venue: "kraken",
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId("referral-feedback").textContent).toBe(
        "attribution recorded",
      );
      expect(screen.getByTestId("referral-receipt-count").textContent).toContain(
        "1",
      );
    });
  });
});

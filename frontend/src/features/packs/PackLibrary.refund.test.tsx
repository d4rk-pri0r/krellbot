/**
 * Pack library refund form — entitlement revoke request (M21.3).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PackLibrary } from "./PackLibrary";
import type { PackLibraryClient, RefundResult } from "./client";

afterEach(() => {
  cleanup();
});

function makeClient(
  overrides: Partial<
    PackLibraryClient & { requestRefund(sku: string): Promise<RefundResult> }
  > = {},
) {
  return {
    listInstalled: vi.fn(async () => []),
    redeemActivation: vi.fn(async () => ({
      schema_version: "1",
      status: "dead" as const,
      message: "license not accepted",
      catalog_downloaded: false,
    })),
    requestRefund: vi.fn(async (sku: string): Promise<RefundResult> => ({
      schema_version: "1",
      status: "refunded",
      message: "refund completed",
      sku,
      entitlements: [],
      refund_id: `re_fake_${sku}`,
    })),
    ...overrides,
  };
}

describe("PackLibrary refund request", () => {
  it("requests a refund and reports entitlement revoke", async () => {
    const requestRefund = vi.fn(async (): Promise<RefundResult> => ({
      schema_version: "1",
      status: "refunded",
      message: "refund completed",
      sku: "paid-launch-dca",
      entitlements: [],
      refund_id: "re_fake_paid-launch-dca",
    }));
    render(<PackLibrary client={makeClient({ requestRefund })} showBillingForms />);

    await screen.findByTestId("pack-library-refund");
    fireEvent.change(screen.getByTestId("pack-library-refund-input"), {
      target: { value: "paid-launch-dca" },
    });
    fireEvent.click(screen.getByTestId("pack-library-refund-submit"));

    await waitFor(() => {
      expect(requestRefund).toHaveBeenCalledWith("paid-launch-dca");
    });
    expect(screen.getByTestId("pack-library-refund-feedback").textContent).toMatch(
      /Entitlement revoked/,
    );
  });

  it("keeps trading/export honesty on failed refund", async () => {
    const requestRefund = vi.fn(async (): Promise<RefundResult> => ({
      schema_version: "1",
      status: "failed",
      message: "refund refused",
      sku: "paid-launch-dca",
      entitlements: ["paid-launch-dca"],
      refund_id: null,
    }));
    render(<PackLibrary client={makeClient({ requestRefund })} showBillingForms />);

    await screen.findByTestId("pack-library-refund");
    fireEvent.change(screen.getByTestId("pack-library-refund-input"), {
      target: { value: "paid-launch-dca" },
    });
    fireEvent.click(screen.getByTestId("pack-library-refund-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("pack-library-refund-error").textContent).toMatch(
        /trading and export stay available/i,
      );
    });
  });

  it("hides the refund form when requestRefund is absent", async () => {
    render(
      <PackLibrary
        showBillingForms
        client={{
          listInstalled: vi.fn(async () => []),
          redeemActivation: vi.fn(async () => ({
            schema_version: "1",
            status: "dead" as const,
            message: "license not accepted",
            catalog_downloaded: false,
          })),
        }}
      />,
    );
    await screen.findByTestId("pack-library-redeem");
    expect(screen.queryByTestId("pack-library-refund")).toBeNull();
  });

  it("hides billing forms by default on PackLibrary (mounted under Settings → Trust & billing)", async () => {
    render(<PackLibrary client={makeClient()} />);
    await screen.findByTestId("pack-library-empty");
    expect(screen.queryByTestId("pack-library-redeem")).toBeNull();
    expect(screen.queryByTestId("pack-library-refund")).toBeNull();
  });
});

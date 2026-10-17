/**
 * StatusStrip — live status / kill-switch reflection evidence.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * The strip is the persistent top-of-shell control surface. It must reflect
 * the real LiveStatus the operations client already serves (kill-switch
 * engagement, authorized venues, promotion availability) instead of a static
 * placeholder, without duplicating OperationsView's action surfaces: the
 * strip reflects state, it never engages or releases anything.
 *
 * No fake backend health, fake kill reason, fake venue grants or fake
 * promotion copy is asserted — every expectation is driven by a typed
 * LiveStatus fixture.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LiveStatus } from "../features/operations/client";
import { StatusStrip } from "./StatusStrip";

function live(over: Partial<LiveStatus> = {}): LiveStatus {
  return {
    schema_version: "1",
    live_enabled: false,
    authorized: [],
    kill_switch: { engaged: false, reason: null, engaged_at: null },
    promotion_available: false,
    promotion_code: "live_promotion_owner_deferred",
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("StatusStrip — static-to-live contract (KRELL-SIGNAL-20261010)", () => {
  it("renders the honest unavailable placeholder when no live status has been read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("no server in this test"))),
    );
    render(<StatusStrip />);
    // OLD state, still required: without a read there is nothing truthful to
    // claim, so the strip says live orders are unavailable and reports Paper.
    await waitFor(() => {
      expect(screen.getByTestId("live-orders-status").textContent).toBe(
        "Live orders unavailable",
      );
    });
    expect(screen.getByLabelText("Mode Paper").textContent).toBe("Paper");
  });

  it("drops the unavailable placeholder once a real LiveStatus is provided", () => {
    render(<StatusStrip live={live()} />);
    expect(screen.getByTestId("live-orders-status").textContent).not.toBe(
      "Live orders unavailable",
    );
    // No kill switch engaged, no authorized venues: still honestly Paper,
    // and no kill rule is fabricated.
    expect(screen.getByLabelText("Mode Paper").textContent).toBe("Paper");
    expect(screen.queryByTestId("statusstrip-kill")).toBeNull();
  });

  it("reflects an engaged kill switch with its reason and readable timestamp", () => {
    render(
      <StatusStrip
        live={live({
          kill_switch: {
            engaged: true,
            reason: "manual_engaged",
            engaged_at: 1760000000,
          },
        })}
      />,
    );
    const kill = screen.getByTestId("statusstrip-kill").textContent ?? "";
    expect(kill).toContain("Kill switch engaged");
    expect(kill).toContain("manual_engaged");
    // Human-readable, timezone-explicit form of the server's epoch seconds.
    expect(kill).toContain("2025-10-09 08:53:20 UTC");
    // State is never carried by the dot color alone.
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "Kill switch: engaged — manual_engaged",
    );
  });

  it("counts authorized venues and switches the mode label to Live", () => {
    render(
      <StatusStrip
        live={live({
          authorized: [
            { venue: "kraken", pair: "BTC/USD" },
            { venue: "coinbase", pair: "ETH/USD" },
          ],
        })}
      />,
    );
    expect(screen.getByTestId("live-orders-status").textContent).toContain(
      "2 live venues authorized",
    );
    expect(screen.getByLabelText("Mode Live").textContent).toBe("Live");
  });

  it("shows the promotion affordance copy only when promotion is available", () => {
    const withPromotion = render(<StatusStrip live={live({ promotion_available: true })} />);
    expect(screen.getByTestId("statusstrip-promotion").textContent).toContain(
      "Promotion available",
    );
    withPromotion.unmount();
    // ...and never invents it when the server says it is not.
    render(<StatusStrip live={live()} />);
    expect(screen.queryByTestId("statusstrip-promotion")).toBeNull();
  });

  it("keeps long venue names inside the strip instead of widening the page", () => {
    render(
      <StatusStrip
        live={live({
          authorized: [
            { venue: "a-very-long-exchange-identifier", pair: "VERYLONGSYMBOL/USDT" },
          ],
        })}
      />,
    );
    const venue = screen.getByTestId("statusstrip-venue");
    expect(venue.textContent).toContain("a-very-long-exchange-identifier");
    // The composition relies on CSS wrapping, which jsdom does not apply;
    // pin the structural contract the CSS depends on instead.
    expect(venue.className).toContain("kbot-status__venue");
    expect(venue.closest(".kbot-status")).not.toBeNull();
  });

  it("reflects a self-read view when mounted without a prop", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            live: {
              schema_version: "1",
              live_enabled: true,
              authorized: [{ venue: "kraken", pair: "BTC/USD" }],
              kill_switch: { engaged: true, reason: "manual_engaged", engaged_at: 1760000000 },
              promotion_available: false,
              promotion_code: "live_promotion_owner_deferred",
            },
            deployments: [],
            alerts: [],
          }),
          { status: 200 },
        ),
      ),
    );
    render(<StatusStrip />);
    await waitFor(() => {
      expect(screen.getByTestId("live-orders-status").textContent).toBe(
        "Kill switch: engaged — manual_engaged",
      );
    });
    expect(screen.getByLabelText("Mode Live").textContent).toBe("Live");
  });
});

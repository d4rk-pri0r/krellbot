/**
 * StatusStrip — engaged_at Date-range containment regression (issue 297).
 * Contract: KRELL-SIGNAL-20261010.
 *
 * An engaged kill-switch whose engaged_at cannot be represented as a Date
 * (out-of-range epoch seconds, NaN, ±Infinity) must never throw the whole
 * shell status strip away with a RangeError from toISOString: the strip
 * keeps reflecting mode, engagement and authorized venues, and the kill
 * rule renders without the timestamp node — the same honest presentation
 * as a missing engaged_at — instead of any fabricated timestamp, epoch or
 * current-date text. A healthy finite engaged_at stays byte-equivalent
 * "YYYY-MM-DD HH:MM:SS UTC".
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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

function engagedLive(engagedAt: number): LiveStatus {
  return live({
    authorized: [{ venue: "kraken", pair: "BTC/USD" }],
    kill_switch: {
      engaged: true,
      reason: "manual_engaged",
      engaged_at: engagedAt,
    },
  });
}

afterEach(cleanup);

describe("StatusStrip engaged_at Date-range containment (issue 297)", () => {
  // 1e13 epoch seconds is 1e16 epoch milliseconds — past the maximum
  // ECMAScript time value (±8.64e15 ms) — in both directions.
  it.each([1e13, -1e13])(
    "keeps the strip usable without a timestamp for out-of-range engaged_at %s",
    (engagedAt) => {
      render(<StatusStrip live={engagedLive(engagedAt)} />);
      const kill = screen.getByTestId("statusstrip-kill");
      expect(kill.querySelector(".kbot-status__kill-label")?.textContent).toBe(
        "Kill switch engaged",
      );
      expect(kill.querySelector(".kbot-status__kill-reason")?.textContent).toBe(
        "manual_engaged",
      );
      // The honest missing-timestamp presentation, never a RangeError.
      expect(kill.querySelector(".kbot-status__kill-at")).toBeNull();
      // No fabricated timestamp, epoch or current-date text sneaks in.
      expect(kill.textContent ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}/);
      expect(kill.textContent ?? "").not.toContain("UTC");
      // The strip still reflects mode, engagement and authorized venues.
      expect(screen.getByLabelText("Mode Live").textContent).toBe("Live");
      expect(screen.getByTestId("live-orders-status").textContent).toBe(
        "Kill switch: engaged — manual_engaged",
      );
      expect(screen.getByTestId("statusstrip-venues").textContent).toContain(
        "kraken",
      );
    },
  );

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    "keeps the strip usable without a timestamp for non-finite engaged_at %s",
    (engagedAt) => {
      render(<StatusStrip live={engagedLive(engagedAt)} />);
      const kill = screen.getByTestId("statusstrip-kill");
      expect(kill.querySelector(".kbot-status__kill-label")?.textContent).toBe(
        "Kill switch engaged",
      );
      expect(kill.querySelector(".kbot-status__kill-reason")?.textContent).toBe(
        "manual_engaged",
      );
      expect(kill.querySelector(".kbot-status__kill-at")).toBeNull();
      expect(kill.textContent ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}/);
      expect(kill.textContent ?? "").not.toContain("UTC");
      expect(screen.getByLabelText("Mode Live").textContent).toBe("Live");
      expect(screen.getByTestId("live-orders-status").textContent).toBe(
        "Kill switch: engaged — manual_engaged",
      );
      expect(screen.getByTestId("statusstrip-venues").textContent).toContain(
        "kraken",
      );
    },
  );

  it("keeps a healthy finite engaged_at byte-equivalent in UTC", () => {
    render(<StatusStrip live={engagedLive(1700000000)} />);
    expect(
      screen
        .getByTestId("statusstrip-kill")
        .querySelector(".kbot-status__kill-at")?.textContent,
    ).toBe("2023-11-14 22:13:20 UTC");
  });

  it("keeps the epoch boundary engaged_at of 0 renderable in UTC", () => {
    render(<StatusStrip live={engagedLive(0)} />);
    expect(
      screen
        .getByTestId("statusstrip-kill")
        .querySelector(".kbot-status__kill-at")?.textContent,
    ).toBe("1970-01-01 00:00:00 UTC");
  });

  it("leaves the healthy-control fixture's mode and venue reflection unchanged", () => {
    render(<StatusStrip live={engagedLive(1700000000)} />);
    expect(screen.getByLabelText("Mode Live").textContent).toBe("Live");
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "Kill switch: engaged — manual_engaged",
    );
    expect(screen.getByTestId("statusstrip-venues").textContent).toContain(
      "BTC/USD",
    );
  });

  it("renders no kill rule when the switch is not engaged with a null engaged_at", () => {
    render(<StatusStrip live={live()} />);
    expect(screen.queryByTestId("statusstrip-kill")).toBeNull();
    expect(screen.getByLabelText("Mode Paper").textContent).toBe("Paper");
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "No live venues authorized",
    );
  });
});

/**
 * StatusStrip — scoped Signal presentation vocabulary evidence.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Pins the owner-approved scoped class vocabulary the top-of-shell strip
 * renders (.kbot-status and its __-children from
 * frontend/src/shell/StatusStrip.signal.css) without touching the legacy
 * unscoped StatusStrip.test.tsx: every expectation here is driven through
 * the existing `live` prop path onto StatusStripBody, and every test
 * references an existing data-testid marker verbatim
 * (live-orders-status / statusstrip-venues / statusstrip-venue /
 * statusstrip-promotion / statusstrip-kill), which this slice must not
 * alter.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { LiveStatus } from "../features/operations/client";
import { StatusStrip } from "./StatusStrip";

afterEach(cleanup);

const cssSource = readFileSync(
  resolve(__dirname, "StatusStrip.signal.css"),
  "utf8",
);

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

describe("StatusStrip Signal presentation (KRELL-SIGNAL-20261010)", () => {
  it("mounts the scoped Signal root with the shared status vocabulary", () => {
    render(<StatusStrip live={live()} />);
    const orders = screen.getByTestId("live-orders-status");
    const root = orders.closest(".kbot-status");
    expect(root).not.toBeNull();
    // Exact tokens, not substrings: a renamed or suffixed class must fail.
    expect(root?.classList.contains("kbot-status")).toBe(true);
    expect(root?.classList.contains("kbot-status--engaged")).toBe(false);
    expect(root?.getAttribute("role")).toBe("region");
    expect(root?.getAttribute("aria-label")).toBe("Status");
    expect(root?.querySelector(".kbot-status__dot")).not.toBeNull();
    expect(root?.querySelector(".kbot-status__mode")?.textContent).toBe("Paper");
    expect(root?.querySelector(".kbot-status__divider")).not.toBeNull();
    expect(orders.classList.contains("kbot-status__orders")).toBe(true);
  });

  it("keeps the honest unavailable placeholder inside the scoped orders class", () => {
    render(<StatusStrip live={null} />);
    const orders = screen.getByTestId("live-orders-status");
    expect(orders.classList.contains("kbot-status__orders")).toBe(true);
    expect(orders.textContent).toBe("Live orders unavailable");
    const root = orders.closest(".kbot-status");
    expect(root?.querySelector(".kbot-status__mode")?.textContent).toBe("Paper");
    // No read yet: no venue chips, no promotion affordance, no kill rule.
    expect(screen.queryByTestId("statusstrip-venues")).toBeNull();
    expect(screen.queryByTestId("statusstrip-promotion")).toBeNull();
    expect(screen.queryByTestId("statusstrip-kill")).toBeNull();
  });

  it("engages the scoped root and renders the kill rule under the approved classes", () => {
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
    const kill = screen.getByTestId("statusstrip-kill");
    expect(kill.classList.contains("kbot-status__kill")).toBe(true);
    expect(kill.querySelector(".kbot-status__kill-label")?.textContent).toBe(
      "Kill switch engaged",
    );
    expect(kill.querySelector(".kbot-status__kill-reason")?.textContent).toBe(
      "manual_engaged",
    );
    expect(kill.querySelector(".kbot-status__kill-at")?.textContent).toBe(
      "2025-10-09 08:53:20 UTC",
    );
    const root = kill.closest(".kbot-status");
    expect(root?.classList.contains("kbot-status")).toBe(true);
    expect(root?.classList.contains("kbot-status--engaged")).toBe(true);
    expect(root?.getAttribute("aria-label")).toBe("Status — kill switch engaged");
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "Kill switch: engaged — manual_engaged",
    );
  });

  it("omits the kill timestamp node when the server reports none", () => {
    render(
      <StatusStrip
        live={live({
          kill_switch: { engaged: true, reason: null, engaged_at: null },
        })}
      />,
    );
    const kill = screen.getByTestId("statusstrip-kill");
    expect(kill.classList.contains("kbot-status__kill")).toBe(true);
    expect(kill.querySelector(".kbot-status__kill-label")).not.toBeNull();
    expect(kill.querySelector(".kbot-status__kill-reason")?.textContent).toBe(
      "(no reason)",
    );
    expect(kill.querySelector(".kbot-status__kill-at")).toBeNull();
  });

  it("renders authorized venue chips through the scoped venues vocabulary", () => {
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
    const venues = screen.getByTestId("statusstrip-venues");
    expect(venues.classList.contains("kbot-status__venues")).toBe(true);
    const chips = screen.getAllByTestId("statusstrip-venue");
    expect(chips).toHaveLength(2);
    for (const chip of chips) {
      expect(chip.classList.contains("kbot-status__venue")).toBe(true);
      expect(chip.closest(".kbot-status")).not.toBeNull();
    }
    expect(venues.querySelectorAll(".kbot-status__pair")).toHaveLength(2);
    expect(chips[0]?.querySelector(".kbot-status__pair")?.textContent).toBe(
      "BTC/USD",
    );
    // Mode follows the authorization, not just the switch.
    expect(
      screen
        .getByTestId("live-orders-status")
        .closest(".kbot-status")
        ?.querySelector(".kbot-status__mode")?.textContent,
    ).toBe("Live");
  });

  it("keeps the venues container absent when nothing is authorized", () => {
    render(<StatusStrip live={live()} />);
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "No live venues authorized",
    );
    expect(screen.queryByTestId("statusstrip-venues")).toBeNull();
    expect(screen.queryByTestId("statusstrip-venue")).toBeNull();
  });

  it("renders the promotion affordance only under the scoped class", () => {
    render(<StatusStrip live={live({ promotion_available: true })} />);
    const promotion = screen.getByTestId("statusstrip-promotion");
    expect(promotion.classList.contains("kbot-status__promotion")).toBe(true);
    expect(promotion.textContent).toBe("Promotion available");
    expect(promotion.closest(".kbot-status")).not.toBeNull();
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "No live venues authorized",
    );
  });

  it("keeps the promotion affordance absent when unavailable", () => {
    render(<StatusStrip live={live()} />);
    expect(screen.getByTestId("live-orders-status").textContent).toBe(
      "No live venues authorized",
    );
    expect(screen.queryByTestId("statusstrip-promotion")).toBeNull();
  });

  it("scopes the Signal stylesheet to the approved vocabulary and tokens", () => {
    // The rendered strip still carries the scoped orders class this
    // stylesheet owns.
    render(<StatusStrip live={live()} />);
    const orders = screen.getByTestId("live-orders-status");
    expect(orders.classList.contains("kbot-status__orders")).toBe(true);
    for (const selector of [
      ".kbot-status--engaged",
      ".kbot-status__venues",
      ".kbot-status__venue",
      ".kbot-status__pair",
      ".kbot-status__promotion",
      ".kbot-status__kill",
      ".kbot-status__kill-label",
      ".kbot-status__kill-reason",
      ".kbot-status__kill-at",
      ".kbot-status__orders",
    ]) {
      expect(cssSource.includes(selector)).toBe(true);
    }
    // Approved Signal vocabulary only: navy/surface/line panels, muted and
    // text prose, mono technical ids, sage affirmative, coral caution.
    expect(cssSource).toContain('var(--font-mono, "IBM Plex Mono"');
    expect(cssSource).toContain("var(--coral, #cc9689)");
    expect(cssSource).toContain("var(--sage, #b3dda8)");
    expect(cssSource).toContain("var(--muted, #abc4d8)");
    expect(cssSource).toContain("var(--surface, #14222e)");
    expect(cssSource).toContain("var(--navy, #0e1c29)");
    expect(cssSource).toContain("var(--line, #22465d)");
    expect(cssSource).not.toContain("#a3ff12");
    expect(cssSource).not.toContain("lime");
    expect(cssSource).not.toContain("cyan");
  });

  it("keeps 390px containment and ≥44px rows in the mobile layer", () => {
    // The wrapping contract is what the rendered strip relies on; anchor the
    // css expectations on the live surface the stylesheet governs.
    render(<StatusStrip live={live()} />);
    expect(screen.getByTestId("live-orders-status").closest(".kbot-status")).not.toBeNull();
    expect(cssSource).toContain("@media (max-width: 640px)");
    expect(cssSource).toMatch(/min-height:\s*44px/);
    expect(cssSource).toMatch(/overflow-wrap:\s*anywhere/);
    expect(cssSource).toMatch(/min-width:\s*0/);
  });
});

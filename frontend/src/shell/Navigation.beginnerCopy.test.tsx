/**
 * Pins shell honesty: StatusStrip is the single shell-level paper-only status
 * pill, and Navigation renders destinations without duplicating Local preview.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Navigation } from "./Navigation";
import { StatusStrip } from "./StatusStrip";

afterEach(() => {
  cleanup();
});

describe("Shell paper-only status honesty", () => {
  it("keeps paper-only status in StatusStrip rather than repeating it inside Navigation", () => {
    render(
      <>
        <Navigation active="home" onChange={() => {}} />
        <StatusStrip
          live={{
            schema_version: "1",
            live_enabled: false,
            authorized: [],
            kill_switch: { engaged: false, reason: null, engaged_at: null },
            promotion_available: false,
            promotion_code: "live_promotion_owner_deferred",
          }}
        />
      </>,
    );
    expect(screen.queryByTestId("nav-local-preview")).toBeNull();
    expect(screen.queryByTestId("nav-local-preview-note")).toBeNull();
    expect(screen.getByTestId("kbot-status-strip").textContent).toContain(
      "No live venues authorized",
    );
  });
});

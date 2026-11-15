import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FleetArmedList } from "./FleetArmedList";
import type { FleetArmedClient, FleetArmedDeployment, FleetArmedView } from "./client";

function deployment(
  overrides: Partial<FleetArmedDeployment> = {},
): FleetArmedDeployment {
  return {
    venue: "kraken",
    pair: "SUIUSD",
    mode: "paper",
    pack_id: "trend-follow",
    entries_paused: false,
    last_tick_ts_ms: 1_700_000_100_000,
    last_tick_result: "2 ticks, last refusal insufficient_cash",
    last_refusal_code: "insufficient_cash",
    detail_href: "/?view=workstation&venue=kraken&pair=SUIUSD",
    ...overrides,
  };
}

function view(deployments: FleetArmedDeployment[]): FleetArmedView {
  return {
    schema_version: "1",
    armed: deployments.length > 0,
    deployments,
  };
}

function makeClient(
  listFleet: FleetArmedClient["listFleet"],
): FleetArmedClient {
  return { listFleet };
}

describe("FleetArmedList", () => {
  it("renders armed deployments with last tick time, result, and detail link", async () => {
    const client = makeClient(vi.fn().mockResolvedValue(view([deployment()])));
    render(<FleetArmedList client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-table")).toBeTruthy();
    });
    expect(screen.getByTestId("fleet-armed-count").textContent).toBe(
      "1 armed deployment",
    );
    expect(screen.getByTestId("fleet-armed-last-tick").textContent).toBe(
      new Date(1_700_000_100_000).toISOString(),
    );
    expect(screen.getByTestId("fleet-armed-last-result").textContent).toBe(
      "2 ticks, last refusal insufficient_cash",
    );
    const link = screen.getByTestId("fleet-armed-detail-link");
    expect(link.getAttribute("href")).toBe(
      "/?view=workstation&venue=kraken&pair=SUIUSD",
    );
  });

  it("shows no-tick-yet result and an em dash when last_tick_ts_ms is null", async () => {
    const client = makeClient(
      vi.fn().mockResolvedValue(
        view([
          deployment({
            last_tick_ts_ms: null,
            last_tick_result: "no tick yet",
            last_refusal_code: null,
          }),
        ]),
      ),
    );
    render(<FleetArmedList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-last-result").textContent).toBe(
        "no tick yet",
      );
    });
    expect(screen.getByTestId("fleet-armed-last-tick").textContent).toBe("—");
  });

  it("shows the confirmed empty state when no packs are armed", async () => {
    const client = makeClient(vi.fn().mockResolvedValue(view([])));
    render(<FleetArmedList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-empty").textContent).toBe(
        "No packs armed",
      );
    });
  });

  it("invokes onOpenDetail with the wire deep link for in-app navigation", async () => {
    const onOpenDetail = vi.fn();
    const client = makeClient(vi.fn().mockResolvedValue(view([deployment()])));
    render(<FleetArmedList client={client} onOpenDetail={onOpenDetail} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-detail-link")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("fleet-armed-detail-link"));
    expect(onOpenDetail).toHaveBeenCalledWith(
      "/?view=workstation&venue=kraken&pair=SUIUSD",
      "kraken",
      "SUIUSD",
    );
  });

  it("surfaces unavailable when the fleet client method is missing", () => {
    render(<FleetArmedList client={{} as FleetArmedClient} />);
    expect(screen.getByTestId("fleet-armed-unavailable").textContent).toBe(
      "Armed fleet unavailable",
    );
  });
});

/**
 * Multi-pair fleet UI (M16.2): per-pair rows, last tick, unresolved
 * summary, selection into Inspector context, and pause/disarm scoped to
 * the selected arm — never collapsed to armed[0].
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FleetArmedList } from "./FleetArmedList";
import type {
  FleetArmedClient,
  FleetArmedDeployment,
  FleetArmedView,
  PaperClient,
} from "./client";
import type { OperationsClient, UnresolvedOrderRow } from "../operations/client";
import {
  Inspector,
  selectionFromDeployment,
} from "../../shell/Inspector";

afterEach(cleanup);

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
    last_tick_result: "2 ticks, no refusal",
    last_refusal_code: null,
    detail_href: "/?view=workstation&venue=kraken&pair=SUIUSD",
    ...overrides,
  };
}

const first = deployment();
const second = deployment({
  venue: "coinbase",
  pair: "BTC-USD",
  pack_id: "mean-revert",
  entries_paused: true,
  last_tick_ts_ms: 1_700_000_200_000,
  last_tick_result: "1 tick, no refusal",
  detail_href: "/?view=workstation&venue=coinbase&pair=BTC-USD",
});

function view(deployments: FleetArmedDeployment[]): FleetArmedView {
  return {
    schema_version: "1",
    armed: deployments.length > 0,
    armed_count: deployments.length,
    deployments,
    groups: deployments.map((row) => ({
      venue: row.venue,
      pair: row.pair,
      deployments: [row],
    })),
  };
}

function makeClient(deployments = [first, second]) {
  return {
    listFleet: vi
      .fn<FleetArmedClient["listFleet"]>()
      .mockResolvedValue(view(deployments)),
    pauseEntries: vi
      .fn<PaperClient["pauseEntries"]>()
      .mockResolvedValue({ ok: true }),
    resumeEntries: vi
      .fn<PaperClient["resumeEntries"]>()
      .mockResolvedValue({ ok: true }),
    disarm: vi.fn<PaperClient["disarm"]>().mockResolvedValue({ ok: true }),
  } satisfies FleetArmedClient &
    Pick<PaperClient, "pauseEntries" | "resumeEntries" | "disarm">;
}

describe("FleetArmedList multi-pair (M16.2)", () => {
  it("renders a distinct per-pair row with last tick for every armed market", async () => {
    render(<FleetArmedList client={makeClient()} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("fleet-armed-row")).toHaveLength(2);
    });
    expect(screen.getByTestId("fleet-armed-count").textContent).toBe(
      "2 armed deployments",
    );
    const rows = screen.getAllByTestId("fleet-armed-row");
    expect(rows[0].getAttribute("data-venue")).toBe("kraken");
    expect(rows[0].getAttribute("data-pair")).toBe("SUIUSD");
    expect(rows[1].getAttribute("data-venue")).toBe("coinbase");
    expect(rows[1].getAttribute("data-pair")).toBe("BTC-USD");
    const ticks = screen.getAllByTestId("fleet-armed-last-tick");
    expect(ticks[0].textContent).toBe(new Date(1_700_000_100_000).toISOString());
    expect(ticks[1].textContent).toBe(new Date(1_700_000_200_000).toISOString());
    const results = screen.getAllByTestId("fleet-armed-last-result");
    expect(results[0].textContent).toBe("2 ticks, no refusal");
    expect(results[1].textContent).toBe("1 tick, no refusal");
  });

  it("shows unresolved summary count without collapsing multi-pair rows", async () => {
    const unresolved: UnresolvedOrderRow[] = [
      {
        client_order_id: "coid-a",
        age_seconds: 10,
        last_lookup_result: "absent",
      },
      {
        client_order_id: "coid-b",
        age_seconds: 20,
        last_lookup_result: "open",
      },
    ];
    const unresolvedClient = {
      listUnresolvedOrders: vi.fn().mockResolvedValue(unresolved),
    } as Pick<OperationsClient, "listUnresolvedOrders">;
    render(
      <FleetArmedList
        client={makeClient()}
        unresolvedClient={unresolvedClient}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("fleet-unresolved-summary").textContent).toBe(
        "2 unresolved orders",
      );
    });
    expect(screen.getAllByTestId("fleet-armed-row")).toHaveLength(2);
  });

  it("selects one arm and scopes pause/disarm to that market only", async () => {
    const client = makeClient();
    const onSelectionChange = vi.fn();
    render(
      <FleetArmedList client={client} onSelectionChange={onSelectionChange} />,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId("fleet-armed-row")).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByTestId("fleet-armed-row")[1]);
    expect(onSelectionChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        venue: "coinbase",
        pair: "BTC-USD",
        pack_id: "mean-revert",
      }),
    );
    expect(screen.getByTestId("fleet-armed-selected").textContent).toContain(
      "coinbase · BTC-USD",
    );
    expect(screen.getByTestId("fleet-armed-selected-pack").textContent).toBe(
      "mean-revert",
    );

    fireEvent.click(screen.getByTestId("fleet-armed-selected-disarm"));
    await waitFor(() => {
      expect(client.disarm).toHaveBeenCalledExactlyOnceWith("coinbase", "BTC-USD");
    });
    expect(client.pauseEntries).not.toHaveBeenCalled();

    // Selected resume is enabled for the paused second arm; pause stays scoped.
    fireEvent.click(screen.getByTestId("fleet-armed-selected-resume"));
    await waitFor(() => {
      expect(client.resumeEntries).toHaveBeenCalledExactlyOnceWith(
        "coinbase",
        "BTC-USD",
      );
    });
  });

  it("keeps Inspector selection context truthful for the selected fleet arm", async () => {
    const client = makeClient();
    const onSelectionChange = vi.fn();
    render(
      <FleetArmedList client={client} onSelectionChange={onSelectionChange} />,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId("fleet-armed-row")).toHaveLength(2);
    });
    fireEvent.click(screen.getAllByTestId("fleet-armed-row")[0]);
    expect(onSelectionChange).toHaveBeenCalledTimes(1);
    const row = onSelectionChange.mock.calls[0][0] as FleetArmedDeployment;
    const selection = selectionFromDeployment({
      venue: row.venue,
      pair: row.pair,
      mode: row.mode,
      pack_id: row.pack_id,
      entries_paused: row.entries_paused,
    });
    render(<Inspector selection={selection} />);
    const selected = screen.getByTestId("inspector-selection");
    expect(selected.getAttribute("data-kind")).toBe("deployment");
    expect(selected.textContent).toContain("kraken:SUIUSD");
    expect(selected.textContent).toContain("trend-follow · paper");
    expect(selected.textContent).toContain("Entries active");
    expect(screen.queryByTestId("inspector-empty")).toBeNull();
  });
});

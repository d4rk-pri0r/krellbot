import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FleetArmedList } from "./FleetArmedList";
import type {
  FleetArmedClient,
  FleetArmedDeployment,
  FleetArmedView,
  PaperClient,
  PaperCommandResult,
} from "./client";
import type { OperationsClient, UnresolvedOrderRow } from "../operations/client";

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

function view(deployments: FleetArmedDeployment[]): FleetArmedView {
  return {
    schema_version: "1",
    armed: deployments.length > 0,
    deployments,
  };
}

const first = deployment();
const second = deployment({
  venue: "coinbase",
  pair: "BTC-USD",
  entries_paused: true,
  detail_href: "/?view=workstation&venue=coinbase&pair=BTC-USD",
});

function combinedClient(deployments = [first, second]) {
  return {
    listFleet: vi
      .fn<FleetArmedClient["listFleet"]>()
      .mockResolvedValue(view(deployments)),
    getStatus: vi
      .fn<PaperClient["getStatus"]>()
      .mockResolvedValue({ schema_version: "1", armed: true }),
    pauseEntries: vi
      .fn<PaperClient["pauseEntries"]>()
      .mockResolvedValue({ ok: true }),
    resumeEntries: vi
      .fn<PaperClient["resumeEntries"]>()
      .mockResolvedValue({ ok: true }),
    disarm: vi.fn<PaperClient["disarm"]>().mockResolvedValue({ ok: true }),
  } satisfies FleetArmedClient & PaperClient;
}

function button(action: "pause" | "resume" | "disarm", index = 0) {
  const controls = screen.getAllByTestId(`fleet-armed-row-${action}`);
  return controls[index] as HTMLButtonElement;
}

describe("FleetArmedList pause/disarm", () => {
  it.each([false, true])(
    "exposes native labelled pause/resume/disarm matching entries_paused=%s",
    async (paused) => {
      render(
        <FleetArmedList
          client={combinedClient([
            { ...first, entries_paused: paused },
          ])}
        />,
      );
      await waitFor(() => {
        expect(screen.getByTestId("fleet-armed-table")).toBeTruthy();
      });
      expect(button("pause").disabled).toBe(paused);
      expect(button("resume").disabled).toBe(!paused);
      expect(button("disarm").disabled).toBe(false);
      expect(button("pause").getAttribute("aria-label")).toBe(
        `Pause new buys on ${first.venue} ${first.pair}`,
      );
      expect(button("disarm").getAttribute("aria-label")).toBe(
        `Stop paper run ${first.venue} ${first.pair}`,
      );
    },
  );

  it.each([
    ["pause", "pauseEntries", 0],
    ["resume", "resumeEntries", 1],
    ["disarm", "disarm", 1],
  ] as const)(
    "%s targets only that row and refreshes once on success",
    async (action, method, index) => {
      const client = combinedClient();
      let resolve!: (value: PaperCommandResult) => void;
      client[method].mockImplementationOnce(
        () => new Promise((done) => {
          resolve = done;
        }),
      );
      client.listFleet
        .mockResolvedValueOnce(view([first, second]))
        .mockResolvedValueOnce(
          view(index === 0 ? [{ ...first, entries_paused: true }, second] : [first]),
        );
      render(<FleetArmedList client={client} />);
      await waitFor(() => {
        expect(screen.getAllByTestId("fleet-armed-row")).toHaveLength(2);
      });
      fireEvent.click(button(action, index));
      expect(client[method]).toHaveBeenCalledExactlyOnceWith(
        [first, second][index].venue,
        [first, second][index].pair,
      );
      for (const kind of ["pause", "resume", "disarm"] as const) {
        expect(button(kind, index).disabled).toBe(true);
      }
      fireEvent.click(button(action, index));
      expect(client[method]).toHaveBeenCalledTimes(1);
      await act(async () => {
        resolve({ ok: true });
      });
      await waitFor(() => {
        expect(client.listFleet).toHaveBeenCalledTimes(2);
      });
    },
  );

  it("keeps the row chip and allows retry after pause throws", async () => {
    const client = combinedClient([first]);
    client.pauseEntries.mockRejectedValueOnce(new Error("request failed: 503"));
    render(<FleetArmedList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-row-pause")).toBeTruthy();
    });
    const chip = screen.getByTestId("fleet-armed-entries");
    const previousClass = chip.className;
    fireEvent.click(button("pause"));
    const error = await screen.findByTestId("fleet-armed-row-action-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.textContent).toBe("Pause new buys failed: request failed: 503");
    expect(chip.textContent).toBe("Entries active");
    expect(chip.className).toBe(previousClass);
    expect(client.listFleet).toHaveBeenCalledTimes(1);
    expect(button("pause").disabled).toBe(false);
  });

  it("renders refusal message without refreshing", async () => {
    const client = combinedClient([first]);
    client.pauseEntries.mockResolvedValueOnce({
      ok: false,
      code: "conflict",
      message: "run not owned",
    });
    render(<FleetArmedList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-row-pause")).toBeTruthy();
    });
    fireEvent.click(button("pause"));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Pause new buys failed: run not owned",
    );
    expect(client.listFleet).toHaveBeenCalledTimes(1);
  });

  it("refreshes the confirmed pause chip before offering resume", async () => {
    const client = combinedClient([first]);
    client.listFleet
      .mockResolvedValueOnce(view([first]))
      .mockResolvedValueOnce(view([{ ...first, entries_paused: true }]));
    render(<FleetArmedList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-entries").textContent).toBe(
        "Entries active",
      );
    });
    fireEvent.click(button("pause"));
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-entries").textContent).toBe(
        "Entries paused",
      );
    });
    expect(button("pause").disabled).toBe(true);
    expect(button("resume").disabled).toBe(false);
    expect(client.listFleet).toHaveBeenCalledTimes(2);
  });

  it("distinguishes a confirmed disarm from a failed list readback", async () => {
    const client = combinedClient([first]);
    client.listFleet
      .mockResolvedValueOnce(view([first]))
      .mockRejectedValueOnce(new Error("readback failed: 503"));
    render(<FleetArmedList client={client} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-row-disarm")).toBeTruthy();
    });
    fireEvent.click(button("disarm"));
    expect(
      (await screen.findByTestId("fleet-armed-error")).textContent,
    ).toBe("readback failed: 503");
    expect(screen.queryByTestId("fleet-armed-row-action-error")).toBeNull();
    expect(client.disarm).toHaveBeenCalledExactlyOnceWith(first.venue, first.pair);
    expect(client.listFleet).toHaveBeenCalledTimes(2);
  });

  it("mounts Operations unresolved list when unresolvedClient is provided", async () => {
    const unresolved: UnresolvedOrderRow[] = [
      {
        client_order_id: "coid-fleet-1",
        age_seconds: 42,
        last_lookup_result: "absent",
      },
    ];
    const unresolvedClient = {
      listUnresolvedOrders: vi.fn().mockResolvedValue(unresolved),
    } as Pick<OperationsClient, "listUnresolvedOrders">;
    render(
      <FleetArmedList
        client={combinedClient([])}
        unresolvedClient={unresolvedClient}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("fleet-unresolved-panel")).toBeTruthy();
    });
    expect(
      await screen.findByTestId("ops-unresolved-row-coid-fleet-1"),
    ).toBeTruthy();
    expect(screen.getByTestId("ops-unresolved-orders")).toBeTruthy();
  });

  it("hides unresolved panel when unresolvedClient is omitted", async () => {
    render(<FleetArmedList client={combinedClient([])} />);
    await waitFor(() => {
      expect(screen.getByTestId("fleet-armed-empty")).toBeTruthy();
    });
    expect(screen.queryByTestId("fleet-unresolved-panel")).toBeNull();
  });
});

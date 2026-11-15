import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UnresolvedOrdersList } from "./UnresolvedOrdersList";
import type { OperationsClient, UnresolvedOrderRow } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const EMPTY_TEXT = "No unresolved orders.";
const LOADING_TEXT = "Loading unresolved orders…";

function order(over: Partial<UnresolvedOrderRow> = {}): UnresolvedOrderRow {
  return {
    client_order_id: "coid-stuck-1",
    age_seconds: 125,
    last_lookup_result: "absent",
    ...over,
  };
}

function makeClient(
  over: Partial<Pick<OperationsClient, "listUnresolvedOrders">> = {},
): OperationsClient {
  return {
    getOperations: vi.fn(),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    ackAlert: vi.fn(),
    ...over,
  };
}

describe("UnresolvedOrdersList", () => {
  it("shows loading while the first list request is in flight", async () => {
    let release: ((rows: UnresolvedOrderRow[]) => void) | undefined;
    const client = makeClient({
      listUnresolvedOrders: vi.fn().mockImplementation(
        () =>
          new Promise<UnresolvedOrderRow[]>((resolve) => {
            release = resolve;
          }),
      ),
    });
    render(<UnresolvedOrdersList client={client} />);
    expect(screen.getByTestId("ops-unresolved-loading").textContent).toBe(LOADING_TEXT);
    expect((screen.getByTestId("ops-unresolved-refresh") as HTMLButtonElement).disabled).toBe(
      true,
    );
    release?.([]);
    await waitFor(() => expect(screen.queryByTestId("ops-unresolved-loading")).toBeNull());
  });

  it("says plainly when there are no unresolved orders", async () => {
    const client = makeClient({
      listUnresolvedOrders: vi.fn().mockResolvedValue([]),
    });
    render(<UnresolvedOrdersList client={client} />);
    expect(await screen.findByTestId("ops-unresolved-empty").then((n) => n.textContent)).toBe(
      EMPTY_TEXT,
    );
  });

  it("lists client order id, age, and last lookup result for each unresolved order", async () => {
    const client = makeClient({
      listUnresolvedOrders: vi.fn().mockResolvedValue([
        order(),
        order({
          client_order_id: "coid-stuck-2",
          age_seconds: 3661,
          last_lookup_result: "open",
        }),
        order({
          client_order_id: "coid-no-age",
          age_seconds: null,
          last_lookup_result: "none",
        }),
      ]),
    });
    render(<UnresolvedOrdersList client={client} />);
    const row1 = await screen.findByTestId("ops-unresolved-row-coid-stuck-1");
    expect(row1.textContent).toContain("coid-stuck-1");
    expect(row1.textContent).toContain("2m 5s");
    expect(row1.textContent).toContain("absent");
    const row2 = screen.getByTestId("ops-unresolved-row-coid-stuck-2");
    expect(row2.textContent).toContain("1h 1m");
    expect(row2.textContent).toContain("open");
    const row3 = screen.getByTestId("ops-unresolved-row-coid-no-age");
    expect(row3.textContent).toContain("—");
    expect(row3.textContent).toContain("none");
  });

  it("surfaces a load failure with retry that reloads the list", async () => {
    const listUnresolvedOrders = vi
      .fn()
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValueOnce([order()]);
    const client = makeClient({ listUnresolvedOrders });
    render(<UnresolvedOrdersList client={client} />);
    expect(await screen.findByTestId("ops-unresolved-error")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ops-unresolved-retry"));
    expect(await screen.findByTestId("ops-unresolved-row-coid-stuck-1")).toBeTruthy();
    expect(listUnresolvedOrders).toHaveBeenCalledTimes(2);
  });
});

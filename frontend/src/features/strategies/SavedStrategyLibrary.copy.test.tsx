import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SavedStrategyLibrary,
  type LibraryClient,
  type OwnedDraftSummary,
} from "./SavedStrategyLibrary";

afterEach(cleanup);

function summary(overrides: Partial<OwnedDraftSummary> = {}): OwnedDraftSummary {
  return {
    revision_id: "rev-1",
    strategy_id: "trend-follow",
    parent_revision_id: null,
    state: "draft",
    runnable: false,
    created_at: "2026-10-07T10:00:00Z",
    id: "trend-follow",
    label: "Trend follow",
    pair: "SUIUSD",
    timeframe: "1h",
    ...overrides,
  };
}

const ownedBytes = JSON.stringify({
  schema_version: 1,
  id: "trend-follow",
  version: "1.0.0",
  label: "Trend follow",
  author: "local workstation",
  timeframe: "1h",
  indicators: { ma: { fn: "sma", src: "close", len: 20 } },
  entry: ["close", ">", "ma"],
  exit: ["close", "<", "ma"],
  risk: { max_account_pct: 25, stop: { type: "pct", pct: 5 } },
  markets: [{ venue: "kraken", pair: "SUIUSD" }],
});

function makeClient(rows: OwnedDraftSummary[], bytes: string = ownedBytes): LibraryClient {
  return {
    listOwned: vi.fn().mockResolvedValue(rows),
    getJson: vi.fn().mockResolvedValue({
      revision_id: rows[0]?.revision_id ?? "rev-1",
      state: rows[0]?.state ?? "draft",
      bytes,
    }),
  };
}

describe("SavedStrategyLibrary — copy as new owned draft", () => {
  const rows = [
    summary({
      revision_id: "rev-owned-9",
      state: "validated",
      label: "Validated plan",
    }),
  ];

  it("offers a Copy as new control per owned revision only when the host supports it", async () => {
    render(
      <SavedStrategyLibrary client={makeClient(rows)} onReopen={vi.fn()} />,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("listitem").length).toBe(1),
    );
    expect(
      screen.queryByRole("button", { name: /copy as new/i }),
    ).toBeNull();
  });

  it("fetches the real bytes with client.getJson and passes them to onCopyAsNew", async () => {
    const onCopyAsNew = vi.fn();
    const client = makeClient(rows);
    render(
      <SavedStrategyLibrary
        client={client}
        onReopen={vi.fn()}
        onCopyAsNew={onCopyAsNew}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /copy as new/i }).length,
      ).toBe(1),
    );
    fireEvent.click(screen.getByRole("button", { name: /copy as new/i }));
    await waitFor(() => expect(onCopyAsNew).toHaveBeenCalledTimes(1));
    expect(client.getJson).toHaveBeenCalledWith("rev-owned-9");
    const [passedSummary, passedBytes] = onCopyAsNew.mock.calls[0];
    expect(passedSummary.revision_id).toBe("rev-owned-9");
    expect(passedBytes).toBe(ownedBytes);
  });

  it("surfaces the error and keeps the list when the copy fetch fails, without calling onCopyAsNew", async () => {
    const onCopyAsNew = vi.fn();
    const client = makeClient(rows);
    client.getJson = vi.fn().mockRejectedValue(new Error("library open failed: 500"));
    render(
      <SavedStrategyLibrary
        client={client}
        onReopen={vi.fn()}
        onCopyAsNew={onCopyAsNew}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /copy as new/i }).length,
      ).toBe(1),
    );
    fireEvent.click(screen.getByRole("button", { name: /copy as new/i }));
    await waitFor(() =>
      expect(screen.getByTestId("library-copy-error").textContent).toContain(
        "library open failed: 500",
      ),
    );
    expect(onCopyAsNew).not.toHaveBeenCalled();
    expect(screen.getAllByRole("listitem").length).toBe(1);
  });

  it("keeps rows disabled while a copy fetch is in flight and restores them after", async () => {
    let release: ((value: OwnedRevisionBytesLike) => void) | null = null;
    const pending = new Promise<OwnedRevisionBytesLike>((resolve) => {
      release = resolve;
    });
    const client: LibraryClient = {
      listOwned: vi.fn().mockResolvedValue(rows),
      getJson: vi.fn(() => pending),
    };
    const onCopyAsNew = vi.fn();
    render(
      <SavedStrategyLibrary
        client={client}
        onReopen={vi.fn()}
        onCopyAsNew={onCopyAsNew}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /copy as new/i }).length,
      ).toBe(1),
    );
    const copyButton = screen.getByRole("button", {
      name: /copy as new/i,
    }) as HTMLButtonElement;
    const reopenButton = screen.getByRole("button", {
      name: /reopen/i,
    }) as HTMLButtonElement;
    fireEvent.click(copyButton);
    await waitFor(() => expect(copyButton.disabled).toBe(true));
    expect(reopenButton.disabled).toBe(true);
    release?.({
      revision_id: "rev-owned-9",
      state: "validated",
      bytes: ownedBytes,
    });
    await waitFor(() => expect(onCopyAsNew).toHaveBeenCalledTimes(1));
    expect(copyButton.disabled).toBe(false);
    expect(reopenButton.disabled).toBe(false);
    // A single fetch: no retry storm on the happy path.
    expect(client.getJson).toHaveBeenCalledTimes(1);
  });

  it("never calls validate or arm for the copy", async () => {
    const onCopyAsNew = vi.fn();
    const client = makeClient(rows);
    render(
      <SavedStrategyLibrary
        client={client}
        onReopen={vi.fn()}
        onCopyAsNew={onCopyAsNew}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /copy as new/i }).length,
      ).toBe(1),
    );
    fireEvent.click(screen.getByRole("button", { name: /copy as new/i }));
    await waitFor(() => expect(onCopyAsNew).toHaveBeenCalledTimes(1));
    // The LibraryClient contract has no write verbs; assert the read path
    // only fetched once and no fabricated identity was handed to the host.
    expect(client.getJson).toHaveBeenCalledTimes(1);
    const [passedSummary] = onCopyAsNew.mock.calls[0];
    expect(passedSummary.revision_id).toBe("rev-owned-9");
    expect(passedSummary.state).toBe("validated");
  });
});

type OwnedRevisionBytesLike = {
  revision_id: string;
  state: "draft" | "validated" | "deployed" | "archived";
  bytes: string;
};

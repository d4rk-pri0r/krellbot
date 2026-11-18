import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ForwardPaperLedgerPanel } from "./ForwardPaperLedgerPanel";
import type { ForwardPaperLedger, ForwardPaperLedgerClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function ledger(over: Partial<ForwardPaperLedger> = {}): ForwardPaperLedger {
  return {
    schema_version: "1",
    mode: "paper",
    order: "forward",
    presentation: "local_evidence",
    disclaimer: "Paper evidence — not live P&L",
    events: [
      {
        ts: 100,
        kind: "arm",
        venue: "kraken",
        pack: "trend-follow",
        pair: "SUIUSD",
        detail: { mode: "paper" },
      },
      {
        ts: 200,
        kind: "tick",
        venue: "kraken",
        pack: "trend-follow",
        pair: "SUIUSD",
        detail: { reason: "no_signal" },
      },
      {
        ts: 200,
        kind: "refusal",
        venue: "kraken",
        pack: "trend-follow",
        pair: "SUIUSD",
        detail: { code: "store_full" },
      },
      {
        ts: 250,
        kind: "fill",
        venue: "kraken",
        pack: "",
        pair: "SUIUSD",
        detail: { coid: "c1", side: "buy", ts_ms: 250_000 },
      },
    ],
    ...over,
  };
}

function clientFor(body: ForwardPaperLedger = ledger()): ForwardPaperLedgerClient {
  return {
    listForwardLedger: vi.fn(async () => body),
  };
}

describe("ForwardPaperLedgerPanel", () => {
  it("renders events oldest-first without reversing", async () => {
    render(<ForwardPaperLedgerPanel client={clientFor()} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-forward-ledger-row-0")).toBeTruthy();
    });
    const kinds = screen
      .getAllByTestId(/paper-forward-ledger-row-/)
      .map((row) => row.querySelector(".kbot-paper-ledger__kind")?.textContent);
    expect(kinds).toEqual(["arm", "tick", "refusal", "fill"]);
    expect(screen.getByTestId("paper-forward-ledger-disclaimer").textContent).toContain(
      "Paper evidence — not live P&L",
    );
  });

  it("shows empty copy when the ledger has no events", async () => {
    render(<ForwardPaperLedgerPanel client={clientFor(ledger({ events: [] }))} />);
    expect(
      await screen.findByTestId("paper-forward-ledger-empty").then((node) => node.textContent),
    ).toBe("No paper ledger events yet.");
  });

  it("retries after a failed read", async () => {
    const listForwardLedger = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(ledger({ events: [] }));
    render(<ForwardPaperLedgerPanel client={{ listForwardLedger }} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-forward-ledger-error")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("paper-forward-ledger-retry"));
    await waitFor(() => {
      expect(screen.getByTestId("paper-forward-ledger-empty")).toBeTruthy();
    });
    expect(listForwardLedger).toHaveBeenCalledTimes(2);
  });
});

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExplainResult } from "./explainPack";
import { StrategyExplanationCsvExport } from "./StrategyExplanationCsvExport";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const EXPORT_ID = "strategies-explanation-csv-export";

function emptyResult(): ExplainResult {
  return {
    revisionId: null,
    savedStatus: "unsaved",
    parsed: false,
    metadata: { label: null, packId: null, version: null, author: null, origin: null },
    timeframe: { text: "unsupported timeframe (undefined)", supported: false },
    indicators: [],
    entry: { kind: "unknown", text: "" },
    exit: { kind: "unknown", text: "" },
    markets: [],
    allocation: { text: "", supported: false },
    stop: { text: "", supported: false },
    hasUnknowns: true,
    byteLength: 0,
  };
}

function populatedResult(): ExplainResult {
  return {
    ...emptyResult(),
    parsed: true,
    revisionId: "rev-7",
    savedStatus: "saved",
    metadata: {
      label: "Trend follow",
      packId: "trend-follow",
      version: "1.0.0",
      author: "krellbot tests",
      origin: "Test fixture.",
    },
    indicators: [{ name: "ema14", text: '"ema14" = ema of close over the last 14 bars', supported: true }],
    markets: [{ venue: "kraken", pair: "XBT/USD", supported: true, text: "kraken: XBT/USD" }],
  };
}

function installDownloadCapture() {
  const originalCreateElement = document.createElement.bind(document);
  const createObjectURL = vi
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:test-url");
  const revokeObjectURL = vi
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => {});
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const createElement = vi.spyOn(document, "createElement");
  const anchors: HTMLAnchorElement[] = [];
  createElement.mockImplementation(((tag: string) => {
    const element = originalCreateElement(tag);
    if (tag === "a" && element instanceof HTMLAnchorElement) {
      anchors.push(element);
    }
    return element;
  }) as typeof document.createElement);
  return {
    anchors,
    blobs: () => createObjectURL.mock.calls.map((call) => call[0] as Blob),
    restore: () => {
      click.mockRestore();
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
      createElement.mockRestore();
    },
  };
}

describe("StrategyExplanationCsvExport rendering", () => {
  it("renders the button disabled when the explanation carries no metadata", () => {
    render(<StrategyExplanationCsvExport result={emptyResult()} />);
    const button = screen.getByTestId(EXPORT_ID) as HTMLButtonElement;
    expect(button.textContent).toBe("Export explanation");
    expect(button.disabled).toBe(true);
  });

  it("renders the button disabled when explicitly disabled", () => {
    render(<StrategyExplanationCsvExport result={populatedResult()} disabled />);
    const button = screen.getByTestId(EXPORT_ID) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("renders the button enabled once metadata rows exist", () => {
    render(<StrategyExplanationCsvExport result={populatedResult()} />);
    const button = screen.getByTestId(EXPORT_ID) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });
});

describe("StrategyExplanationCsvExport download", () => {
  it("click builds a Blob containing the header plus metadata and indicator rows", async () => {
    const capture = installDownloadCapture();
    try {
      render(<StrategyExplanationCsvExport result={populatedResult()} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      const blobs = capture.blobs();
      expect(blobs.length).toBe(1);
      expect(blobs[0].type).toBe("text/csv;charset=utf-8");
      const csv = await blobs[0].text();
      expect(csv).toContain("section,key,value");
      expect(csv).toContain("metadata,label,Trend follow");
      expect(csv).toContain("indicator,ema14,");
      expect(csv).toContain("market,kraken XBT/USD,XBT/USD");
      const lines = csv.split("\r\n");
      expect(lines[0]).toBe("section,key,value");
      // 1 header + 5 metadata + 1 indicator + 1 market
      expect(lines.length).toBe(8);
    } finally {
      capture.restore();
    }
  });

  it("click produces no blob while disabled", () => {
    const capture = installDownloadCapture();
    try {
      render(<StrategyExplanationCsvExport result={emptyResult()} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(capture.blobs().length).toBe(0);
    } finally {
      capture.restore();
    }
  });

  it("uses the strategy-explanation-<timestamp>.csv filename pattern without colons", () => {
    const capture = installDownloadCapture();
    try {
      render(<StrategyExplanationCsvExport result={populatedResult()} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      const downloads = capture.anchors
        .map((anchor) => anchor.download)
        .filter((name) => name.startsWith("strategy-explanation-"));
      expect(downloads.length).toBe(1);
      expect(downloads[0]).toMatch(
        /^strategy-explanation-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.csv$/,
      );
    } finally {
      capture.restore();
    }
  });

  it("revokes the object URL after the download click", () => {
    const capture = installDownloadCapture();
    try {
      render(<StrategyExplanationCsvExport result={populatedResult()} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test-url");
    } finally {
      capture.restore();
    }
  });
});

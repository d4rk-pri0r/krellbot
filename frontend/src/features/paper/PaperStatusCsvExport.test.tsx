import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PaperStatusCsvExport } from "./PaperStatusCsvExport";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperStatus } from "./client";

const EXPORT_ID = "paper-status-csv-export";
const EXPECTED_HEADER = "schema_version,armed,venue,pair,entries_paused,mode,pack_id";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "btc,usd",
    mode: "paper",
    ...extra,
  };
}

function makeClient(status: PaperStatus): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue(status),
    pauseEntries: vi.fn().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ ok: true }),
    disarm: vi.fn().mockResolvedValue({ ok: true }),
  };
}

// jsdom neither resolves blob URLs nor follows anchor downloads, so both the
// blob contents and the anchor's download attribute are recorded manually.
type Captured = { filename: string; csvPromise: Promise<string> };

function captureDownloads(): { captured: Captured[]; restore: () => void } {
  const captured: Captured[] = [];
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const originalClick = HTMLAnchorElement.prototype.click;

  URL.createObjectURL = ((input: Blob | MediaSource): string => {
    captured.push({ filename: "", csvPromise: (input as Blob).text() });
    return "blob:mock";
  }) as typeof URL.createObjectURL;

  HTMLAnchorElement.prototype.click = function clickAnchor(
    this: HTMLAnchorElement,
  ): void {
    const last = captured[captured.length - 1];
    if (last) {
      last.filename = this.download;
    }
  };

  URL.revokeObjectURL = vi.fn();

  return {
    captured,
    restore: (): void => {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      HTMLAnchorElement.prototype.click = originalClick;
    },
  };
}

// Minimal RFC-4180 reader: handles quoted fields with doubled quotes so the
// tests round-trip the CSV the component actually emits.
function parseCsv(csv: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < csv.length; i += 1) {
    const char = csv[i];
    if (quoted) {
      if (char === '"') {
        if (csv[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

describe("PaperStatusCsvExport visibility", () => {
  it("renders nothing when status has armed=false", () => {
    render(<PaperStatusCsvExport status={{ schema_version: "1", armed: false }} />);
    expect(screen.queryByTestId(EXPORT_ID)).toBeNull();
    expect(screen.queryByText("Export CSV")).toBeNull();
  });

  it("StatusPanel does not mount the Export CSV button for an unarmed pack", async () => {
    render(<StatusPanel client={makeClient({ schema_version: "1", armed: false })} />);
    await waitFor(() => {
      expect(screen.getByTestId("paper-status-empty")).toBeTruthy();
    });
    expect(screen.queryByTestId(EXPORT_ID)).toBeNull();
    expect(screen.queryByText("Export CSV")).toBeNull();
  });

  it("renders the button enabled when paper controls are present", async () => {
    render(<StatusPanel client={makeClient(armedStatus())} />);
    const button = (await screen.findByTestId(EXPORT_ID)) as HTMLButtonElement;
    expect(button.textContent).toBe("Export CSV");
    expect(button.disabled).toBe(false);
  });

  it("button id is paper-status-csv-export exactly", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);
    const button = screen.getByTestId(EXPORT_ID) as HTMLButtonElement;
    expect(button.id).toBe(EXPORT_ID);
  });
});

describe("PaperStatusCsvExport download", () => {
  it("click produces a 2-line CSV (header + 1 row) with the exact header", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(
        <PaperStatusCsvExport
          status={armedStatus({ entries_paused: false, pack_id: "trend-follow" })}
        />,
      );
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(captured.length).toBe(1);
      const csv = await captured[0]!.csvPromise;
      const lines = csv.split("\n");
      expect(lines.length).toBe(2);
      expect(lines[0]).toBe(EXPECTED_HEADER);
      expect(csv.endsWith("\n")).toBe(false);

      const rows = parseCsv(csv);
      expect(rows.length).toBe(2);
      expect(rows[0]).toEqual([
        "schema_version",
        "armed",
        "venue",
        "pair",
        "entries_paused",
        "mode",
        "pack_id",
      ]);
      expect(rows[1]?.length).toBe(7);
      expect(rows[1]?.[0]).toBe("1");
      expect(rows[1]?.[1]).toBe("true");
      expect(rows[1]?.[2]).toBe("kraken");
      expect(rows[1]?.[3]).toBe("btc,usd");
      expect(rows[1]?.[4]).toBe("false");
      expect(rows[1]?.[5]).toBe("paper");
      expect(rows[1]?.[6]).toBe("trend-follow");
    } finally {
      restore();
    }
  });

  it("wraps a field containing a comma in double quotes and keeps the value intact", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(<PaperStatusCsvExport status={armedStatus({ pack_id: "abc, def" })} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      const csv = await captured[0]!.csvPromise;
      const lines = csv.split("\n");
      expect(lines.length).toBe(2);
      expect(lines[1]).toContain('"abc, def"');
      expect(parseCsv(csv)[1]?.[6]).toBe("abc, def");
    } finally {
      restore();
    }
  });

  it("doubles internal double quotes inside a quoted field", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(<PaperStatusCsvExport status={armedStatus({ pack_id: 'ab"c' })} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      const csv = await captured[0]!.csvPromise;
      expect(csv.split("\n")[1]).toContain('"ab""c"');
      expect(parseCsv(csv)[1]?.[6]).toBe('ab"c');
    } finally {
      restore();
    }
  });

  it("leaves fields with no comma, quote, or newline unquoted", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(
        <PaperStatusCsvExport
          status={armedStatus({
            pair: "SUIUSD",
            entries_paused: true,
            pack_id: "trend",
          })}
        />,
      );
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      const csv = await captured[0]!.csvPromise;
      expect(csv).not.toContain('"');
      expect(parseCsv(csv)[1]?.[4]).toBe("true");
    } finally {
      restore();
    }
  });

  it("empty optional fields render as empty cells (entries_paused undefined)", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(
        <PaperStatusCsvExport
          status={armedStatus({ entries_paused: undefined, pack_id: undefined })}
        />,
      );
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      const csv = await captured[0]!.csvPromise;
      const lines = csv.split("\n");
      expect(lines.length).toBe(2);
      expect(lines[1]).toBe('1,true,kraken,"btc,usd",,paper,');
      const rows = parseCsv(csv);
      expect(rows[1]?.length).toBe(7);
      expect(rows[1]?.[4]).toBe("");
      expect(rows[1]?.[6]).toBe("");
    } finally {
      restore();
    }
  });

  it("filename starts with krellbot-paper-status- and ends with .csv", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(<PaperStatusCsvExport status={armedStatus()} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(captured.length).toBe(1);
      const filename = captured[0]!.filename;
      expect(filename.startsWith("krellbot-paper-status-")).toBe(true);
      expect(filename.endsWith(".csv")).toBe(true);
      const stamp = filename.slice("krellbot-paper-status-".length, -".csv".length);
      expect(stamp).toMatch(/^\d{14}$/);
    } finally {
      restore();
    }
  });

  it("StatusPanel export click yields exactly one armed=true data row", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(<StatusPanel client={makeClient(armedStatus({ pack_id: "trend" }))} />);
      fireEvent.click(await screen.findByTestId(EXPORT_ID));
      expect(captured.length).toBe(1);
      const csv = await captured[0]!.csvPromise;
      const rows = parseCsv(csv);
      expect(rows.length).toBe(2);
      const dataRows = rows.slice(1);
      expect(dataRows.length).toBe(1);
      expect(dataRows[0]?.[1]).toBe("true");
      expect(dataRows[0]?.[1] === "").toBe(false);
      dataRows[0]?.forEach((cell) => {
        expect(typeof cell).toBe("string");
      });
    } finally {
      restore();
    }
  });
});

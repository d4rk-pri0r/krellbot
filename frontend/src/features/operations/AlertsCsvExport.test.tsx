import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsView } from "./OperationsView";
import type {
  AlertRow,
  OperationsClient,
  OperationsViewModel,
} from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function view(over: Partial<OperationsViewModel> = {}): OperationsViewModel {
  return {
    schema_version: "1",
    live: {
      schema_version: "1",
      live_enabled: false,
      authorized: [],
      kill_switch: { engaged: false, reason: null, engaged_at: null },
      promotion_available: false,
      promotion_code: "live_promotion_owner_deferred",
    },
    deployments: [],
    alerts: [],
    ...over,
  };
}

function makeClient(over: Partial<OperationsClient> = {}): OperationsClient {
  const v = view();
  return {
    getOperations: vi.fn().mockResolvedValue(v),
    promote: vi.fn().mockResolvedValue({ schema_version: "1", code: "live_disabled", ok: false }),
    pauseEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_paused", ok: true }),
    resumeEntries: vi.fn().mockResolvedValue({ schema_version: "1", code: "entries_resumed", ok: true }),
    engageKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_engaged", ok: true }),
    releaseKill: vi.fn().mockResolvedValue({ schema_version: "1", code: "kill_switch_released", ok: true }),
    ackAlert: vi.fn().mockResolvedValue({ schema_version: "1", code: "acknowledged", ok: true }),
    ...over,
  };
}

function alert(over: Partial<AlertRow> = {}): AlertRow {
  return {
    id: "abc123",
    kind: "live_refused",
    severity: "warning",
    code: "live_disabled",
    venue: "kraken",
    pair: "SUIUSD",
    count: 2,
    first_ts: 1700000000,
    last_ts: 1700000600,
    acknowledged: false,
    ...over,
  };
}

function expectedFields(row: AlertRow): string[] {
  return [
    row.id,
    row.kind,
    row.severity,
    row.code ?? "",
    row.venue ?? "",
    row.pair ?? "",
    String(row.count),
    String(row.first_ts),
    String(row.last_ts),
    row.acknowledged ? "true" : "false",
  ];
}

function splitCsvLines(text: string): string[] {
  return text.replace(/\n$/, "").split("\n");
}

// Minimal RFC-4180-shaped parser: handles quoted fields with embedded commas,
// doubled quotes, and newlines. No production dependency — tests only.
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"') {
      quoted = true;
      continue;
    }
    if (ch === ",") {
      row.push(field);
      field = "";
      continue;
    }
    if (ch === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      continue;
    }
    if (ch === "\r") {
      continue;
    }
    field += ch;
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

type Capture = {
  createObjectURL: ReturnType<typeof vi.fn>;
  revokeObjectURL: ReturnType<typeof vi.fn>;
  createElementSpy: ReturnType<typeof vi.spyOn>;
  anchors: HTMLAnchorElement[];
  texts: string[];
  restore(): void;
};

function stubDownload(): Capture {
  const createObjectURL = vi.fn<(input: Blob | MediaSource) => string>(
    () => "blob:ops-alerts-csv",
  );
  const revokeObjectURL = vi.fn();
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
  const anchors: HTMLAnchorElement[] = [];
  const texts: string[] = [];
  const realCreateElement = document.createElement.bind(document);
  const createElementSpy = vi.spyOn(document, "createElement").mockImplementation(
    ((tag: string) => {
      const el = realCreateElement(tag) as HTMLElement;
      if (tag.toLowerCase() === "a") {
        const anchor = el as HTMLAnchorElement;
        const originalClick = anchor.click.bind(anchor);
        anchor.click = () => {
          texts.push(String(createObjectURL.mock.calls.at(-1)?.[0] ?? new Blob()));
          return originalClick();
        };
        anchors.push(anchor);
      }
      return el as ReturnType<typeof document.createElement>;
    }) as typeof document.createElement,
  );
  return {
    createObjectURL,
    revokeObjectURL,
    createElementSpy,
    anchors,
    texts,
    restore() {
      createElementSpy.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    },
  };
}

function clickExport(): void {
  fireEvent.click(screen.getByTestId("ops-alerts-csv-export"));
}

describe("OperationsView alerts CSV export", () => {
  it("renders the export button (disabled) and empty-state message when there are no alerts", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alerts");
    const button = screen.getByTestId("ops-alerts-csv-export");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    const empty = screen.getByTestId("ops-alerts-csv-empty");
    expect(empty.textContent).toBe("No alerts to export.");
    const section = screen
      .getByTestId("ops-alerts")
      .closest('section[aria-label="Alerts"]');
    expect(section).not.toBeNull();
    expect(section!.contains(empty)).toBe(true);
    expect(section!.querySelectorAll('[data-testid="ops-alerts-csv-empty"]').length).toBe(1);
  });

  it("exports a 2-line CSV (header + row) with all 9 columns correct, quoting a venue that contains a comma", async () => {
    const row = alert({
      id: "a1",
      // venue with a comma forces RFC-4180 quoting in that field
      venue: "kraken,btc\"usd",
      severity: "critical",
      count: 7,
      acknowledged: true,
    });
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts: [row] })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-a1");
    expect(screen.getByTestId("ops-alerts-csv-export").hasAttribute("disabled")).toBe(false);

    const capture = stubDownload();
    try {
      clickExport();
      await waitFor(() => {
        expect(capture.createObjectURL).toHaveBeenCalledTimes(1);
      });
      const blob = capture.createObjectURL.mock.calls[0]?.[0] as Blob;
      const text = await blob.text();
      expect(blob.type).toBe("text/csv");
      expect(text).not.toContain("\r");

      const lines = splitCsvLines(text);
      expect(lines).toHaveLength(2);
      expect(lines[0]).toBe("id,kind,severity,code,venue,pair,count,first_ts,last_ts,acknowledged");
      const parsed = parseCsv(text);
      expect(parsed).toHaveLength(2);
      expect(parsed[0]).toEqual([
        "id",
        "kind",
        "severity",
        "code",
        "venue",
        "pair",
        "count",
        "first_ts",
        "last_ts",
        "acknowledged",
      ]);
      expect(parsed[1]).toEqual(expectedFields(row));
      // The comma-bearing venue must round-trip through the quotes.
      expect(parseCsv(text)[1][4]).toBe("kraken,btc\"usd");
      // The raw line must actually contain the quoted field with the doubled quote.
      expect(lines[1]).toContain("\"kraken,btc\"\"usd\"");
    } finally {
      capture.restore();
    }
  });

  it("exports 3 alerts as 4 lines and the parsed rows round-trip row-for-row", async () => {
    const rows = [
      alert({
        id: "r1",
        kind: "live_refused",
        code: "live_disabled",
        venue: "kraken",
        pair: "SUIUSD",
        count: 2,
        acknowledged: false,
      }),
      alert({
        id: "r2",
        kind: "paper_rejected",
        severity: "critical",
        code: null,
        venue: null,
        pair: null,
        count: 1,
        acknowledged: false,
      }),
      alert({
        id: "r3",
        kind: "reconcile_unknown",
        severity: "info",
        code: "unknown outcome, \"check\"",
        venue: "bitstamp",
        pair: "SUI,USD",
        count: 11,
        acknowledged: true,
      }),
    ];
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts: rows })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-r3");

    const capture = stubDownload();
    try {
      clickExport();
      await waitFor(() => {
        expect(capture.createObjectURL).toHaveBeenCalledTimes(1);
      });
      const text = await (capture.createObjectURL.mock.calls[0]?.[0] as Blob).text();
      expect(splitCsvLines(text)).toHaveLength(4);
      const parsed = parseCsv(text);
      expect(parsed).toHaveLength(4);
      expect(parsed[0]).toEqual([
        "id",
        "kind",
        "severity",
        "code",
        "venue",
        "pair",
        "count",
        "first_ts",
        "last_ts",
        "acknowledged",
      ]);
      expect(parsed.slice(1)).toEqual(rows.map(expectedFields));
    } finally {
      capture.restore();
    }
  });

  it("serializes acknowledged=false as the literal string 'false' and timestamps as integer epoch seconds", async () => {
    const row = alert({ id: "f1", acknowledged: false, first_ts: 1699999999, last_ts: 1700001234 });
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts: [row] })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-f1");

    const capture = stubDownload();
    try {
      clickExport();
      await waitFor(() => {
        expect(capture.createObjectURL).toHaveBeenCalledTimes(1);
      });
      const text = await (capture.createObjectURL.mock.calls[0]?.[0] as Blob).text();
      const parsed = parseCsv(text);
      expect(parsed[1][9]).toBe("false");
      expect(parsed[1][7]).toBe("1699999999");
      expect(parsed[1][8]).toBe("1700001234");
      expect(text).toContain("false");
      expect(text).not.toContain("False");
    } finally {
      capture.restore();
    }
  });

  it("names the download krellbot-alerts-<UTC yyyymmddHHMMSS>.csv via new Date().toISOString()", async () => {
    const client = makeClient({
      getOperations: vi.fn().mockResolvedValue(view({ alerts: [alert()] })),
    });
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alert-abc123");

    const before = new Date().toISOString();
    const capture = stubDownload();
    try {
      clickExport();
      await waitFor(() => {
        expect(capture.anchors.length).toBeGreaterThan(0);
      });
      const name = capture.anchors[0]!.download;
      expect(name.startsWith("krellbot-alerts-")).toBe(true);
      expect(name.endsWith(".csv")).toBe(true);
      const stamp = name.slice("krellbot-alerts-".length, name.length - ".csv".length);
      expect(stamp).toMatch(/^-?\d{14}$/);
      const after = new Date().toISOString();
      const pad = (n: number, w = 2) => String(Math.abs(n)).padStart(w, "0");
      const stampOf = (d: Date) =>
        `${pad(d.getUTCFullYear(), 4)}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}` +
        `${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}`;
      expect(Number(stamp)).toBeGreaterThanOrEqual(Number(stampOf(new Date(before))));
      expect(Number(stamp)).toBeLessThanOrEqual(Number(stampOf(new Date(after))));
    } finally {
      capture.restore();
    }
  });

  it("uses exactly the data-testid 'ops-alerts-csv-export' for the button", async () => {
    const client = makeClient();
    render(<OperationsView client={client} />);
    await screen.findByTestId("ops-alerts");
    expect(screen.getByTestId("ops-alerts-csv-export")).toBeDefined();
    expect(screen.getAllByTestId("ops-alerts-csv-export")).toHaveLength(1);
  });
});

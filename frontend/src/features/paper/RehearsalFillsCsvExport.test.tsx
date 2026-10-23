/**
 * RehearsalFillsCsvExport — unit coverage for the issue-106 export of the
 * fills currently read into the rehearsal panel's history list.
 *
 * The export must contain exactly the recent_fills rows the panel last
 * confirmed (coid, side, ts_ms and the qty/price strings as supplied —
 * numeric precision preserved byte-for-byte), carry an explicit
 * simulated-data provenance cell on every row, quote CSV metacharacters
 * correctly, neutralize spreadsheet-formula prefixes in the free-form
 * string fields, refuse to manufacture rows for an empty or unavailable
 * history, and never announce completion (or leave a reachable partial
 * download) when the export fails.
 *
 * Transport note: the rehearsal client here is an in-memory vi.fn() fake
 * standing in for the loopback rehearsal API; the fills are clearly
 * labeled simulated fixtures, never a claim about the backend. The real
 * downloaded-file-vs-paper-kraken.json comparison is the guarded J7.2
 * browser journey.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RehearsalPanel } from "./RehearsalPanel";
import { RehearsalFillsCsvExport, toRehearsalFillsCsv } from "./RehearsalFillsCsvExport";
import type {
  RehearsalClient,
  RehearsalCommandResult,
  RehearsalFill,
  RehearsalStatus,
} from "./rehearsalClient";

const EXPORT_ID = "rehearsal-fills-csv-export";
const ERROR_ID = "rehearsal-fills-csv-export-error";
const BUSY_ID = "rehearsal-fills-csv-export-busy-status";
const EXPECTED_HEADER = "coid,side,ts_ms,qty,price,provenance";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function fill(extra: Partial<RehearsalFill> = {}): RehearsalFill {
  return {
    coid: "coid-entry-1",
    side: "buy",
    qty: "1.50000000",
    price: "0.00004500",
    ts_ms: Date.UTC(2026, 9, 7, 9, 30, 5),
    kind: "fill",
    ...extra,
  };
}

function rehearsalStatus(extra: Partial<RehearsalStatus> = {}): RehearsalStatus {
  return {
    schema_version: "1",
    label: "SYNTHETIC PAPER REHEARSAL — simulated fixture, not market data",
    status: "paused",
    cursor: 3,
    total_bars: 20,
    balances: { USD: "984.25", SUI: "1.5" },
    position: "1.5",
    resting_stop: "0.42",
    recent_fills: [fill()],
    ...extra,
  };
}

function commandResult(
  status: Partial<RehearsalStatus>,
): RehearsalCommandResult {
  return {
    schema_version: "1",
    code: "ok",
    ok: true,
    message: "ok",
    status: rehearsalStatus(status),
  };
}

function makeRehearsalClient(
  overrides: Partial<RehearsalClient> = {},
): RehearsalClient {
  return {
    getStatus: vi.fn().mockResolvedValue(rehearsalStatus()),
    start: vi.fn().mockResolvedValue(commandResult({ status: "running", cursor: 1 })),
    pause: vi.fn().mockResolvedValue(commandResult({ status: "paused" })),
    resume: vi.fn().mockResolvedValue(commandResult({ status: "running", cursor: 2 })),
    exit: vi.fn().mockResolvedValue(commandResult({ status: "exited" })),
    stop: vi.fn().mockResolvedValue(commandResult({ status: "stopped" })),
    ...overrides,
  };
}

async function renderPanel(client: RehearsalClient) {
  render(<RehearsalPanel client={client} />);
  await waitFor(() => {
    expect(screen.getByTestId("rehearsal-fills-panel")).toBeTruthy();
  });
  return screen.getByTestId("rehearsal-fills-panel");
}

// jsdom neither resolves blob URLs nor follows anchor downloads, so both the
// blob contents and the anchor's download attribute are recorded manually.
type Captured = { filename: string; csvPromise: Promise<string> };

function captureDownloads(): {
  captured: Captured[];
  revoked: string[];
  restore: () => void;
} {
  const captured: Captured[] = [];
  const revoked: string[] = [];
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const originalClick = HTMLAnchorElement.prototype.click;

  URL.createObjectURL = ((input: Blob | MediaSource): string => {
    captured.push({ filename: "", csvPromise: (input as Blob).text() });
    return `blob:mock-${captured.length}`;
  }) as typeof URL.createObjectURL;

  HTMLAnchorElement.prototype.click = function clickAnchor(
    this: HTMLAnchorElement,
  ): void {
    const last = captured[captured.length - 1];
    if (last) {
      last.filename = this.download;
    }
  };

  URL.revokeObjectURL = ((url: string): void => {
    revoked.push(url);
  }) as typeof URL.revokeObjectURL;

  return {
    captured,
    revoked,
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

describe("RehearsalFillsCsvExport mount in the rehearsal fills panel", () => {
  it("renders one native button named 'Export visible fills' inside the rehearsal fills panel", async () => {
    const panel = await renderPanel(makeRehearsalClient());

    const button = within(panel).getByTestId(EXPORT_ID) as HTMLButtonElement;
    expect(button.tagName).toBe("BUTTON");
    expect(button.type).toBe("button");
    expect(button.textContent).toBe("Export visible fills");
    expect(button.disabled).toBe(false);
    expect(
      within(panel).getAllByRole("button", { name: /export visible fills/i }),
    ).toHaveLength(1);
  });

  it("keeps every rehearsal command control while the export is offered", async () => {
    await renderPanel(makeRehearsalClient());

    const commands = screen.getByTestId("rehearsal-commands-panel");
    expect(within(commands).getAllByRole("button").length).toBe(6);
    for (const id of [
      "rehearsal-command-start",
      "rehearsal-command-pause",
      "rehearsal-command-resume",
      "rehearsal-command-exit",
      "rehearsal-command-stop",
      "rehearsal-command-refresh",
    ]) {
      expect(within(commands).getByTestId(id)).toBeTruthy();
    }
  });

  it("offers no export while no rehearsal status has been confirmed", async () => {
    render(
      <RehearsalPanel
        client={makeRehearsalClient({
          getStatus: vi.fn().mockReturnValue(new Promise<RehearsalStatus>(() => {})),
        })}
      />,
    );
    expect(await screen.findByTestId("rehearsal-loading")).toBeTruthy();
    expect(screen.queryByTestId("rehearsal-fills-panel")).toBeNull();
    expect(screen.queryByTestId(EXPORT_ID)).toBeNull();
  });

  it("exports exactly the rows the panel is showing (same count and coids)", async () => {
    const fills = [
      fill({ coid: "coid-a", side: "buy", qty: "1.5", price: "0.45", ts_ms: 1001 }),
      fill({ coid: "coid-b", side: "sell", qty: "1.5", price: "0.5", ts_ms: 1002 }),
      fill({ coid: "coid-c", side: "buy", qty: "2.25", price: "0.44", ts_ms: 1003 }),
    ];
    const panel = await renderPanel(
      makeRehearsalClient({
        getStatus: vi.fn().mockResolvedValue(rehearsalStatus({ recent_fills: fills })),
      }),
    );
    expect(within(panel).getAllByTestId("rehearsal-fill")).toHaveLength(3);

    const { captured, restore } = captureDownloads();
    try {
      fireEvent.click(within(panel).getByTestId(EXPORT_ID));
      expect(captured).toHaveLength(1);
      const csv = await captured[0]!.csvPromise;
      const rows = parseCsv(csv);
      expect(rows.length - 1).toBe(fills.length);
      expect(within(panel).getAllByTestId("rehearsal-fill")).toHaveLength(
        rows.length - 1,
      );
      for (let i = 0; i < fills.length; i += 1) {
        expect(rows[i + 1]?.[0]).toBe(fills[i]!.coid);
      }
    } finally {
      restore();
    }
  });
});

describe("RehearsalFillsCsvExport CSV fidelity", () => {
  it("emits the exact header and one row per fill with ts_ms exact and qty/price as supplied", () => {
    const fills = [
      fill({
        coid: "coid-entry-1",
        side: "buy",
        qty: "1.50000000",
        price: "0.00004500",
        ts_ms: 1760121005000,
      }),
      fill({
        coid: "coid-exit-2",
        side: "sell",
        qty: "1.50000000",
        price: "0.00005000",
        ts_ms: 1760123700000,
      }),
    ];
    const csv = toRehearsalFillsCsv(fills);
    expect(csv.split("\n")[0]).toBe(EXPECTED_HEADER);

    const rows = parseCsv(csv);
    expect(rows[0]).toEqual([
      "coid",
      "side",
      "ts_ms",
      "qty",
      "price",
      "provenance",
    ]);
    expect(rows.length - 1).toBe(2);
    expect(rows[1]?.slice(0, 5)).toEqual([
      "coid-entry-1",
      "buy",
      "1760121005000",
      "1.50000000",
      "0.00004500",
    ]);
    expect(rows[2]?.slice(0, 5)).toEqual([
      "coid-exit-2",
      "sell",
      "1760123700000",
      "1.50000000",
      "0.00005000",
    ]);
  });

  it("carries an explicit simulated-data provenance cell on every row", () => {
    const csv = toRehearsalFillsCsv([fill(), fill({ coid: "coid-2" })]);
    const rows = parseCsv(csv);
    expect(rows[0]?.[5]).toBe("provenance");
    for (const row of rows.slice(1)) {
      expect(row?.[5]).toMatch(/simulated/i);
    }
  });

  it("preserves numeric precision of qty/price byte-for-byte (no reformatting)", () => {
    const qty = "1.50000000000000000012";
    const price = "0.00004500000000000007";
    const rows = parseCsv(toRehearsalFillsCsv([fill({ qty, price })]));
    expect(rows[1]?.[3]).toBe(qty);
    expect(rows[1]?.[4]).toBe(price);
  });

  it("downloads a krellbot-rehearsal-fills-*.csv file with that exact content on click", async () => {
    const fills = [fill(), fill({ coid: "coid-exit-2", side: "sell" })];
    const { captured, revoked, restore } = captureDownloads();
    try {
      render(<RehearsalFillsCsvExport fills={fills} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(captured).toHaveLength(1);
      const csv = await captured[0]!.csvPromise;
      expect(csv).toBe(toRehearsalFillsCsv(fills));
      const filename = captured[0]!.filename;
      expect(filename.startsWith("krellbot-rehearsal-fills-")).toBe(true);
      expect(filename.endsWith(".csv")).toBe(true);
      const stamp = filename.slice(
        "krellbot-rehearsal-fills-".length,
        -".csv".length,
      );
      expect(stamp).toMatch(/^\d{14}$/);
      expect(revoked).toEqual([`blob:mock-1`]);
    } finally {
      restore();
    }
  });

  it("announces completion only through the live region after a successful export", async () => {
    const { restore } = captureDownloads();
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      const busy = screen.getByTestId(BUSY_ID);
      expect(busy.getAttribute("role")).toBe("status");
      expect(busy.textContent).not.toMatch(/complete/i);
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      await waitFor(() => {
        expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
      });
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();
    } finally {
      restore();
    }
  });
});

describe("RehearsalFillsCsvExport CSV quoting", () => {
  it("wraps a coid containing a comma in double quotes and round-trips it", () => {
    const rows = parseCsv(toRehearsalFillsCsv([fill({ coid: "a,b" })]));
    expect(rows[1]?.[0]).toBe("a,b");
    expect(rows[1]?.length).toBe(6);
  });

  it("doubles internal double quotes inside a quoted coid", () => {
    const csv = toRehearsalFillsCsv([fill({ coid: 'ab"c' })]);
    const rows = parseCsv(csv);
    expect(rows[1]?.[0]).toBe('ab"c');
    expect(rows[1]?.length).toBe(6);
  });

  it("quotes a coid containing a newline and round-trips it", () => {
    const rows = parseCsv(toRehearsalFillsCsv([fill({ coid: "a\nb" })]));
    expect(rows[1]?.[0]).toBe("a\nb");
    expect(rows[1]?.length).toBe(6);
  });

  it("leaves fields with no comma, quote or newline unquoted", () => {
    const csv = toRehearsalFillsCsv([fill({ coid: "coid-entry-1" })]);
    const dataLine = csv.split("\n")[1] ?? "";
    expect(dataLine).not.toContain('"');
  });
});

describe("RehearsalFillsCsvExport spreadsheet-formula handling", () => {
  it("neutralizes a coid that starts with a formula character (=, +, -, @)", () => {
    const rows = parseCsv(
      toRehearsalFillsCsv([
        fill({ coid: "=SUM(A1:A9)" }),
        fill({ coid: "+1/0" }),
        fill({ coid: "-2+3" }),
        fill({ coid: "@cmd" }),
      ]),
    );
    expect(rows[1]?.[0]).toBe("'=SUM(A1:A9)");
    expect(rows[2]?.[0]).toBe("'+1/0");
    expect(rows[3]?.[0]).toBe("'-2+3");
    expect(rows[4]?.[0]).toBe("'@cmd");
  });

  it("neutralizes a side string that starts with a formula character", () => {
    const rows = parseCsv(toRehearsalFillsCsv([fill({ side: "=HYPERLINK(\"x\")" })]));
    expect(rows[1]?.[1]).toBe("'=HYPERLINK(\"x\")");
  });

  it("never alters benign strings or the numeric fields", () => {
    const rows = parseCsv(
      toRehearsalFillsCsv([fill({ coid: "coid-entry-1", side: "buy", qty: "1.5", price: "0.45" })]),
    );
    expect(rows[1]?.[0]).toBe("coid-entry-1");
    expect(rows[1]?.[1]).toBe("buy");
    expect(rows[1]?.[3]).toBe("1.5");
    expect(rows[1]?.[4]).toBe("0.45");
  });
});

describe("RehearsalFillsCsvExport empty and unavailable history", () => {
  it("disables the button and manufactures no rows or download when there are no fills", async () => {
    const { captured, restore } = captureDownloads();
    try {
      const panel = await renderPanel(
        makeRehearsalClient({
          getStatus: vi.fn().mockResolvedValue(rehearsalStatus({ recent_fills: [] })),
        }),
      );
      const button = within(panel).getByTestId(EXPORT_ID) as HTMLButtonElement;
      expect(button.disabled).toBe(true);
      expect(within(panel).getByTestId("rehearsal-fills-empty").textContent).toBe(
        "No simulated fills in this rehearsal yet",
      );
      fireEvent.click(button);
      expect(captured).toHaveLength(0);
      expect(screen.getByTestId(BUSY_ID).textContent).not.toMatch(/complete/i);
      expect(toRehearsalFillsCsv([]).split("\n").filter((line) => line.length > 0))
        .toEqual([EXPECTED_HEADER]);
    } finally {
      restore();
    }
  });

  it("renders nothing itself when there is no confirmed fill list at all", () => {
    const { container } = render(<RehearsalFillsCsvExport fills={[]} />);
    expect(screen.queryByTestId(ERROR_ID)).toBeNull();
    expect(container.querySelector("button")?.disabled ?? true).toBe(true);
  });
});

describe("RehearsalFillsCsvExport error handling", () => {
  it("a failing object URL shows an alert, never claims completion, and downloads nothing", async () => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const originalClick = HTMLAnchorElement.prototype.click;
    const click = vi.fn();
    const revoke = vi.fn();
    URL.createObjectURL = vi.fn(() => {
      throw new Error("no blob store");
    });
    URL.revokeObjectURL = revoke as typeof URL.revokeObjectURL;
    HTMLAnchorElement.prototype.click = click;
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));

      const error = screen.getByTestId(ERROR_ID);
      expect(error.getAttribute("role")).toBe("alert");
      expect(error.textContent).toMatch(/failed/i);
      expect(click).not.toHaveBeenCalled();
      expect(revoke).not.toHaveBeenCalled();
      const busy = screen.getByTestId(BUSY_ID).textContent ?? "";
      expect(busy).not.toMatch(/complete/i);
      expect(busy).toMatch(/failed|no file/i);
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      HTMLAnchorElement.prototype.click = originalClick;
    }
  });

  it("a failing anchor click revokes the object URL so no partial download is left reachable", async () => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const originalClick = HTMLAnchorElement.prototype.click;
    const revoke = vi.fn();
    URL.createObjectURL = vi.fn(() => "blob:mock-partial");
    URL.revokeObjectURL = revoke as typeof URL.revokeObjectURL;
    HTMLAnchorElement.prototype.click = function clickAnchor(): void {
      throw new Error("download denied");
    };
    try {
      render(<RehearsalFillsCsvExport fills={[fill()]} />);
      fireEvent.click(screen.getByTestId(EXPORT_ID));

      expect(screen.getByTestId(ERROR_ID).textContent).toMatch(/failed/i);
      expect(revoke).toHaveBeenCalledWith("blob:mock-partial");
      expect(screen.getByTestId(BUSY_ID).textContent ?? "").not.toMatch(
        /complete/i,
      );
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      HTMLAnchorElement.prototype.click = originalClick;
    }
  });

  it("recovers: a later successful click exports and announces completion", async () => {
    const failing = captureDownloads();
    URL.createObjectURL = vi.fn(() => {
      throw new Error("no blob store");
    });
    render(<RehearsalFillsCsvExport fills={[fill()]} />);
    fireEvent.click(screen.getByTestId(EXPORT_ID));
    expect(screen.getByTestId(ERROR_ID)).toBeTruthy();
    failing.restore();

    const ok = captureDownloads();
    try {
      fireEvent.click(screen.getByTestId(EXPORT_ID));
      expect(ok.captured).toHaveLength(1);
      await waitFor(() => {
        expect(screen.getByTestId(BUSY_ID).textContent).toMatch(/complete/i);
      });
      expect(screen.queryByTestId(ERROR_ID)).toBeNull();
    } finally {
      ok.restore();
    }
  });
});

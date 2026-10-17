import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TraceCsvExport } from "./TraceCsvExport";
import { ResearchView, type ResearchClient, type StoredResult } from "./ResearchView";

afterEach(cleanup);

function makeClient(overrides: Partial<ResearchClient> = {}): ResearchClient {
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-abc" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
    getJob: vi.fn().mockResolvedValue({ id: "job-abc", state: "succeeded" }),
    getResultDownload: vi.fn().mockResolvedValue(new Blob(["{}"])),
    ...overrides,
  };
}

function fillForm(): void {
  fireEvent.change(screen.getByLabelText(/dataset path/i), {
    target: { value: "fixtures/synthetic.csv" },
  });
  fireEvent.change(screen.getByLabelText(/fee basis points/i), { target: { value: "10" } });
  fireEvent.change(screen.getByLabelText(/^from$/i), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText(/^to$/i), { target: { value: "0" } });
}

type DownloadCapture = {
  anchor: HTMLAnchorElement | null;
  blob: Blob | null;
};

/**
 * jsdom has no real blob-URL support, so intercept the download
 * machinery: URL.createObjectURL captures the produced Blob and
 * document.createElement captures the synthetic anchor. Replacing
 * anchor.click keeps jsdom from attempting a navigation.
 */
function stubDownload(): { captured: () => DownloadCapture; restore: () => void } {
  const captured: DownloadCapture = { anchor: null, blob: null };
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = ((input: Blob | MediaSource): string => {
    if (input instanceof Blob) {
      captured.blob = input;
    }
    return "blob:trace-csv";
  }) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  const realCreateElement = document.createElement.bind(document);
  const createElementSpy = vi.spyOn(document, "createElement").mockImplementation(
    ((tag: string) => {
      const el = realCreateElement(tag) as HTMLElement;
      if (tag.toLowerCase() === "a") {
        const anchor = el as HTMLAnchorElement;
        captured.anchor = anchor;
        anchor.click = () => {
          /* capture happens on the element itself */
        };
      }
      return el as ReturnType<typeof document.createElement>;
    }) as typeof document.createElement,
  );
  return {
    captured: () => captured,
    restore: () => {
      createElementSpy.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    },
  };
}

async function loadTrace(
  trace: Array<Record<string, unknown>>,
  overrides: Partial<ResearchClient> = {},
): Promise<void> {
  const client = makeClient({
    getResult: vi.fn().mockResolvedValue({
      legacy_receipt: { equity: 0 },
      trace,
    } satisfies StoredResult),
    ...overrides,
  });
  render(<ResearchView client={client} />);
  fillForm();
  fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
  await screen.findByTestId("research-job-id");
  fireEvent.click(screen.getByRole("button", { name: /load result/i }));
  await screen.findByTestId("research-trace-scroll");
}

/** Parse the CSV dialect these tests produce (RFC4180 quoting, \n rows). */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i] ?? "";
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  // Only the final newline is an artifact; genuine empty rows survive.
  if (text.endsWith("\n")) {
    const last = rows[rows.length - 1];
    if (last && last.length === 1 && last[0] === "") {
      rows.pop();
    }
  }
  return rows;
}

async function exportAndGetCsv(): Promise<{ text: string; anchor: HTMLAnchorElement }> {
  const harness = stubDownload();
  try {
    fireEvent.click(screen.getByTestId("research-trace-csv-export"));
    await waitFor(() => {
      expect(harness.captured().blob).not.toBeNull();
      expect(harness.captured().anchor).not.toBeNull();
    });
    const text = await harness.captured().blob!.text();
    return { text, anchor: harness.captured().anchor! };
  } finally {
    harness.restore();
  }
}

describe("TraceCsvExport", () => {
  it("renders a disabled button and the empty-state message when the trace is empty", async () => {
    await loadTrace([]);
    const button = screen.getByTestId("research-trace-csv-export") as HTMLButtonElement;
    expect(button.tagName).toBe("BUTTON");
    expect(button.textContent).toBe("Export CSV");
    expect(button.disabled).toBe(true);
    const empty = screen.getByTestId("research-trace-csv-empty");
    expect(empty.textContent).toBe("No trace rows to export.");
    const tracePanel = screen.getByTestId("research-trace");
    expect(tracePanel.contains(empty)).toBe(true);
  });

  it("enables the button once the trace has rows", async () => {
    await loadTrace([{ bar_ts: 1 }]);
    const button = screen.getByTestId("research-trace-csv-export") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(screen.queryByTestId("research-trace-csv-empty")).toBeNull();
  });

  it("exports the sorted-unique key union: header + one row per trace row, empty cells for missing keys", async () => {
    const trace: Array<Record<string, unknown>> = [
      { bar_ts: 1, alpha: 0.5 },
      { bar_ts: 2, zeta: true, absent_elsewhere: null },
      { beta: "plain" },
    ];
    await loadTrace(trace);
    const { text, anchor } = await exportAndGetCsv();

    expect(anchor.download).toMatch(/^krellbot-trace-job-abc-\d{14}\.csv$/);
    expect(text).not.toMatch(/\r/);

    const rows = parseCsv(text);
    expect(rows.length).toBe(1 + trace.length);
    const header = rows[0] ?? [];
    expect(header).toEqual(["absent_elsewhere", "alpha", "bar_ts", "beta", "zeta"]);

    const at = (r: number, name: string): string => rows[r]?.[header.indexOf(name)] ?? "";
    expect(at(1, "bar_ts")).toBe("1");
    expect(at(1, "alpha")).toBe("0.5");
    expect(at(1, "beta")).toBe("");
    expect(at(1, "zeta")).toBe("");
    expect(at(1, "absent_elsewhere")).toBe("");
    expect(at(2, "bar_ts")).toBe("2");
    expect(at(2, "zeta")).toBe("true");
    expect(at(2, "absent_elsewhere")).toBe("");
    expect(at(3, "beta")).toBe("plain");
    expect(at(3, "bar_ts")).toBe("");

    // Round-trip: the parsed column set is exactly the key union.
    for (const row of rows.slice(1)) {
      expect(row.length).toBe(header.length);
    }
    const parsedColumns = new Set(header);
    const expectedUnion = new Set(trace.flatMap((row) => Object.keys(row)));
    expect(parsedColumns).toEqual(expectedUnion);
  });

  it("escapes cells containing comma, quote, or newline by quoting and doubling internal quotes", async () => {
    const tricky = 'he said "run", then\nstopped';
    await loadTrace([{ note: tricky, plain: "ok" }]);
    const { text } = await exportAndGetCsv();

    const lines = text.split("\n");
    expect(lines[0]).toBe("note,plain");
    // The escaped cell spans the embedded newline, so the trailing raw
    // text lines belong to a single logical CSV record.
    const record = lines.slice(1).join("\n").replace(/\n$/, "");
    expect(record).toBe('"he said ""run"", then\nstopped",ok');

    const rows = parseCsv(text);
    expect(rows.length).toBe(2);
    expect(rows[1]?.[0]).toBe(tricky);
    expect(rows[1]?.[1]).toBe("ok");
  });

  it("stringifies booleans and numbers plainly and null as an empty cell", async () => {
    await loadTrace([{ n: 42, b: false, s: "text", nil: null }]);
    const { text } = await exportAndGetCsv();
    const rows = parseCsv(text);
    expect(rows[0]).toEqual(["b", "n", "nil", "s"]);
    expect(rows[1]).toEqual(["false", "42", "", "text"]);
  });

  it("names the file with the loaded jobId, falling back to unk when absent", async () => {
    await loadTrace([{ a: 1 }]);
    const { anchor } = await exportAndGetCsv();
    expect(anchor.download).toMatch(/^krellbot-trace-job-abc-\d{14}\.csv$/);

    // Standalone render with no jobId uses the unk fallback.
    cleanup();
    const harness = stubDownload();
    try {
      render(<TraceCsvExport trace={[{ a: 1 }]} jobId={null} />);
      const button = screen.getByTestId("research-trace-csv-export") as HTMLButtonElement;
      expect(button.disabled).toBe(false);
      fireEvent.click(button);
      await waitFor(() => {
        expect(harness.captured().anchor).not.toBeNull();
      });
      expect(harness.captured().anchor!.download).toMatch(
        /^krellbot-trace-unk-\d{14}\.csv$/,
      );
    } finally {
      harness.restore();
    }
  });

  it("exposes exactly the research-trace-csv-export test id on the button", async () => {
    await loadTrace([]);
    const button = screen.getByTestId("research-trace-csv-export");
    expect(button.getAttribute("data-testid")).toBe("research-trace-csv-export");
    expect(button.tagName).toBe("BUTTON");
    expect(button.id).not.toBe("research-trace-csv-export");
  });

  it("does not crash on malformed (null) rows in the trace array", async () => {
    // Rendered standalone: ResearchView's windowed list is out of scope
    // here; this asserts the exporter itself survives a null row.
    const trace = [null, { a: 1 }] as unknown as Array<Record<string, unknown>>;
    const harness = stubDownload();
    try {
      render(<TraceCsvExport trace={trace} jobId="job-x" />);
      fireEvent.click(screen.getByTestId("research-trace-csv-export"));
      await waitFor(() => {
        expect(harness.captured().blob).not.toBeNull();
      });
      const text = await harness.captured().blob!.text();
      const rows = parseCsv(text);
      expect(rows.length).toBe(3);
      expect(rows[0]).toEqual(["a"]);
      expect(rows[1]).toEqual([""]);
      expect(rows[2]).toEqual(["1"]);
    } finally {
      harness.restore();
    }
  });
});


import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PaperStatusCsvExport } from "./PaperStatusCsvExport";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperStatus } from "./client";

const here = dirname(fileURLToPath(import.meta.url));

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

describe("PaperStatusCsvExport Signal presentation", () => {
  it("renders the Seafoam 'Local preview' badge above the Export CSV button for an armed paper status", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);

    const badge = screen.getByTestId("paper-status-csv-local-preview");
    expect(badge.textContent).toBe("Local preview");

    const button = screen.getByTestId(EXPORT_ID) as HTMLButtonElement;
    // The badge sits inside the same scoped wrapper and precedes the button.
    const wrapper = button.closest(".kbot-feature__paper-csv-root");
    expect(wrapper).not.toBeNull();
    expect(wrapper!.contains(badge)).toBe(true);
    expect(badge.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("hides the badge in the same branches that hide the button (null status, armed=false)", () => {
    const { unmount } = render(<PaperStatusCsvExport status={null} />);
    expect(screen.queryByTestId(EXPORT_ID)).toBeNull();
    expect(screen.queryByTestId("paper-status-csv-local-preview")).toBeNull();
    expect(screen.queryByText("Local preview")).toBeNull();
    unmount();

    render(<PaperStatusCsvExport status={{ schema_version: "1", armed: false }} />);
    expect(screen.queryByTestId(EXPORT_ID)).toBeNull();
    expect(screen.queryByTestId("paper-status-csv-local-preview")).toBeNull();
    expect(screen.queryByText("Local preview")).toBeNull();
  });

  it("renders the badge from the armed StatusPanel mount and still produces the same CSV on click", async () => {
    render(<StatusPanel client={makeClient(armedStatus({ pack_id: "trend" }))} />);
    const button = (await screen.findByTestId(EXPORT_ID)) as HTMLButtonElement;
    expect(screen.getByTestId("paper-status-csv-local-preview").textContent).toBe(
      "Local preview",
    );
    expect(button.closest(".kbot-feature__paper-csv-root")).not.toBeNull();

    const { captured, restore } = captureDownloads();
    try {
      fireEvent.click(button);
      expect(captured.length).toBe(1);
      const csv = await captured[0]!.csvPromise;
      expect(csv.split("\n")[0]).toBe(EXPECTED_HEADER);
      expect(csv.split("\n")[1]?.split(",")[0]).toBe("1");
    } finally {
      restore();
    }
  });

  it("keeps the button's id, label and existing kbot-paper-status__action class while adding the scoped class", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);

    const button = screen.getByTestId(EXPORT_ID) as HTMLButtonElement;
    expect(button.id).toBe("paper-status-csv-export");
    expect(button.textContent).toBe("Export CSV");
    expect(button.className).toContain("kbot-paper-status__action");
    expect(button.className).toContain("kbot-feature__paper-csv-root__action");
  });

  it("ships scoped Signal chrome under .kbot-feature__paper-csv-root with shared tokens only", () => {
    const raw = readFileSync(join(here, "PaperStatusCsvExport.signal.css"), "utf8");
    // Comments between rules would otherwise prefix the selector text.
    const css = raw.replace(/\/\*[\s\S]*?\*\//g, "");

    // Every rule is scoped under the single feature root.
    for (const selector of css.split("}").map((rule) => rule.split("{")[0] ?? "")) {
      const trimmed = selector.trim();
      if (trimmed.length > 0 && !trimmed.startsWith("@media")) {
        expect(trimmed.startsWith(".kbot-feature__paper-csv-root")).toBe(true);
      }
    }

    // Button surface: seafoam accent when armed/idle, sage when hovered/active.
    const actionCss = css;
    expect(actionCss).toMatch(
      /\.kbot-feature__paper-csv-root[^{]*__action[^{]*\{[^}]*var\(--seafoam/,
    );
    expect(actionCss).toMatch(
      /\.kbot-feature__paper-csv-root[^{]*__action:hover[^{]*\{[^}]*var\(--sage/,
    );
    expect(actionCss).toMatch(
      /\.kbot-feature__paper-csv-root[^{]*__action:active[^{]*\{[^}]*var\(--sage/,
    );

    // 44px tap target on small viewports, focus-visible ring, badge chrome.
    expect(css).toMatch(/@media[^{]*640px[^{]*\{[\s\S]*?min-height:\s*44px/);
    expect(css).toMatch(
      /\.kbot-feature__paper-csv-root[^{]*:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--seafoam/,
    );
    expect(css).toMatch(
      /\.kbot-feature__paper-csv-root[^{]*__badge[^{]*\{[^}]*var\(--seafoam/,
    );
    expect(css).toMatch(/var\(--font-ui,/);

    // Shared tokens only: no new palette, nothing remote, no retired hues.
    expect(css).not.toMatch(/@import|https?:\/\//);
    for (const retired of ["#5ce1ff", "#c6ff3d", "#07090d", "#72f6b0"]) {
      expect(css.toLowerCase()).not.toContain(retired);
    }
    const approved = new Set([
      "#0e1c29",
      "#14222e",
      "#18354a",
      "#22465d",
      "#e9f0f5",
      "#abc4d8",
      "#a8d8d1",
      "#b3dda8",
      "#cc9689",
      "#172a1d",
    ]);
    const hexes = css.toLowerCase().match(/#[0-9a-f]{6}\b/g) ?? [];
    for (const hex of hexes) {
      expect(approved.has(hex)).toBe(true);
    }
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

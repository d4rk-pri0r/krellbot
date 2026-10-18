import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PaperStatusCsvExport } from "./PaperStatusCsvExport";
import { StatusPanel } from "./StatusPanel";
import type { PaperClient, PaperStatus } from "./client";

const here = dirname(fileURLToPath(import.meta.url));

const EXPORT_TESTID = "paper-status-csv-export";
const BADGE_TESTID = "paper-status-csv-local-preview";
const ROOT_SCOPE = "kbot-feature__paper-csv-root";

const cssSource = readFileSync(join(here, "PaperStatusCsvExport.signal.css"), "utf8");

/**
 * KRELL-SIGNAL-20261010 paper-status CSV export presentation slice.
 *
 * These tests pin the approved scoped Signal vocabulary the mounted
 * armed-paper "Export CSV" affordance actually renders with —
 * .kbot-feature__paper-csv-root / __meta / __badge / __action — against
 * the existing data-testid contract (paper-status-csv-local-preview,
 * paper-status-csv-export) and the existing null-status / unarmed /
 * non-paper-mode early-return semantics. The download contract (the
 * toPaperStatusCsv() body, exportTimestamp(), downloadCsv(), the
 * krellbot-paper-status-<UTC compact stamp>.csv filename and the
 * text/csv;charset=utf-8 Blob MIME) is pinned as-is; nothing here asks
 * for a component change. Every client is an in-memory vi.fn() fake
 * standing in for the loopback paper API; no real venue/engine state,
 * keys, orders or fills are exercised or implied.
 */

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function armedStatus(extra: Partial<PaperStatus> = {}): PaperStatus {
  return {
    schema_version: "1",
    armed: true,
    venue: "kraken",
    pair: "SUIUSD",
    entries_paused: false,
    mode: "paper",
    pack_id: "trend-follow",
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

// jsdom neither resolves blob URLs nor follows anchor downloads, so the
// blob MIME, the blob contents and the anchor's download attribute are
// recorded manually (same technique as PaperStatusCsvExport.test.tsx).
type Captured = { filename: string; blobType: string; csvPromise: Promise<string> };

function captureDownloads(): { captured: Captured[]; restore: () => void } {
  const captured: Captured[] = [];
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const originalClick = HTMLAnchorElement.prototype.click;

  URL.createObjectURL = ((input: Blob | MediaSource): string => {
    const blob = input as Blob;
    captured.push({ filename: "", blobType: blob.type, csvPromise: blob.text() });
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

function scopedRoots(): HTMLElement[] {
  return Array.from(document.querySelectorAll(`.${ROOT_SCOPE}`));
}

describe("PaperStatusCsvExport Signal presentation", () => {
  it("renders the scoped Signal root wrapping the existing badge and export testids for an armed paper status", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);

    const badge = screen.getByTestId(BADGE_TESTID);
    const button = screen.getByTestId(EXPORT_TESTID);

    const roots = scopedRoots();
    expect(roots.length).toBe(1);
    const root = roots[0] as HTMLElement;
    expect(root.getAttribute("class")).toBe(ROOT_SCOPE);
    expect(badge.closest(`.${ROOT_SCOPE}`)).toBe(root);
    expect(button.closest(`.${ROOT_SCOPE}`)).toBe(root);
    // The badge row sits above the button inside the same scoped wrapper.
    expect(badge.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the Local preview badge in the scoped meta row with the scoped badge class", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);

    const badge = screen.getByTestId(BADGE_TESTID);
    expect(badge.textContent).toBe("Local preview");
    expect(badge.getAttribute("class")).toBe("kbot-feature__paper-csv-root__badge");

    const meta = badge.closest(".kbot-feature__paper-csv-root__meta");
    expect(meta).not.toBeNull();
    expect(meta?.tagName).toBe("P");
    expect(meta?.getAttribute("class")).toBe("kbot-feature__paper-csv-root__meta");
  });

  it("carries the scoped action class on the button alongside the existing kbot-paper-status__action class", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);

    const button = screen.getByTestId(EXPORT_TESTID) as HTMLButtonElement;
    expect(button.getAttribute("class")).toBe(
      "kbot-paper-status__action kbot-feature__paper-csv-root__action",
    );
    expect(button.className).toContain("kbot-paper-status__action");
    expect(button.className).toContain("kbot-feature__paper-csv-root__action");
    expect(button.id).toBe("paper-status-csv-export");
    expect(button.getAttribute("type")).toBe("button");
    expect(button.textContent).toBe("Export CSV");
    expect(button.disabled).toBe(false);
  });

  it("returns null for status=null: no scoped root, no badge, no export button", () => {
    const { container } = render(<PaperStatusCsvExport status={null} />);
    expect(screen.queryByTestId(EXPORT_TESTID)).toBeNull();
    expect(screen.queryByTestId(BADGE_TESTID)).toBeNull();
    expect(screen.queryByText("Local preview")).toBeNull();
    expect(scopedRoots().length).toBe(0);
    expect(container.firstChild).toBeNull();
  });

  it("returns null in every early-return branch (unarmed, non-paper mode, missing venue, missing pair)", () => {
    const { unmount } = render(
      <PaperStatusCsvExport status={{ schema_version: "1", armed: false }} />,
    );
    expect(screen.queryByTestId(EXPORT_TESTID)).toBeNull();
    expect(scopedRoots().length).toBe(0);
    unmount();

    render(<PaperStatusCsvExport status={armedStatus({ mode: "live" })} />);
    expect(screen.queryByTestId(EXPORT_TESTID)).toBeNull();
    expect(scopedRoots().length).toBe(0);
    unmount();

    render(<PaperStatusCsvExport status={armedStatus({ venue: undefined })} />);
    expect(screen.queryByTestId(EXPORT_TESTID)).toBeNull();
    expect(scopedRoots().length).toBe(0);
    unmount();

    render(<PaperStatusCsvExport status={armedStatus({ pair: undefined })} />);
    expect(screen.queryByTestId(EXPORT_TESTID)).toBeNull();
    expect(scopedRoots().length).toBe(0);
  });

  it("StatusPanel mounts the scoped slice for an armed paper status without disturbing sibling controls", async () => {
    render(<StatusPanel client={makeClient(armedStatus())} />);

    const button = (await screen.findByTestId(EXPORT_TESTID)) as HTMLButtonElement;
    expect(button.closest(`.${ROOT_SCOPE}`)).not.toBeNull();
    expect(screen.getByTestId(BADGE_TESTID).textContent).toBe("Local preview");
    // Sibling paper controls keep rendering in the same actions row.
    const siblings = document.querySelectorAll(".kbot-paper-status__action");
    expect(siblings.length).toBeGreaterThanOrEqual(1);
  });

  it("StatusPanel unarmed mount renders the empty sibling line and no scoped CSV slice", async () => {
    render(
      <StatusPanel client={makeClient({ schema_version: "1", armed: false })} />,
    );

    expect(await screen.findByTestId("paper-status-empty")).toBeDefined();
    expect(screen.queryByTestId(EXPORT_TESTID)).toBeNull();
    expect(screen.queryByTestId(BADGE_TESTID)).toBeNull();
    expect(scopedRoots().length).toBe(0);
  });

  it("StatusPanel loading mount (status=null initial state) keeps the loading sibling line and no scoped CSV slice", () => {
    const client = {
      getStatus: vi.fn().mockImplementation(() => new Promise<PaperStatus>(() => {})),
      pauseEntries: vi.fn(),
      resumeEntries: vi.fn(),
      disarm: vi.fn(),
    } as unknown as PaperClient;
    render(<StatusPanel client={client} />);

    expect(screen.getByTestId("paper-status-loading")).toBeDefined();
    expect(screen.queryByTestId(EXPORT_TESTID)).toBeNull();
    expect(scopedRoots().length).toBe(0);
  });

  it("keeps the krellbot-paper-status-<UTC compact stamp>.csv filename and text/csv;charset=utf-8 MIME on click", async () => {
    const { captured, restore } = captureDownloads();
    try {
      render(<PaperStatusCsvExport status={armedStatus()} />);
      fireEvent.click(screen.getByTestId(EXPORT_TESTID));
      expect(captured.length).toBe(1);
      expect(captured[0]!.filename).toMatch(/^krellbot-paper-status-\d{14}\.csv$/);
      expect(captured[0]!.blobType).toBe("text/csv;charset=utf-8");
      const csv = await captured[0]!.csvPromise;
      expect(csv.split("\n")[0]).toBe(
        "schema_version,armed,venue,pair,entries_paused,mode,pack_id",
      );
    } finally {
      restore();
    }
  });

  it("scopes every stylesheet rule under the Signal paper-csv root", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);
    expect(screen.getByTestId(BADGE_TESTID).closest(`.${ROOT_SCOPE}`)).not.toBeNull();

    const selectors =
      cssSource
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .match(/([^{}]+)\{/g)
        ?.map((rule) => rule.slice(0, -1).trim())
        .filter((selector) => selector.length > 0 && !selector.startsWith("@")) ?? [];
    expect(selectors.length).toBeGreaterThan(5);
    for (const selector of selectors) {
      expect(selector.startsWith(`.${ROOT_SCOPE}`)).toBe(true);
    }
    for (const scoped of [
      ".kbot-feature__paper-csv-root .kbot-feature__paper-csv-root__meta",
      ".kbot-feature__paper-csv-root .kbot-feature__paper-csv-root__badge",
      ".kbot-feature__paper-csv-root .kbot-feature__paper-csv-root__action",
      ".kbot-feature__paper-csv-root .kbot-feature__paper-csv-root__action:focus-visible",
    ]) {
      expect(cssSource.includes(scoped)).toBe(true);
    }
    // 44px tap target on small viewports.
    expect(cssSource).toContain("@media (max-width: 640px)");
    expect(cssSource).toMatch(/min-height:\s*44px/);
  });

  it("keeps only the approved Signal vocabulary tokens in the stylesheet", () => {
    render(<PaperStatusCsvExport status={armedStatus()} />);
    expect(screen.getByTestId(EXPORT_TESTID)).toBeDefined();

    expect(cssSource).toContain("var(--seafoam, #a8d8d1)");
    expect(cssSource).toContain("var(--sage, #b3dda8)");
    expect(cssSource).toContain('var(--font-ui, "Manrope"');
    expect(cssSource).not.toMatch(/@import|https?:\/\//);
    for (const retired of ["#5ce1ff", "#c6ff3d", "#07090d", "#72f6b0"]) {
      expect(cssSource.toLowerCase()).not.toContain(retired);
    }
  });
});

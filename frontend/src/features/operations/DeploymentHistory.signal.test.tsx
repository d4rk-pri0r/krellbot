import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DeploymentHistory } from "./DeploymentHistory";
import type { DeploymentRecordRow, OperationsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const cssSource = readFileSync(
  resolve(__dirname, "DeploymentHistory.signal.css"),
  "utf8",
);

/**
 * KRELL-SIGNAL-20261010 deployment-history presentation layer.
 *
 * These tests pin the scoped Signal vocabulary the mounted history list
 * actually renders with (component-root `.kbot-ops__history`, nested
 * `.kbot-ops__history <element>` rules) against the existing data-testid
 * contract and the existing fetch / loading / empty / error / row
 * semantics. Every client here is an in-memory vi.fn() fake standing in
 * for the loopback operations API; no real deployment history, orders,
 * or venue state is exercised or implied.
 */

const LOADING_TEXT = "Loading deployments…";
const EMPTY_TEXT = "No deployments yet. Local preview only — live trading unavailable.";
const LIST_ERROR_PREFIX = "Could not load deployments — check the workstation is running.";
const LOCAL_PREVIEW_BADGE = "Local preview";
const TITLE_TEXT = "Deployment history";

function record(over: Partial<DeploymentRecordRow> = {}): DeploymentRecordRow {
  return {
    deployment_id: "dep-1",
    venue: "kraken",
    pair: "SUIUSD",
    created_at_ms: 1_700_000_010_000,
    state: "paper",
    config: {},
    schedule: {},
    last_execution_summary: "",
    ...over,
  };
}

function makeClient(
  over: Partial<Pick<OperationsClient, "listDeploymentRecords" | "getDeploymentRecord">> = {},
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

function scopedRoot(): HTMLElement {
  const roots = document.querySelectorAll(".kbot-ops__history");
  expect(roots.length).toBe(1);
  return roots[0] as HTMLElement;
}

describe("DeploymentHistory Signal presentation", () => {
  it("mounts the scoped Signal root class instead of an unscoped generic root", async () => {
    const client = makeClient({ listDeploymentRecords: vi.fn().mockResolvedValue([]) });
    render(<DeploymentHistory client={client} />);
    await screen.findByTestId("ops-history-empty");
    const root = scopedRoot();
    expect(root.getAttribute("class")).toBe("kbot-ops__history");
    expect(screen.getByTestId("ops-history-preview-badge").closest(".kbot-ops__history")).toBe(
      root,
    );
  });

  it("keeps the head row, panel title, and Local preview badge under the scoped root", async () => {
    const client = makeClient({ listDeploymentRecords: vi.fn().mockResolvedValue([]) });
    render(<DeploymentHistory client={client} />);
    const badge = await screen.findByTestId("ops-history-preview-badge");
    const head = badge.closest(".kbot-ops__history-head");
    expect(head).not.toBeNull();
    expect(head?.closest(".kbot-ops__history")).toBe(scopedRoot());
    const title = head?.querySelector(".kbot-ops__panel-title");
    expect(title?.tagName).toBe("H3");
    expect(title?.textContent).toBe(TITLE_TEXT);
    expect(badge.getAttribute("class")).toContain("kbot-ops__preview-badge");
    expect(badge.textContent).toBe(LOCAL_PREVIEW_BADGE);
  });

  it("renders the loading line in the scoped empty class while the first read is in flight", () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockImplementation(
        () => new Promise<DeploymentRecordRow[]>(() => {}),
      ),
    });
    render(<DeploymentHistory client={client} />);
    const loading = screen.getByTestId("ops-history-loading");
    expect(loading.textContent).toBe(LOADING_TEXT);
    expect(loading.getAttribute("class")).toBe("kbot-ops__empty");
    expect(loading.closest(".kbot-ops__history")).toBe(scopedRoot());
  });

  it("renders the honest empty state in the scoped empty class with the badge still visible", async () => {
    const client = makeClient({ listDeploymentRecords: vi.fn().mockResolvedValue([]) });
    render(<DeploymentHistory client={client} />);
    const empty = await screen.findByTestId("ops-history-empty");
    expect(empty.textContent).toBe(EMPTY_TEXT);
    expect(empty.getAttribute("class")).toBe("kbot-ops__empty");
    expect(screen.getByTestId("ops-history-preview-badge").textContent).toBe(LOCAL_PREVIEW_BADGE);
  });

  it("renders the records in the scoped table with the id, venue, pair, created, and state columns", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([
        record(),
        record({ deployment_id: "dep-2", venue: "coinbase", pair: "BTC-USD", state: "paused" }),
      ]),
    });
    render(<DeploymentHistory client={client} />);
    const row1 = await screen.findByTestId("ops-history-row-dep-1");
    const table = row1.closest("table");
    expect(table?.getAttribute("class")).toBe("kbot-ops__table");
    expect(table?.getAttribute("data-testid")).toBe("ops-history-table");
    expect(table?.closest(".kbot-ops__history")).toBe(scopedRoot());
    expect(
      within(table as HTMLElement)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Deployment", "Venue", "Pair", "Created", "State"]);
    expect(row1.querySelectorAll("td")[1]?.textContent).toBe("kraken");
    expect(row1.textContent).toContain("dep-1");
    expect(row1.textContent).toContain("SUIUSD");
    expect(row1.textContent).toContain("2023-11-14 22:13:30");
    expect(row1.textContent).toContain("paper");
    const row2 = screen.getByTestId("ops-history-row-dep-2");
    expect(row2.querySelectorAll("td")[1]?.textContent).toBe("coinbase");
    expect(row2.textContent).toContain("paused");
  });

  it("carries the expanded-row seafoam selection affordance on the scoped row selector", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord: vi.fn().mockResolvedValue(record()),
    });
    render(<DeploymentHistory client={client} />);
    const row = await screen.findByTestId("ops-history-row-dep-1");
    expect(row.matches('tr[data-testid^="ops-history-row-"]')).toBe(true);
    fireEvent.click(row);
    const detail = await screen.findByTestId("ops-history-detail-dep-1");
    expect(row.getAttribute("aria-expanded")).toBe("true");
    expect(row.matches('tr[data-testid^="ops-history-row-"][aria-expanded="true"]')).toBe(true);
    expect(detail.getAttribute("class")).toBe("kbot-ops__history-detail");
    expect(detail.closest("table")).toBe(row.closest("table"));
    fireEvent.click(screen.getByTestId("ops-history-row-dep-1"));
    await waitFor(() => expect(screen.queryByTestId("ops-history-detail-dep-1")).toBeNull());
    expect(row.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps the detail loading line in the scoped empty class", async () => {
    let releaseDetail: ((value: DeploymentRecordRow) => void) | undefined;
    const getDeploymentRecord = vi.fn().mockImplementation(
      () =>
        new Promise<DeploymentRecordRow>((resolve_) => {
          releaseDetail = resolve_;
        }),
    );
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord,
    });
    render(<DeploymentHistory client={client} />);
    fireEvent.click(await screen.findByTestId("ops-history-row-dep-1"));
    const detailLoading = await screen.findByTestId("ops-history-detail-loading");
    expect(detailLoading.getAttribute("class")).toBe("kbot-ops__empty");
    expect(detailLoading.closest(".kbot-ops__history-detail")).not.toBeNull();
    releaseDetail?.(record());
    await waitFor(() => expect(screen.queryByTestId("ops-history-detail-loading")).toBeNull());
  });

  it("keeps the detail refusal line in the scoped caution result class", async () => {
    const client = makeClient({
      listDeploymentRecords: vi.fn().mockResolvedValue([record()]),
      getDeploymentRecord: vi.fn().mockRejectedValue(
        new Error("deployment history failed: 404 deployment_not_found"),
      ),
    });
    render(<DeploymentHistory client={client} />);
    fireEvent.click(await screen.findByTestId("ops-history-row-dep-1"));
    const detailError = await screen.findByTestId("ops-history-detail-error");
    expect(detailError.getAttribute("role")).toBe("alert");
    expect(detailError.getAttribute("class")).toBe("kbot-ops__row-result");
    expect(detailError.closest(".kbot-ops__history-detail")).not.toBeNull();
    expect(detailError.textContent).toContain("deployment history failed: 404 deployment_not_found");
  });

  it("keeps the list failure in the caution result class with the scoped inline Retry", async () => {
    const listDeploymentRecords = vi
      .fn<() => Promise<DeploymentRecordRow[]>>()
      .mockRejectedValueOnce(new Error("deployment history failed: 403 session required"))
      .mockResolvedValueOnce([record()]);
    const client = makeClient({ listDeploymentRecords });
    render(<DeploymentHistory client={client} />);
    const error = await screen.findByTestId("ops-history-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.getAttribute("class")).toBe("kbot-ops__row-result");
    expect(error.closest(".kbot-ops__history")).toBe(scopedRoot());
    expect(error.textContent).toContain(LIST_ERROR_PREFIX);
    expect(error.textContent).toContain("deployment history failed: 403 session required");
    expect(screen.queryByTestId("ops-history-table")).toBeNull();
    const retry = screen.getByTestId("ops-history-retry");
    expect(retry.getAttribute("class")).toBe("kbot-ops__retry");
    fireEvent.click(retry);
    await screen.findByTestId("ops-history-row-dep-1");
    expect(screen.queryByTestId("ops-history-error")).toBeNull();
  });

  it("scopes every stylesheet rule under the Signal history root", () => {
    const selectors = cssSource
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .match(/([^{}]+)\{/g)
      ?.map((rule) => rule.slice(0, -1).trim())
      .filter((selector) => selector.length > 0 && !selector.startsWith("@")) ?? [];
    expect(selectors.length).toBeGreaterThan(10);
    for (const selector of selectors) {
      expect(selector.startsWith(".kbot-ops__history")).toBe(true);
    }
    for (const scoped of [
      ".kbot-ops__history .kbot-ops__history-head",
      ".kbot-ops__history .kbot-ops__history-head .kbot-ops__panel-title",
      ".kbot-ops__history .kbot-ops__preview-badge",
      ".kbot-ops__history .kbot-ops__empty",
      ".kbot-ops__history .kbot-ops__table",
      ".kbot-ops__history .kbot-ops__row-result",
      ".kbot-ops__history .kbot-ops__retry",
      ".kbot-ops__history .kbot-ops__history-detail",
      ".kbot-ops__history .kbot-ops__history-facts",
      '.kbot-ops__history tr[data-testid^="ops-history-row-"]',
      '.kbot-ops__history tr[data-testid^="ops-history-row-"][aria-expanded="true"]',
    ]) {
      expect(cssSource.includes(scoped)).toBe(true);
    }
  });

  it("keeps the approved Signal vocabulary in the stylesheet tokens", () => {
    expect(cssSource).toContain('var(--font-ui, "Manrope"');
    expect(cssSource).toContain('var(--font-mono, "IBM Plex Mono"');
    expect(cssSource).toContain("var(--seafoam, #a8d8d1)");
    expect(cssSource).toContain("var(--muted, #abc4d8)");
    expect(cssSource).toContain("var(--surface, #14222e)");
    expect(cssSource).toContain("var(--caution-text, #e2c193)");
    expect(cssSource).not.toContain("#a3ff12");
    expect(cssSource).not.toContain("lime");
    expect(cssSource).not.toContain("cyan");
  });

  it("keeps the mobile layer: 390px containment and ≥44px touch targets", () => {
    expect(cssSource).toContain("@media (max-width: 640px)");
    expect(cssSource).toMatch(/min-height:\s*44px/);
    expect(cssSource).toMatch(/overflow-wrap:\s*anywhere/);
    expect(cssSource).toMatch(/min-width:\s*0/);
  });
});

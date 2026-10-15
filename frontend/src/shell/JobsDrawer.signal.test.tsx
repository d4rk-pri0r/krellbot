/**
 * JobsDrawer — scoped Signal presentation vocabulary evidence.
 * Contract: KRELL-SIGNAL-20261010.
 *
 * Pins the owner-approved scoped class vocabulary the mounted JobsDrawer
 * renders in the shell head-utils area (.kbot-shell__jobs-root and the
 * .kbot-jobs__… children from frontend/src/shell/JobsDrawer.signal.css)
 * without touching the legacy unscoped JobsDrawer.test.tsx: every
 * expectation here is driven through the existing `client` prop path with
 * a stubbed jobs fetch and the existing JobRow contract, and every test
 * references an existing data-testid marker verbatim
 * (kbot-jobs-dialog / jobs-local-preview / jobs-refresh / jobs-error /
 * jobs-loading / jobs-empty / job-row / jobs-drawer-csv-export), which
 * this slice must not alter.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { JobsDrawer, type JobRow } from "./JobsDrawer";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const cssSource = readFileSync(
  resolve(__dirname, "JobsDrawer.signal.css"),
  "utf8",
);

const ROW: JobRow = { id: "job-1", kind: "research.backtest", state: "succeeded" };

function openJobsDrawer(): void {
  fireEvent.click(screen.getByRole("button", { name: "Jobs" }));
}

describe("JobsDrawer Signal presentation (KRELL-SIGNAL-20261010)", () => {
  it("mounts the scoped Signal root with the shared trigger semantics", () => {
    const list = vi.fn<() => Promise<JobRow[]>>().mockResolvedValue([ROW]);
    const { container } = render(<JobsDrawer client={{ list }} />);
    const root = container.querySelector<HTMLElement>(".kbot-shell__jobs-root");
    expect(root).toBeInstanceOf(HTMLElement);
    // Exact tokens, not substrings: a renamed or suffixed class must fail.
    const trigger = root?.querySelector<HTMLElement>("button.kbot-jobs__trigger");
    expect(trigger?.textContent).toBe("Jobs");
    expect(trigger?.getAttribute("aria-haspopup")).toBe("dialog");
    expect(trigger?.getAttribute("aria-expanded")).toBe("false");
    expect(trigger?.getAttribute("aria-controls")).toBe("kbot-jobs-drawer");
    expect(list).not.toHaveBeenCalled();
    openJobsDrawer();
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("renders the dialog, head, title, badge and toolbar under the scoped classes", async () => {
    const list = vi.fn<() => Promise<JobRow[]>>().mockResolvedValue([ROW]);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    const dialog = await screen.findByTestId("kbot-jobs-dialog");
    expect(dialog.classList.contains("kbot-jobs__dialog")).toBe(true);
    const root = dialog.closest(".kbot-shell__jobs-root");
    expect(root).not.toBeNull();
    const scrim = dialog.parentElement;
    expect(scrim?.classList.contains("kbot-jobs__scrim")).toBe(true);
    expect(scrim?.getAttribute("role")).toBe("dialog");
    expect(scrim?.getAttribute("aria-modal")).toBe("true");
    expect(scrim?.getAttribute("aria-label")).toBe("Jobs");
    const head = dialog.querySelector<HTMLElement>(".kbot-jobs__head");
    expect(head).toBeInstanceOf(HTMLElement);
    expect(head?.querySelector<HTMLElement>("h2.kbot-jobs__title")?.textContent).toBe("Jobs");
    // The seafoam "Local preview" badge leads the head in every state.
    const badge = screen.getByTestId("jobs-local-preview");
    expect(badge.classList.contains("kbot-jobs__preview-badge")).toBe(true);
    expect(badge.textContent).toBe("Local preview");
    expect(badge.parentElement).toBe(head);
    const close = head?.querySelector<HTMLElement>("button.kbot-jobs__close");
    expect(close?.getAttribute("aria-label")).toBe("Close jobs drawer");
    expect(close?.textContent).toBe("Close");
    const toolbar = dialog.querySelector<HTMLElement>(".kbot-jobs__toolbar");
    expect(toolbar).toBeInstanceOf(HTMLElement);
    const refresh = screen.getByTestId("jobs-refresh");
    expect(refresh.classList.contains("kbot-jobs__refresh")).toBe(true);
    expect(refresh.parentElement).toBe(toolbar);
    // The CSV export affordance sits in the toolbar and stays usable with rows.
    const exportButton = screen.getByTestId("jobs-drawer-csv-export");
    expect(exportButton.parentElement).toBe(toolbar);
    expect(exportButton.hasAttribute("disabled")).toBe(false);
  });

  it("keeps the honest loading state in the scoped classes before the first read settles", async () => {
    let resolveList: (rows: JobRow[]) => void = () => {};
    const list = vi.fn<() => Promise<JobRow[]>>().mockReturnValue(
      new Promise<JobRow[]>((resolve) => {
        resolveList = resolve;
      }),
    );
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    const loading = screen.getByTestId("jobs-loading");
    expect(loading.classList.contains("kbot-jobs__loading")).toBe(true);
    expect(loading.tagName).toBe("P");
    expect(loading.textContent).toBe("Loading jobs…");
    expect(screen.queryByTestId("jobs-empty")).toBeNull();
    expect(screen.queryByTestId("job-row")).toBeNull();
    await act(async () => {
      resolveList([ROW]);
    });
    expect(await screen.findByTestId("job-row")).not.toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
  });

  it("renders rows with the scoped id/kind/state vocabulary and preserves row order", async () => {
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockResolvedValue([
        { id: "job-2", kind: "research.backtest", state: "hibernating" },
        { id: "job-1", kind: "research.mro.sweep", state: "succeeded" },
      ]);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    const rows = await screen.findAllByTestId("job-row");
    expect(rows).toHaveLength(2);
    const dialog = screen.getByTestId("kbot-jobs-dialog");
    const listEl = dialog.querySelector<HTMLElement>("ul.kbot-jobs__list");
    expect(listEl).toBeInstanceOf(HTMLElement);
    expect(rows[0].classList.contains("kbot-jobs__row")).toBe(true);
    expect(rows[0].parentElement).toBe(listEl);
    expect(rows[0].tabIndex).toBe(0);
    // Restraint: ids and states are IBM Plex Mono technical labels; kind stays
    // readable prose in the seafoam accent.
    expect(rows[0].querySelector<HTMLElement>(".kbot-jobs__id")?.textContent).toBe("job-2");
    expect(rows[0].querySelector<HTMLElement>(".kbot-jobs__kind")?.textContent).toBe(
      "Research backtest",
    );
    expect(rows[0].querySelector<HTMLElement>(".kbot-jobs__state")?.textContent).toBe(
      "(hibernating)",
    );
    expect(rows[1].querySelector<HTMLElement>(".kbot-jobs__id")?.textContent).toBe("job-1");
    expect(rows[1].querySelector<HTMLElement>(".kbot-jobs__kind")?.textContent).toBe(
      "Research mro sweep",
    );
    expect(rows[1].querySelector<HTMLElement>(".kbot-jobs__state")?.textContent).toBe(
      "(succeeded)",
    );
  });

  it("keeps the honest empty state inside the scoped empty vocabulary", async () => {
    const list = vi.fn<() => Promise<JobRow[]>>().mockResolvedValue([]);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    const empty = await screen.findByTestId("jobs-empty");
    expect(empty.classList.contains("kbot-jobs__empty")).toBe(true);
    expect(
      empty.querySelector<HTMLElement>(".kbot-jobs__empty-title")?.textContent,
    ).toBe("No jobs");
    expect(
      empty.querySelector<HTMLElement>(".kbot-jobs__empty-detail")?.textContent,
    ).toBe("No jobs yet. Local preview only — live trading unavailable.");
    expect(screen.getByTestId("jobs-local-preview").classList.contains("kbot-jobs__preview-badge")).toBe(
      true,
    );
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    // Disabled pass-through: with no rows the drawer renders the export
    // affordance with the empty jobs array, so it is disabled.
    expect(screen.getByTestId("jobs-drawer-csv-export").hasAttribute("disabled")).toBe(true);
  });

  it("renders the coral failure line with its detail and inline Retry under the scoped classes", async () => {
    const list = vi
      .fn<() => Promise<JobRow[]>>()
      .mockRejectedValueOnce(new Error("jobs failed: 503"))
      .mockResolvedValueOnce([ROW]);
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    const alert = await screen.findByTestId("jobs-error");
    expect(alert.classList.contains("kbot-jobs__row-result")).toBe(true);
    expect(alert.getAttribute("role")).toBe("alert");
    const failure = alert.querySelector<HTMLElement>(".kbot-jobs__row-result-text");
    expect(failure?.textContent).toBe("Could not load jobs — check the workstation is running.");
    const detail = alert.querySelector<HTMLElement>(".kbot-jobs__row-result-detail");
    expect(detail?.textContent).toBe("jobs failed: 503");
    const retry = alert.querySelector<HTMLElement>("button.kbot-jobs__retry");
    expect(retry?.textContent).toBe("Retry");
    // The inline Retry affordance re-invokes the same read.
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findAllByTestId("job-row")).toHaveLength(1);
    expect(screen.queryByTestId("jobs-error")).toBeNull();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("renders the blocked local-only read in the same scoped failure vocabulary", async () => {
    const list = vi.fn<() => Promise<JobRow[]>>().mockRejectedValueOnce(
      new Error("jobs failed: 403"),
    );
    render(<JobsDrawer client={{ list }} />);
    openJobsDrawer();
    const alert = await screen.findByTestId("jobs-error");
    expect(alert.classList.contains("kbot-jobs__row-result")).toBe(true);
    expect(
      alert.querySelector<HTMLElement>(".kbot-jobs__row-result-text")?.textContent,
    ).toBe("Jobs blocked — local-only preview.");
    expect(alert.querySelector<HTMLElement>(".kbot-jobs__row-result-detail")?.textContent).toBe(
      "jobs failed: 403",
    );
    expect(screen.queryByTestId("jobs-empty")).toBeNull();
    expect(screen.queryByTestId("job-row")).toBeNull();
    expect(screen.queryByTestId("jobs-loading")).toBeNull();
  });

  it("scopes every stylesheet rule under the approved jobs root selector", () => {
    render(<JobsDrawer client={{ list: vi.fn().mockResolvedValue([]) }} />);
    expect(screen.getByRole("button", { name: "Jobs" })).toBeInstanceOf(HTMLElement);
    const stripped = cssSource.replace(/\/\*[\s\S]*?\*\//g, "");
    const blocks = Array.from(stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g));
    expect(blocks.length).toBeGreaterThan(0);
    for (const block of blocks) {
      expect(block[1]).toContain(".kbot-shell__jobs-root");
    }
    // The approved scoped child selectors are nested under the root, not flat.
    for (const scoped of [
      ".kbot-jobs__dialog",
      ".kbot-jobs__head",
      ".kbot-jobs__title",
      ".kbot-jobs__preview-badge",
      ".kbot-jobs__toolbar",
      ".kbot-jobs__loading",
      ".kbot-jobs__empty",
      ".kbot-jobs__row-result",
      ".kbot-jobs__row-result-text",
      ".kbot-jobs__row-result-detail",
      ".kbot-jobs__retry",
      ".kbot-jobs__list",
      ".kbot-jobs__row",
      ".kbot-jobs__id",
      ".kbot-jobs__kind",
      ".kbot-jobs__state",
    ]) {
      expect(cssSource).toContain(`${".kbot-shell__jobs-root"} ${scoped}`);
    }
    // The empty-title / empty-detail pair nests one level deeper under .kbot-jobs__empty.
    expect(cssSource).toContain(".kbot-shell__jobs-root .kbot-jobs__empty .kbot-jobs__empty-title");
    expect(cssSource).toContain(
      ".kbot-shell__jobs-root .kbot-jobs__empty .kbot-jobs__empty-detail",
    );
  });

  it("keeps the approved Signal token fallbacks and the narrow-viewport layer", () => {
    render(<JobsDrawer client={{ list: vi.fn().mockResolvedValue([]) }} />);
    expect(screen.getByRole("button", { name: "Jobs" })).toBeInstanceOf(HTMLElement);
    expect(cssSource).toContain('var(--font-ui, "Manrope"');
    expect(cssSource).toContain('var(--font-mono, "IBM Plex Mono"');
    expect(cssSource).toContain("var(--seafoam, #a8d8d1)");
    expect(cssSource).toContain("var(--sage, #b3dda8)");
    expect(cssSource).toContain("var(--coral, #cc9689)");
    expect(cssSource).toContain("var(--surface, #14222e)");
    expect(cssSource).toContain("var(--line, #22465d)");
    expect(cssSource).toContain("@media (max-width: 640px)");
    expect(cssSource).toMatch(/min-height:\s*44px/);
    expect(cssSource).toMatch(/overflow-wrap:\s*anywhere/);
    // No neon-lime/cyan palette reintroduction.
    expect(cssSource).not.toContain("#a3ff12");
    expect(cssSource).not.toContain("lime");
    expect(cssSource).not.toContain("cyan");
  });
});

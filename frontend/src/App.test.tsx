import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { PaperClient } from "./features/paper/client";
import { WorkstationShell } from "./shell/WorkstationShell";

afterEach(cleanup);

function makePaperClient(
  overrides: Partial<PaperClient> = {},
): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
    }),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
    }),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
    }),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
    }),
    ...overrides,
  };
}

describe("App shell", () => {
  it("renders the paper workstation heading", () => {
    render(<App />);
    expect(screen.getByText("Paper workstation")).toBeDefined();
  });

  it("renders the live-orders unavailable status", () => {
    render(<App />);
    expect(screen.getByText("Live orders unavailable")).toBeDefined();
  });
});

describe("App status strip", () => {
  it("exposes the Paper mode badge inside the status strip", () => {
    render(<App />);
    const strip = screen.getByRole("region", { name: /status/i });
    expect(strip.textContent).toMatch(/Paper/);
  });

  it("exposes the live-orders sentence inside the status strip", () => {
    render(<App />);
    const strip = screen.getByRole("region", { name: /status/i });
    expect(strip.textContent).toMatch(/Live orders unavailable/);
  });
});

describe("App navigation", () => {
  it("renders in-app controls for Workstation, Strategies, and Research", () => {
    render(<App />);
    const nav = screen.getByRole("navigation", { name: /workstation navigation/i });
    expect(nav.querySelector("a")).toBeNull();
    const buttons = nav.querySelectorAll("button");
    const labels = Array.from(buttons).map((b) => b.textContent?.trim());
    expect(labels).toEqual(
      expect.arrayContaining(["Workstation", "Strategies", "Research"]),
    );
  });
});

describe("App inspector", () => {
  it("renders an inspector region whose empty state reads 'Nothing selected'", () => {
    render(<App />);
    const inspector = screen.getByRole("region", { name: "Inspector" });
    expect(inspector.textContent).toMatch(/Nothing selected/);
  });
});

describe("App jobs drawer", () => {
  it("opens a drawer labelled 'Jobs' with the 'No jobs' empty state", () => {
    render(<App />);
    expect(screen.queryByRole("dialog", { name: "Jobs" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /jobs/i }));
    const drawer = screen.getByRole("dialog", { name: "Jobs" });
    expect(drawer.textContent).toMatch(/No jobs/);
  });
});

describe("App command palette", () => {
  it("opens on Control+K, focuses its input, and does not submit a command", () => {
    render(<App />);
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = screen.getByRole("dialog", { name: /command palette/i });
    const input = dialog.querySelector("input");
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("opens on Meta+K and focuses its input", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const dialog = screen.getByRole("dialog", { name: /command palette/i });
    const input = dialog.querySelector("input");
    expect(document.activeElement).toBe(input);
  });

  it("closes on Escape and returns focus to the previously focused element", () => {
    render(<App />);
    const trigger = screen.getByRole("button", { name: /jobs/i });
    trigger.focus();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen
      .getByRole("dialog", { name: /command palette/i })
      .querySelector("input");
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(input as HTMLInputElement, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /command palette/i })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("App view routing", () => {
  it("starts on Workstation and renders the inspector", () => {
    render(<App />);
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(
      screen.getByRole("region", { name: "Inspector" }),
    ).toBeDefined();
  });

  it("does not render the strategy editor before Strategies is selected", () => {
    render(<App />);
    expect(
      screen.queryByRole("region", { name: /strategy editor/i }),
    ).toBeNull();
  });

  it("choosing Strategies shows the strategy editor and hides the workstation heading", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    const editor = screen.getByRole("region", { name: /strategy editor/i });
    expect(editor).toBeDefined();
    expect(editor.textContent).toMatch(/Label/);
    expect(editor.textContent).toMatch(/Raw JSON/);
    expect(screen.queryByText("Paper workstation")).toBeNull();
    expect(screen.queryByRole("region", { name: "Inspector" })).toBeNull();
  });

  it("choosing Workstation after Strategies shows the paper workstation again", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(
      screen.getByRole("region", { name: /strategy editor/i }),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(
      screen.queryByRole("region", { name: /strategy editor/i }),
    ).toBeNull();
  });

  it("choosing Research shows the research run form", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.getByLabelText(/dataset path/i)).toBeDefined();
    expect(screen.getByLabelText(/fee basis points/i)).toBeDefined();
    expect(screen.getByLabelText(/^from$/i)).toBeDefined();
    expect(screen.getByLabelText(/^to$/i)).toBeDefined();
    expect(screen.getByRole("button", { name: /^run$/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /synthetic fixture/i })).toBeDefined();
  });

  it("choosing Research hides the workstation heading", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.queryByText("Paper workstation")).toBeNull();
  });

  it("choosing Workstation after Research shows the paper workstation again", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.getByLabelText(/dataset path/i)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(screen.queryByLabelText(/dataset path/i)).toBeNull();
  });
});

describe("App paper controls (NS10b)", () => {
  it("renders the Paper controls region on the workstation view with a no-armed-pack fallback", async () => {
    const paperClient = makePaperClient();
    render(<WorkstationShell paperClient={paperClient} />);
    const panel = await screen.findByTestId("paper-status-panel");
    expect(panel.textContent).toMatch(/Paper status/);
    expect(panel.textContent).toMatch(/No pack armed/);
    // No controls while not armed.
    expect(screen.queryByRole("button", { name: /pause entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /resume entries/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^disarm$/i })).toBeNull();
  });

  it("shows Pause entries, Resume entries, and Disarm when status says armed", async () => {
    const paperClient = makePaperClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: true,
        venue: "kraken",
        pair: "SUIUSD",
        entries_paused: false,
        mode: "paper",
        pack_id: "trend-follow",
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    expect(
      await screen.findByRole("button", { name: /pause entries/i }),
    ).toBeDefined();
    expect(
      await screen.findByRole("button", { name: /resume entries/i }),
    ).toBeDefined();
    expect(
      await screen.findByRole("button", { name: /^disarm$/i }),
    ).toBeDefined();
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
  });

  it("hides the controls on the Strategies and Research views", () => {
    const paperClient = makePaperClient();
    render(<WorkstationShell paperClient={paperClient} />);
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    expect(screen.queryByTestId("paper-status-panel")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(screen.queryByTestId("paper-status-panel")).toBeNull();
  });

  it("does not expose any button whose name includes 'Live'", async () => {
    const paperClient = makePaperClient({
      getStatus: vi.fn().mockResolvedValue({
        schema_version: "1",
        armed: true,
        venue: "kraken",
        pair: "SUIUSD",
        entries_paused: false,
        mode: "paper",
        pack_id: "trend-follow",
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    const panel = await screen.findByTestId("paper-status-panel");
    const buttons = panel.querySelectorAll("button");
    for (const btn of Array.from(buttons)) {
      expect(btn.textContent ?? "").not.toMatch(/Live/);
    }
    // And the status strip's "Live orders unavailable" sentence stays
    // in its existing region — no live-order control ever replaces it.
    const strip = screen.getByRole("region", { name: "Status" });
    expect(strip.textContent).toMatch(/Live orders unavailable/);
  });

  it("shows 'Entries paused' after a successful pause click", async () => {
    const paperClient = makePaperClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: false,
          mode: "paper",
          pack_id: "trend-follow",
        })
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: true,
          mode: "paper",
          pack_id: "trend-follow",
        }),
      pauseEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "entries_paused",
        ok: true,
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    const pause = await screen.findByRole("button", { name: /pause entries/i });
    fireEvent.click(pause);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries paused/,
    );
    expect(paperClient.pauseEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
  });

  it("shows 'Entries active' after a successful resume click", async () => {
    const paperClient = makePaperClient({
      getStatus: vi
        .fn()
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: true,
          mode: "paper",
          pack_id: "trend-follow",
        })
        .mockResolvedValueOnce({
          schema_version: "1",
          armed: true,
          venue: "kraken",
          pair: "SUIUSD",
          entries_paused: false,
          mode: "paper",
          pack_id: "trend-follow",
        }),
      resumeEntries: vi.fn().mockResolvedValue({
        schema_version: "1",
        code: "entries_resumed",
        ok: true,
      }),
    });
    render(<WorkstationShell paperClient={paperClient} />);
    const resume = await screen.findByRole("button", { name: /resume entries/i });
    fireEvent.click(resume);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("paper-status-entries").textContent).toMatch(
      /Entries active/,
    );
    expect(paperClient.resumeEntries).toHaveBeenCalledWith("kraken", "SUIUSD");
  });
});

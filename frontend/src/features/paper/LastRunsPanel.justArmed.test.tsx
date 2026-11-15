/**
 * LastRunsPanel — just-armed empty copy does not contradict Armed paper runs.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LastRunsPanel } from "./LastRunsPanel";
import type { PaperClient, PaperRunsClient } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LastRunsPanel just-armed empty copy", () => {
  it("says no journalled runs yet rather than denying an armed pack", async () => {
    const client = {
      getStatus: vi.fn(),
      pauseEntries: vi.fn(),
      resumeEntries: vi.fn(),
      disarm: vi.fn(),
      listRuns: vi.fn().mockResolvedValue({ schema_version: "1", runs: [] }),
    } as unknown as PaperClient & PaperRunsClient;

    render(<LastRunsPanel client={client} />);

    expect((await screen.findByTestId("paper-last-runs-empty")).textContent).toBe(
      "No journalled paper runs yet — an armed pack waits for its first tick.",
    );
  });
});

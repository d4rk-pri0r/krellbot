import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeRestorePanel } from "./HomeRestorePanel";
import type { HomeRestoreClient, HomeRestoreResult } from "./homeRestoreClient";

afterEach(() => {
  cleanup();
});

function result(over: Partial<HomeRestoreResult> = {}): HomeRestoreResult {
  return {
    ok: true,
    code: "home_restored",
    message: "home restored; restore fence engaged",
    fence_engaged: true,
    kill_reason: "home restored; release entries pause and kill switch before live sends",
    entries_paused: true,
    live_ready: false,
    paper_only_release: true,
    applied: true,
    ...over,
  };
}

function makeClient(
  restoreHome: HomeRestoreClient["restoreHome"] = vi.fn().mockResolvedValue(result()),
): HomeRestoreClient {
  return { restoreHome };
}

function chooseFile(name = "backup.tar.gz"): File {
  return new File([new Uint8Array([1, 2, 3])], name, {
    type: "application/gzip",
  });
}

describe("HomeRestorePanel fence honesty (M16.6)", () => {
  it("explains the restore fence and that restore is never live-ready", () => {
    render(<HomeRestorePanel client={makeClient()} />);
    expect(screen.getByTestId("ops-home-restore")).toBeTruthy();
    expect(screen.getByTestId("ops-home-restore-fence-copy").textContent).toMatch(
      /kill switch/i,
    );
    expect(screen.getByTestId("ops-home-restore-live-ready").textContent).toMatch(
      /Live-ready after restore: no/,
    );
    expect(
      (screen.getByTestId("ops-home-restore-submit") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("submits the chosen archive and reports fence engagement without live-ready", async () => {
    const restoreHome = vi.fn().mockResolvedValue(result());
    render(<HomeRestorePanel client={makeClient(restoreHome)} />);
    const input = screen.getByTestId("ops-home-restore-file") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [chooseFile()] } });
    fireEvent.click(screen.getByTestId("ops-home-restore-submit"));

    await waitFor(() => {
      expect(restoreHome).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByTestId("ops-home-restore-feedback")).toBeTruthy();
    expect(screen.getByTestId("ops-home-restore-feedback").textContent).toMatch(
      /Fence engaged/i,
    );
    expect(screen.getByTestId("ops-home-restore-feedback").textContent).toMatch(
      /Not live-ready/i,
    );
    expect(screen.getByTestId("ops-home-restore-live-ready").textContent).toBe(
      "Live-ready after restore: no",
    );
  });

  it("surfaces home_not_empty honesty without claiming live-ready", async () => {
    const restoreHome = vi.fn().mockResolvedValue(
      result({
        ok: false,
        code: "home_not_empty",
        applied: false,
        validated: true,
        message:
          "archive validated; restore not applied because the workstation home is not empty",
      }),
    );
    render(<HomeRestorePanel client={makeClient(restoreHome)} />);
    fireEvent.change(screen.getByTestId("ops-home-restore-file"), {
      target: { files: [chooseFile()] },
    });
    fireEvent.click(screen.getByTestId("ops-home-restore-submit"));
    expect(await screen.findByTestId("ops-home-restore-feedback")).toBeTruthy();
    expect(screen.getByTestId("ops-home-restore-feedback").textContent).toMatch(
      /not empty/i,
    );
    expect(screen.queryByTestId("ops-home-restore-error")).toBeNull();
    expect(screen.getByTestId("ops-home-restore-live-ready").textContent).toBe(
      "Live-ready after restore: no",
    );
  });

  it("shows corrupt archive refusal as an error", async () => {
    const restoreHome = vi.fn().mockResolvedValue(
      result({
        ok: false,
        code: "archive_corrupt",
        applied: false,
        fence_engaged: false,
        kill_reason: null,
        message: "home restore refused; workstation home untouched",
      }),
    );
    render(<HomeRestorePanel client={makeClient(restoreHome)} />);
    fireEvent.change(screen.getByTestId("ops-home-restore-file"), {
      target: { files: [chooseFile("bad.tar.gz")] },
    });
    fireEvent.click(screen.getByTestId("ops-home-restore-submit"));
    expect(await screen.findByTestId("ops-home-restore-error")).toBeTruthy();
    expect(screen.getByTestId("ops-home-restore-error").textContent).toMatch(
      /untouched/i,
    );
  });
});

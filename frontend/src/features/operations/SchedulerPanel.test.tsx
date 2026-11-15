import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SchedulerPanel,
  isPlatformEnableUnavailable,
} from "./SchedulerPanel";
import type { OperationsClient, SchedulerStatus } from "./client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function status(over: Partial<SchedulerStatus> = {}): SchedulerStatus {
  return {
    schema_version: "1",
    installed: false,
    enabled: false,
    last_error: null,
    ...over,
  };
}

function makeClient(
  over: Partial<
    Pick<OperationsClient, "getScheduler" | "installScheduler" | "enableScheduler">
  > = {},
): OperationsClient {
  return {
    getOperations: vi.fn(),
    promote: vi.fn(),
    pauseEntries: vi.fn(),
    resumeEntries: vi.fn(),
    engageKill: vi.fn(),
    releaseKill: vi.fn(),
    ackAlert: vi.fn(),
    getScheduler: vi.fn().mockResolvedValue(status()),
    installScheduler: vi.fn().mockResolvedValue(status({ installed: true })),
    enableScheduler: vi.fn().mockResolvedValue(status({ installed: true, enabled: true })),
    ...over,
  };
}

describe("isPlatformEnableUnavailable", () => {
  it("detects unsupported platform last_error", () => {
    expect(isPlatformEnableUnavailable("unsupported platform: win32")).toBe(true);
    expect(isPlatformEnableUnavailable("not_installed")).toBe(false);
    expect(isPlatformEnableUnavailable(null)).toBe(false);
  });
});

describe("SchedulerPanel status display", () => {
  it("shows not installed status from getScheduler", async () => {
    const client = makeClient();
    render(<SchedulerPanel client={client} />);

    expect(await screen.findByTestId("ops-scheduler")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("ops-scheduler-status").textContent).toBe("Not installed.");
    });
    expect(screen.getByTestId("ops-scheduler-installed").textContent).toBe("no");
    expect(screen.getByTestId("ops-scheduler-enabled").textContent).toBe("no");
    expect((screen.getByTestId("ops-scheduler-install") as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect((screen.getByTestId("ops-scheduler-enable") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows honest copy and disables Enable when platform enable is unavailable", async () => {
    const client = makeClient({
      getScheduler: vi.fn().mockResolvedValue(
        status({
          installed: true,
          enabled: false,
          last_error: "unsupported platform: aix",
        }),
      ),
    });
    render(<SchedulerPanel client={client} />);

    const unavailable = await screen.findByTestId("ops-scheduler-unavailable");
    expect(unavailable.textContent).toMatch(/Platform enable is unavailable/i);
    expect(screen.getByTestId("ops-scheduler-unavailable-reason").textContent).toBe(
      "unsupported platform: aix",
    );
    expect((screen.getByTestId("ops-scheduler-enable") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("ops-scheduler-install") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("SchedulerPanel happy path with fakes", () => {
  it("install then enable updates status through fake client", async () => {
    let current = status();
    const getScheduler = vi.fn().mockImplementation(async () => current);
    const installScheduler = vi.fn().mockImplementation(async () => {
      current = status({ installed: true, enabled: false });
      return current;
    });
    const enableScheduler = vi.fn().mockImplementation(async () => {
      current = status({ installed: true, enabled: true });
      return current;
    });
    const client = makeClient({ getScheduler, installScheduler, enableScheduler });
    render(<SchedulerPanel client={client} />);

    await screen.findByTestId("ops-scheduler-status");
    expect(screen.getByTestId("ops-scheduler-status").textContent).toBe("Not installed.");

    fireEvent.click(screen.getByTestId("ops-scheduler-install"));
    await waitFor(() => {
      expect(screen.getByTestId("ops-scheduler-status").textContent).toBe(
        "Installed, not enabled.",
      );
    });
    expect(screen.getByTestId("ops-scheduler-installed").textContent).toBe("yes");
    expect(screen.getByTestId("ops-scheduler-enabled").textContent).toBe("no");
    expect(screen.getByTestId("ops-scheduler-feedback").textContent).toMatch(/installed/i);
    expect(installScheduler).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("ops-scheduler-enable"));
    await waitFor(() => {
      expect(screen.getByTestId("ops-scheduler-status").textContent).toBe(
        "Installed and enabled.",
      );
    });
    expect(screen.getByTestId("ops-scheduler-enabled").textContent).toBe("yes");
    expect(screen.getByTestId("ops-scheduler-feedback").textContent).toMatch(/enabled/i);
    expect(enableScheduler).toHaveBeenCalledTimes(1);
    expect((screen.getByTestId("ops-scheduler-install") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("ops-scheduler-enable") as HTMLButtonElement).disabled).toBe(true);
  });

  it("enable failure with unsupported platform shows unavailable copy", async () => {
    const client = makeClient({
      getScheduler: vi.fn().mockResolvedValue(status({ installed: true })),
      enableScheduler: vi.fn().mockResolvedValue(
        status({
          installed: true,
          enabled: false,
          last_error: "unsupported platform: freebsd",
        }),
      ),
    });
    render(<SchedulerPanel client={client} />);
    await screen.findByTestId("ops-scheduler-enable");

    fireEvent.click(screen.getByTestId("ops-scheduler-enable"));
    const unavailable = await screen.findByTestId("ops-scheduler-unavailable");
    expect(unavailable.textContent).toMatch(/Platform enable is unavailable/i);
    expect((screen.getByTestId("ops-scheduler-enable") as HTMLButtonElement).disabled).toBe(true);
  });
});

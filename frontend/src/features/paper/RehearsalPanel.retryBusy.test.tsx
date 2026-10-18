import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RehearsalPanel } from "./RehearsalPanel";
import type { RehearsalClient, RehearsalStatus } from "./rehearsalClient";

afterEach(cleanup);

const status: RehearsalStatus = {
  schema_version: "1",
  label: "Synthetic retry fixture",
  status: "idle",
  cursor: 0,
  total_bars: 20,
  balances: { USD: "1000" },
  position: "0",
  resting_stop: null,
  recent_fills: [],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

// Defer only the transport boundary; exercise the real panel and reducer.
function clientWith(getStatus: RehearsalClient["getStatus"]): RehearsalClient {
  return {
    getStatus,
    start: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    exit: vi.fn(),
    stop: vi.fn(),
  };
}

const live = () => screen.getByTestId("rehearsal-retry-busy-status");

function expectBusy(button: HTMLButtonElement) {
  expect(document.activeElement).toBe(button);
  expect(button.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect(button.disabled).toBe(true);
  expect(button.textContent?.trim()).toBe("Retry status");
  expect(button.nextElementSibling).toBe(live());
  expect(live().textContent).toBe("Reading rehearsal status…");
  expect(live().getAttribute("role")).toBe("status");
  expect(live().getAttribute("aria-live")).toBe("polite");
  expect(live().getAttribute("aria-atomic")).toBe("true");
  expect(live().closest("button, [role='alert'], .kbot-rehearsal__error-stack")).toBeNull();
  expect(screen.getByTestId("rehearsal-error").textContent).toBe("initial read fixture");
}

describe("rehearsal retry keyboard busy", () => {
  it.each([false, true])("announces the retry round-trip and guards repeat activation (rejected=%s)", async (rejected) => {
    const response = deferred<RehearsalStatus>();
    const nextResponse = deferred<RehearsalStatus>();
    const getStatus = vi.fn()
      .mockRejectedValueOnce(new Error("initial read fixture"))
      .mockImplementationOnce(() => response.promise)
      .mockImplementationOnce(() => nextResponse.promise);
    render(<RehearsalPanel client={clientWith(getStatus)} />);
    const button = await screen.findByRole<HTMLButtonElement>("button", { name: "Retry status" });
    expect(screen.queryByTestId("rehearsal-retry-busy-status")?.textContent ?? "").toBe("");
    expect(button.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
    expect(button.hasAttribute("aria-busy")).toBe(false);
    expect(button.hasAttribute("disabled")).toBe(false);
    button.focus();
    await act(async () => {
      button.click();
      button.click();
    });
    expectBusy(button);
    const announcement = live();
    fireEvent.mouseDown(button);
    fireEvent.keyDown(button, { key: "Enter", repeat: true });
    fireEvent.keyDown(button, { key: " " });
    fireEvent.click(button);
    expect(getStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      if (rejected) response.reject(new Error("retry read fixture"));
      else response.resolve(status);
    });
    expect(live()).toBe(announcement);
    expect(live().textContent).toBe("Rehearsal status refreshed");
    expect(screen.getByTestId("rehearsal-panel").querySelector('[aria-busy="true"]')).toBeNull();
    expect(getStatus).toHaveBeenCalledTimes(2);
    if (rejected) {
      expect(button.hasAttribute("aria-busy")).toBe(false);
      expect(button.hasAttribute("disabled")).toBe(false);
      expect(button.textContent?.trim()).toBe("Retry status");
      expect(document.activeElement).toBe(button);
      fireEvent.click(button);
      expectBusy(button);
      expect(getStatus).toHaveBeenCalledTimes(3);
      await act(async () => nextResponse.resolve(status));
      expect(live()).toBe(announcement);
      expect(live().textContent).toBe("Rehearsal status refreshed");
    } else {
      // Successful readback replaces the failure branch, as before this slice.
      expect(screen.queryByRole("button", { name: "Retry status" })).toBeNull();
      expect(screen.getByTestId("rehearsal-holdings-panel")).toBeTruthy();
    }
  });
});

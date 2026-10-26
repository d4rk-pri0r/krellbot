import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IndicatorSpecJsonExport } from "./IndicatorSpecJsonExport";

type RecordedAnchor = { href: string | null; download: string | null };

function mountDownloadHarness() {
  const blobs: Blob[] = [];
  const allocatedUrls: string[] = [];
  const revokedUrls: string[] = [];
  const anchorClicks: RecordedAnchor[] = [];
  let callSequence = 0;

  const createObjectURL = vi.fn((blob: Blob) => {
    blobs.push(blob);
    callSequence += 1;
    const url = `blob:spec-${callSequence}`;
    allocatedUrls.push(url);
    return url;
  });
  const revokeObjectURL = vi.fn((url: string) => {
    revokedUrls.push(url);
  });
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

  const anchorClick = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      anchorClicks.push({
        href: this.getAttribute("href"),
        download: this.getAttribute("download"),
      });
    });

  return {
    blobs,
    allocatedUrls,
    revokedUrls,
    anchorClicks,
    createObjectURL,
    revokeObjectURL,
    anchorClick,
    failNextAllocation(reason = "synthetic allocation denial 0xC15") {
      createObjectURL.mockImplementationOnce(() => {
        callSequence += 1;
        throw new Error(reason);
      });
    },
    failNextActivation(reason = "synthetic activation denial 0xC15") {
      anchorClick.mockImplementationOnce(() => {
        throw new Error(reason);
      });
    },
  };
}

describe("IndicatorSpecJsonExport failure recovery", () => {
  let windowErrors: string[];

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    windowErrors = [];
    window.addEventListener("error", recordWindowError);
  });

  afterEach(() => {
    window.removeEventListener("error", recordWindowError);
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function recordWindowError(event: ErrorEvent) {
    windowErrors.push(event.message);
    event.preventDefault();
  }

  async function flushMicrotasks() {
    await act(async () => {
      await Promise.resolve();
    });
  }

  function settleStatusLifecycle() {
    act(() => {
      vi.runOnlyPendingTimers();
    });
  }

  it("reports a truthful failure and clears busy when URL allocation throws", async () => {
    const env = mountDownloadHarness();
    env.failNextAllocation();
    render(<IndicatorSpecJsonExport spec={{ name: "sma", len: 14 }} />);
    const button = screen.getByTestId("studio-indicator-spec-export");
    const status = screen.getByTestId("studio-indicator-spec-export-status");

    fireEvent.click(button);
    await flushMicrotasks();

    expect(windowErrors).toEqual([]);
    expect(button.getAttribute("aria-busy")).not.toBe("true");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.textContent ?? "").toMatch(/failed|unable|could not/i);
    expect(env.revokeObjectURL).not.toHaveBeenCalled();
    settleStatusLifecycle();
  });

  it("keeps raw exception details out of the announced failure status", async () => {
    const env = mountDownloadHarness();
    env.failNextAllocation("synthetic allocation denial 0xC15");
    render(<IndicatorSpecJsonExport spec={{ name: "sma", len: 14 }} />);
    const status = screen.getByTestId("studio-indicator-spec-export-status");

    fireEvent.click(screen.getByTestId("studio-indicator-spec-export"));
    await flushMicrotasks();

    const text = status.textContent ?? "";
    expect(text).toMatch(/failed|unable|could not/i);
    expect(text).not.toContain("synthetic");
    expect(text).not.toContain("0xC15");
    expect(text).not.toContain("denial");
    expect(text).not.toContain("Error");
    settleStatusLifecycle();
  });

  it("revokes the allocated object URL and reports failure when anchor activation throws", async () => {
    const env = mountDownloadHarness();
    env.failNextActivation();
    render(<IndicatorSpecJsonExport spec={{ name: "sma", len: 14 }} />);
    const button = screen.getByTestId("studio-indicator-spec-export");
    const status = screen.getByTestId("studio-indicator-spec-export-status");

    fireEvent.click(button);
    await flushMicrotasks();

    expect(windowErrors).toEqual([]);
    expect(env.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(env.revokeObjectURL).toHaveBeenCalledWith(env.allocatedUrls[0]);
    expect(button.getAttribute("aria-busy")).not.toBe("true");
    expect(status.textContent ?? "").toMatch(/failed|unable|could not/i);
    expect(env.anchorClick).toHaveBeenCalledTimes(1);
    settleStatusLifecycle();
  });

  it("revokes the URL even when the anchor throws before the normal revoke point", async () => {
    const env = mountDownloadHarness();
    env.failNextActivation();
    render(
      <IndicatorSpecJsonExport
        spec={{ name: "rsi", len: 14 }}
        timestamp="20261026T153000Z"
      />,
    );

    fireEvent.click(screen.getByTestId("studio-indicator-spec-export"));
    await flushMicrotasks();

    expect(env.anchorClick.mock.invocationCallOrder[0]).toBeLessThan(
      env.revokeObjectURL.mock.invocationCallOrder[0],
    );
    settleStatusLifecycle();
  });

  it("succeeds on the next ordinary click after a failure without reset or remount", async () => {
    const env = mountDownloadHarness();
    env.failNextAllocation();
    render(
      <IndicatorSpecJsonExport
        spec={{ name: "sma", len: 14 }}
        timestamp="20261026T153000Z"
      />,
    );
    const button = screen.getByTestId("studio-indicator-spec-export");
    const status = screen.getByTestId("studio-indicator-spec-export-status");

    fireEvent.click(button);
    await flushMicrotasks();
    expect(status.textContent ?? "").toMatch(/failed|unable|could not/i);
    expect(button.getAttribute("aria-busy")).not.toBe("true");
    expect((button as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(button);
    expect(button.getAttribute("aria-busy")).toBe("true");
    await flushMicrotasks();

    expect(windowErrors).toEqual([]);
    expect(status.textContent).toBe("Export complete for spec sma");
    expect(button.getAttribute("aria-busy")).not.toBe("true");
    expect(env.anchorClick).toHaveBeenCalledTimes(1);
    expect(env.anchorClicks[0]).toEqual({
      href: "blob:spec-2",
      download: "krellbot-indicator-sma-20261026T153000Z.json",
    });
    expect(env.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(env.revokeObjectURL).toHaveBeenCalledWith("blob:spec-2");
    settleStatusLifecycle();
  });

  it("preserves the validated spec JSON and filename contracts on success", async () => {
    const env = mountDownloadHarness();
    render(
      <IndicatorSpecJsonExport
        spec={{ name: "ema 200/fast", len: 200 }}
        timestamp="20261026T153000Z"
      />,
    );

    fireEvent.click(screen.getByTestId("studio-indicator-spec-export"));
    await flushMicrotasks();

    expect(env.blobs).toHaveLength(1);
    expect(env.blobs[0].type).toBe("application/json;charset=utf-8");
    expect(await env.blobs[0].text()).toBe(
      '{\n  "name": "ema 200/fast",\n  "len": 200\n}\n',
    );
    expect(env.anchorClicks[0]?.download).toBe(
      "krellbot-indicator-ema_200_fast-20261026T153000Z.json",
    );
    expect(env.anchorClicks[0]?.href).toBe("blob:spec-1");
    expect(env.revokeObjectURL).toHaveBeenCalledWith("blob:spec-1");
    settleStatusLifecycle();
  });

  it("renders nothing for a null spec without any download machinery", () => {
    mountDownloadHarness();
    const { container } = render(<IndicatorSpecJsonExport spec={null} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("studio-indicator-spec-export")).toBeNull();
    expect(
      screen.queryByTestId("studio-indicator-spec-export-status"),
    ).toBeNull();
  });

  it("lets the newest activation's completion replace an older failed one", async () => {
    const env = mountDownloadHarness();
    env.failNextAllocation();
    render(<IndicatorSpecJsonExport spec={{ name: "sma", len: 14 }} />);
    const button = screen.getByTestId("studio-indicator-spec-export");
    const status = screen.getByTestId("studio-indicator-spec-export-status");

    fireEvent.click(button);
    fireEvent.click(button);
    await flushMicrotasks();

    expect(windowErrors).toEqual([]);
    expect(status.textContent).toBe("Export complete for spec sma");
    expect(button.getAttribute("aria-busy")).not.toBe("true");
    expect(env.createObjectURL).toHaveBeenCalledTimes(2);
    expect(env.anchorClick).toHaveBeenCalledTimes(1);
    expect(env.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(env.revokeObjectURL).toHaveBeenCalledWith("blob:spec-2");
    settleStatusLifecycle();
  });

  it("announces the failure and then clears it on the same lifecycle tick as success", async () => {
    const env = mountDownloadHarness();
    env.failNextActivation();
    render(<IndicatorSpecJsonExport spec={{ name: "sma", len: 14 }} />);
    const button = screen.getByTestId("studio-indicator-spec-export");
    const status = screen.getByTestId("studio-indicator-spec-export-status");

    fireEvent.click(button);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(status.textContent).toBe("Exporting spec sma…");
    expect(env.revokeObjectURL).toHaveBeenCalledWith("blob:spec-1");

    await flushMicrotasks();
    expect(button.hasAttribute("aria-busy")).toBe(false);
    expect(status.textContent).toMatch(/failed|unable|could not/i);
    expect(status.textContent).not.toMatch(/complete/i);

    settleStatusLifecycle();
    expect(status.textContent).toBe("");
  });
});

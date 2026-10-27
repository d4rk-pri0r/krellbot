import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient } from "./client";
import { ResearchView } from "./ResearchView";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const storedBody = {
  legacy_receipt: { equity: 123, fee_bps: 40, trades: [] },
  trace: [{ bar_ts: 1000, input: { close: 12 }, conditions: [] }],
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

/**
 * issue282 regression harness: the real createHttpClient HTTP adapter runs
 * against a synthetic fetch, so the automatic result read exercises the
 * actual GET /api/v1/jobs/{id}/result path (including its 503 -> Error
 * translation) instead of a stubbed client method.
 */
function trackUnhandledRejections(): { caught: unknown[]; stop: () => void } {
  const caught: unknown[] = [];
  const onUnhandled = (reason: unknown): void => {
    caught.push(reason);
  };
  process.on("unhandledRejection", onUnhandled);
  return {
    caught,
    stop: (): void => {
      process.off("unhandledRejection", onUnhandled);
    },
  };
}

function fillForm(): void {
  for (const [label, value] of [
    [/dataset path/i, "fixtures/synthetic.csv"],
    [/fee basis points/i, "40"],
    [/^from$/i, "0"],
    [/^to$/i, "1000"],
  ] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
}

async function runToJob(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: /^Run$/ }));
  await screen.findByTestId("research-job-id");
}

// Enough real time for two further 250 ms poll intervals to fire: proves the
// fixed path neither loops automatic result reads nor resubmits.
const SETTLE_TWO_POLL_INTERVALS_MS = 600;

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, SETTLE_TWO_POLL_INTERVALS_MS));
}

describe("Research automatic result-read failure feedback (issue282)", () => {
  it("shows a truthful accessible alert through the real HTTP adapter when the automatic result read gets a 503, with no unhandled rejection", async () => {
    const unhandled = trackUnhandledRejections();
    let jobPolls = 0;
    let resultReads = 0;
    let submitPosts = 0;
    const fetchMock = vi.fn((url: string | URL | Request): Promise<Response> => {
      const path = String(url);
      if (path === "/api/v1/research/jobs") {
        submitPosts += 1;
        return Promise.resolve(jsonResponse({ id: "job-auto-503", state: "queued" }));
      }
      if (path === "/api/v1/jobs/job-auto-503") {
        jobPolls += 1;
        return Promise.resolve(
          jsonResponse(
            jobPolls === 1
              ? { id: "job-auto-503", state: "running" }
              : { id: "job-auto-503", state: "succeeded" },
          ),
        );
      }
      if (path === "/api/v1/jobs/job-auto-503/result") {
        resultReads += 1;
        return Promise.resolve(jsonResponse({ code: "service_unavailable" }, 503));
      }
      return Promise.reject(new Error(`unexpected fetch: ${path}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<ResearchView client={createHttpClient()} />);
      fillForm();
      await runToJob();

      const alert = await screen.findByTestId("research-job-error");
      expect(alert.getAttribute("role")).toBe("alert");
      expect(alert.textContent).toMatch(/Result read failed/);
      expect(alert.textContent).toContain("request failed: 503");
      expect(alert.textContent).toMatch(/Load result/);

      const runbar = within(screen.getByTestId("research-runbar"));
      // Job identity is retained; the silent Waiting copy is replaced by the error.
      expect(runbar.getByTestId("research-job-id").textContent).toContain("job-auto-503");
      expect(screen.queryByTestId("research-job-status")).toBeNull();
      // No synthesized result and the explicit manual retry stays available.
      expect(screen.queryByTestId("research-result")).toBeNull();
      expect(
        runbar.getByRole("button", { name: /^Load result$/ }),
      ).toBeDefined();

      await settle();
      expect(resultReads).toBe(1);
      expect(submitPosts).toBe(1);
      expect(unhandled.caught).toEqual([]);
    } finally {
      unhandled.stop();
    }
  });

  it("healthy success still auto-displays the result through the real HTTP adapter without any error", async () => {
    const unhandled = trackUnhandledRejections();
    let jobPolls = 0;
    const fetchMock = vi.fn((url: string | URL | Request): Promise<Response> => {
      const path = String(url);
      if (path === "/api/v1/research/jobs") {
        return Promise.resolve(jsonResponse({ id: "job-auto-ok", state: "queued" }));
      }
      if (path === "/api/v1/jobs/job-auto-ok") {
        jobPolls += 1;
        return Promise.resolve(
          jsonResponse(
            jobPolls === 1
              ? { id: "job-auto-ok", state: "running" }
              : { id: "job-auto-ok", state: "succeeded" },
          ),
        );
      }
      if (path === "/api/v1/jobs/job-auto-ok/result") {
        return Promise.resolve(jsonResponse(storedBody));
      }
      return Promise.reject(new Error(`unexpected fetch: ${path}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<ResearchView client={createHttpClient()} />);
      fillForm();
      await runToJob();

      const result = await screen.findByTestId("research-result");
      expect(result.textContent).toContain("123");
      expect(screen.queryByTestId("research-job-error")).toBeNull();
      expect(screen.queryByTestId("research-job-status")).toBeNull();
      await waitFor(() => {
        expect(
          fetchMock.mock.calls.filter(([url]) =>
            String(url).endsWith("/result"),
          ),
        ).toHaveLength(1);
      });
      expect(unhandled.caught).toEqual([]);
    } finally {
      unhandled.stop();
    }
  });

  it("explicit Load result retry after the automatic failure re-reads the same job and clears the error", async () => {
    const unhandled = trackUnhandledRejections();
    let jobPolls = 0;
    let resultReads = 0;
    const fetchMock = vi.fn((url: string | URL | Request): Promise<Response> => {
      const path = String(url);
      if (path === "/api/v1/research/jobs") {
        return Promise.resolve(jsonResponse({ id: "job-retry-503", state: "queued" }));
      }
      if (path === "/api/v1/jobs/job-retry-503") {
        jobPolls += 1;
        return Promise.resolve(
          jsonResponse(
            jobPolls === 1
              ? { id: "job-retry-503", state: "running" }
              : { id: "job-retry-503", state: "succeeded" },
          ),
        );
      }
      if (path === "/api/v1/jobs/job-retry-503/result") {
        resultReads += 1;
        return Promise.resolve(
          resultReads === 1
            ? jsonResponse({ code: "service_unavailable" }, 503)
            : jsonResponse(storedBody),
        );
      }
      return Promise.reject(new Error(`unexpected fetch: ${path}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<ResearchView client={createHttpClient()} />);
      fillForm();
      await runToJob();

      const alert = await screen.findByTestId("research-job-error");
      expect(alert.textContent).toContain("request failed: 503");
      const runbar = within(screen.getByTestId("research-runbar"));
      expect(runbar.getByTestId("research-job-id").textContent).toContain("job-retry-503");

      fireEvent.click(runbar.getByRole("button", { name: /^Load result$/ }));

      const result = await screen.findByTestId("research-result");
      expect(result.textContent).toContain("123");
      await waitFor(() => {
        expect(screen.queryByTestId("research-job-error")).toBeNull();
      });
      expect(runbar.getByTestId("research-job-id").textContent).toContain("job-retry-503");

      const resultUrls = fetchMock.mock.calls
        .filter(([url]) => String(url).endsWith("/result"))
        .map(([url]) => String(url));
      expect(resultUrls).toEqual([
        "/api/v1/jobs/job-retry-503/result",
        "/api/v1/jobs/job-retry-503/result",
      ]);
      expect(unhandled.caught).toEqual([]);
    } finally {
      unhandled.stop();
    }
  });

  it("a late result-read failure for a stale job cannot poison the current run's intent", async () => {
    const unhandled = trackUnhandledRejections();
    let submitPosts = 0;
    const staleRead: { reject: ((reason: Error) => void) | null } = {
      reject: null,
    };
    const fetchMock = vi.fn((url: string | URL | Request): Promise<Response> => {
      const path = String(url);
      if (path === "/api/v1/research/jobs") {
        submitPosts += 1;
        return Promise.resolve(
          jsonResponse(
            submitPosts === 1
              ? { id: "job-stale-a", state: "queued" }
              : { id: "job-current-b", state: "queued" },
          ),
        );
      }
      if (path === "/api/v1/jobs/job-stale-a") {
        return Promise.resolve(jsonResponse({ id: "job-stale-a", state: "succeeded" }));
      }
      if (path === "/api/v1/jobs/job-stale-a/result") {
        return new Promise<Response>((_resolve, reject) => {
          staleRead.reject = reject;
        });
      }
      if (path === "/api/v1/jobs/job-current-b") {
        return new Promise<Response>(() => {});
      }
      return Promise.reject(new Error(`unexpected fetch: ${path}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<ResearchView client={createHttpClient()} />);
      fillForm();
      await runToJob();
      await waitFor(() => expect(staleRead.reject).not.toBeNull());

      // A second ordinary Run supersedes the stale job before its held
      // result read rejects.
      fireEvent.click(screen.getByRole("button", { name: /^Run$/ }));
      await waitFor(() => {
        expect(
          within(screen.getByTestId("research-runbar")).getByTestId("research-job-id")
            .textContent,
        ).toContain("job-current-b");
      });

      staleRead.reject?.(new Error("request failed: 503"));
      await settle();

      expect(screen.queryByTestId("research-job-error")).toBeNull();
      expect(screen.getByTestId("research-job-status").textContent).toContain("Waiting");
      expect(screen.queryByTestId("research-result")).toBeNull();
      expect(unhandled.caught).toEqual([]);
    } finally {
      unhandled.stop();
    }
  });
});

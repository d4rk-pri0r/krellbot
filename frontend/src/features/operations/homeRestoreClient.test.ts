import { beforeEach, describe, expect, it, vi } from "vitest";
import { createHomeRestoreHttpClient } from "./homeRestoreClient";

vi.mock("../../session", () => ({
  getCsrf: () => "test-csrf",
}));

describe("createHomeRestoreHttpClient", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs /api/v1/home/restore with CSRF and gzip body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        code: "home_restored",
        message: "restored",
        fence_engaged: true,
        kill_reason: "home restored; release entries pause and kill switch before live sends",
        entries_paused: true,
        live_ready: false,
        paper_only_release: true,
        applied: true,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = createHomeRestoreHttpClient();
    const blob = new Blob([new Uint8Array([1, 2])], { type: "application/gzip" });
    const result = await client.restoreHome(blob);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/home/restore");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-Krellbot-CSRF"]).toBe(
      "test-csrf",
    );
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/gzip",
    );
    expect(init.body).toBe(blob);
    expect(result.applied).toBe(true);
    expect(result.fence_engaged).toBe(true);
    expect(result.live_ready).toBe(false);
  });

  it("forces live_ready false even if the API claims true", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          ok: true,
          code: "home_restored",
          message: "restored",
          fence_engaged: true,
          kill_reason: "home restored",
          entries_paused: true,
          live_ready: true,
          paper_only_release: true,
          applied: true,
        }),
      }),
    );
    const result = await createHomeRestoreHttpClient().restoreHome(
      new Blob([new Uint8Array([9])]),
    );
    expect(result.live_ready).toBe(false);
  });

  it("parses refusal bodies without throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({
          ok: false,
          code: "archive_corrupt",
          message: "home restore refused; workstation home untouched",
          fence_engaged: false,
          kill_reason: null,
          entries_paused: false,
          live_ready: false,
          paper_only_release: true,
          applied: false,
        }),
      }),
    );
    const result = await createHomeRestoreHttpClient().restoreHome(
      new Blob([new Uint8Array([9])]),
    );
    expect(result.ok).toBe(false);
    expect(result.code).toBe("archive_corrupt");
    expect(result.applied).toBe(false);
  });
});

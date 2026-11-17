import { afterEach, describe, expect, it, vi } from "vitest";
import { createHomeExportHttpClient } from "./homeExportClient";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("createHomeExportHttpClient", () => {
  it("POSTs /api/v1/home/export with CSRF and returns the archive blob", async () => {
    const blob = new Blob(["gz"], { type: "application/gzip" });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: {
        get(name: string) {
          if (name.toLowerCase() === "content-disposition") {
            return 'attachment; filename="krellbot-home-1.tar.gz"';
          }
          return null;
        },
      },
      blob: async () => blob,
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = createHomeExportHttpClient();
    const result = await client.exportHome();
    expect(result.filename).toBe("krellbot-home-1.tar.gz");
    expect(result.blob).toBe(blob);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/home/export");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(typeof init.headers["X-Krellbot-CSRF"]).toBe("string");
  });

  it("includes refusal code in thrown errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ code: "secret_detected", message: "home export refused" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = createHomeExportHttpClient();
    await expect(client.exportHome()).rejects.toThrow(/secret_detected/);
  });
});

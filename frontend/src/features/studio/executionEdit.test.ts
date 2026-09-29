import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import { redeemBootstrap } from "../../session";
import {
  applyExecutionEdit,
  DRAFTS_PATH,
} from "./executionEdit";

const here = dirname(fileURLToPath(import.meta.url));

const csrfToken = "test-csrf-lane-a";

function mockJsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

interface FetchCall {
  url: string;
  init: RequestInit;
}

let fetchMock: Mock;
let fetchCalls: FetchCall[];

beforeEach(async () => {
  fetchCalls = [];
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    fetchCalls.push({ url, init: init ?? {} });
    if (url.endsWith("/api/v1/session/bootstrap")) {
      return mockJsonResponse({ csrf_token: csrfToken });
    }
    return mockJsonResponse({ pack: { id: "lane-a-strategy" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  await redeemBootstrap("test-bootstrap-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function lastDraftsCall(): FetchCall {
  for (let i = fetchCalls.length - 1; i >= 0; i -= 1) {
    if (fetchCalls[i].url.includes("/api/v1/strategies/drafts/")) {
      return fetchCalls[i];
    }
  }
  throw new Error("no drafts call recorded");
}

describe("applyExecutionEdit: request shape", () => {
  it("PUTs to the drafts URL with the literal /api/v1/strategies/drafts/ prefix", async () => {
    const pack = { id: "lane-a-strategy", entry: ["close", ">", "sma2"] };
    await applyExecutionEdit("rev-1", pack);

    const call = lastDraftsCall();
    expect(call.url).toBe("/api/v1/strategies/drafts/rev-1");
    expect(DRAFTS_PATH).toBe("/api/v1/strategies/drafts/");
  });

  it("uses PUT method", async () => {
    await applyExecutionEdit("rev-2", { id: "x" });
    expect(lastDraftsCall().init.method).toBe("PUT");
  });

  it("sends the pack under the body key 'pack'", async () => {
    const pack = { id: "lane-a-strategy", entry: ["close", ">", "sma2"] };
    await applyExecutionEdit("rev-3", pack);

    const body = JSON.parse(String(lastDraftsCall().init.body));
    expect(Object.keys(body)).toEqual(["pack"]);
    expect(body.pack).toEqual(pack);
  });

  it("URL-encodes the revision id", async () => {
    await applyExecutionEdit("rev/with spaces", { id: "x" });
    expect(lastDraftsCall().url).toBe(
      "/api/v1/strategies/drafts/rev%2Fwith%20spaces",
    );
  });

  it("carries the CSRF token in the X-Krellbot-CSRF header", async () => {
    await applyExecutionEdit("rev-4", { id: "x" });
    const headers = lastDraftsCall().init.headers as Record<string, string>;
    expect(headers["X-Krellbot-CSRF"]).toBe(csrfToken);
  });

  it("sets Content-Type to application/json", async () => {
    await applyExecutionEdit("rev-5", { id: "x" });
    const headers = lastDraftsCall().init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("uses credentials: include so the session cookie is sent", async () => {
    await applyExecutionEdit("rev-6", { id: "x" });
    expect(lastDraftsCall().init.credentials).toBe("include");
  });
});

describe("applyExecutionEdit: response handling", () => {
  it("returns the pack from the server response", async () => {
    const serverPack = { id: "lane-a-strategy", entry: ["a", "b"] };
    fetchMock.mockResolvedValueOnce(mockJsonResponse({ pack: serverPack }));

    const result = await applyExecutionEdit("rev-7", { id: "x" });
    expect(result).toEqual(serverPack);
  });

  it("throws when the server returns a non-2xx status", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse({}, 500));
    await expect(applyExecutionEdit("rev-8", { id: "x" })).rejects.toThrow(
      /execution edit failed: 500/,
    );
  });

  it("returns an empty object when the server omits the pack field", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse({}));
    const result = await applyExecutionEdit("rev-9", { id: "x" });
    expect(result).toEqual({});
  });
});

describe("applyExecutionEdit: side-effect freedom", () => {
  it("does not touch localStorage", async () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    await applyExecutionEdit("rev-a", { id: "x" });
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not write to document.cookie", async () => {
    let writes = 0;
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => "",
      set: () => {
        writes += 1;
      },
    });
    await applyExecutionEdit("rev-b", { id: "x" });
    expect(writes).toBe(0);
  });
});

describe("executionEdit.ts module surface", () => {
  it("contains the literal path /api/v1/strategies/drafts/", () => {
    const source = readFileSync(resolve(here, "executionEdit.ts"), "utf8");
    expect(source).toContain("/api/v1/strategies/drafts/");
  });

  it("contains the body key 'pack'", () => {
    const source = readFileSync(resolve(here, "executionEdit.ts"), "utf8");
    expect(source).toContain("pack");
  });

  it("does not call the editor save endpoint", () => {
    const source = readFileSync(resolve(here, "executionEdit.ts"), "utf8");
    expect(source).not.toContain("/editor");
  });

  it("does not import a network library", () => {
    const source = readFileSync(resolve(here, "executionEdit.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']axios["']/);
    expect(source).not.toMatch(/from\s+["']node-fetch["']/);
    expect(source).not.toMatch(/from\s+["']ky["']/);
  });

  it("does not import a graph library", () => {
    const source = readFileSync(resolve(here, "executionEdit.ts"), "utf8");
    expect(source).not.toMatch(/@xyflow\/react/);
    expect(source).not.toMatch(/from\s+["']reactflow["']/);
  });
});
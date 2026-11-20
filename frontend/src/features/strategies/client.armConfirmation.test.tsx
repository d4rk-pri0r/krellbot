import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { createHttpClient } from "./client";
import { redeemBootstrap } from "../../session";

/**
 * Issue 294 — arm response confirmation.
 *
 * `createHttpClient().arm` may resolve ONLY when the parsed response is
 * an object whose `ok` field is the literal boolean `true`. A missing,
 * null, nonboolean or non-object confirmation must reject with truthful
 * unconfirmed/malformed-result feedback: the command's outcome is
 * unknown, so the client must neither report success nor assert that
 * the backend refused. Explicit `ok: false` code feedback and
 * `arm failed: <status>` HTTP errors keep their existing behavior.
 *
 * Every malformed body below is a SYNTHETIC labelled wire fault: the
 * real backend emits a boolean `ok`. Each case must issue exactly one
 * authenticated POST — no automatic retry or replay.
 */

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function malformedJsonResponse(status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new SyntaxError("Unexpected token in JSON");
    },
  } as unknown as Response;
}

/** Seeds the shared session CSRF token so the arm POST can be checked
 * for a real echoed header, then clears the bootstrap call from the
 * mock's history so per-case call counts stay exact. */
async function stubFetchWithSeededCsrf(): Promise<Mock> {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockResolvedValueOnce(jsonResponse({ csrf_token: "arm-csrf-token" }));
  await redeemBootstrap("arm-bootstrap-token");
  fetchMock.mockClear();
  return fetchMock;
}

function expectSingleArmPost(fetchMock: Mock): void {
  expect(fetchMock).toHaveBeenCalledOnce();
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/v1/commands");
  expect(init.method).toBe("POST");
  expect(init.credentials).toBe("include");
  expect(new Headers(init.headers).get("X-Krellbot-CSRF")).toBe(
    "arm-csrf-token",
  );
  expect(JSON.parse(String(init.body))).toEqual({
    schema_version: "1",
    command: "paper.arm",
    payload: {
      revision_id: "rev-1",
      venue: "kraken",
      paper_balance: "1000",
    },
  });
}

async function armOnce(): Promise<void> {
  await createHttpClient().arm("rev-1", "kraken", "1000");
}

describe("createHttpClient arm response confirmation", () => {
  it("healthy control: resolves for an object body with literal ok===true, exactly one authenticated POST", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        code: "armed",
        ok: true,
        effect: "changed",
      }),
    );

    await expect(armOnce()).resolves.toBeUndefined();
    expectSingleArmPost(fetchMock);
  });

  it("healthy control: explicit ok:false keeps its code feedback as a rejection", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        code: "paper_not_disarmed",
        ok: false,
        effect: "refused",
      }),
    );

    await expect(armOnce()).rejects.toThrow(/paper_not_disarmed/);
    expectSingleArmPost(fetchMock);
  });

  it("healthy control: ok:false without a code keeps the generic refusal message", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(jsonResponse({ ok: false }));

    await expect(armOnce()).rejects.toThrow("arm refused");
    expectSingleArmPost(fetchMock);
  });

  it("healthy control: an HTTP error status keeps throwing arm failed: <status>", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(
      jsonResponse(
        { schema_version: "1", code: "draft_not_runnable", ok: false },
        403,
      ),
    );

    await expect(armOnce()).rejects.toThrow("arm failed: 403");
    expectSingleArmPost(fetchMock);

    fetchMock.mockClear();
    fetchMock.mockResolvedValue(jsonResponse({ detail: "boom" }, 500));
    await expect(armOnce()).rejects.toThrow("arm failed: 500");
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — object body missing ok rejects as unconfirmed instead of silently resolving", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(
      jsonResponse({ schema_version: "1", code: "armed", effect: "changed" }),
    );

    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — null body rejects with truthful unconfirmed feedback, not a TypeError", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(jsonResponse(null));

    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — boolean bodies (true/false) reject as unconfirmed", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(jsonResponse(true));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);

    fetchMock.mockClear();
    fetchMock.mockResolvedValue(jsonResponse(false));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — string bodies ('true'/'false') reject as unconfirmed", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(jsonResponse("true"));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);

    fetchMock.mockClear();
    fetchMock.mockResolvedValue(jsonResponse("false"));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — numeric bodies (0/1) reject as unconfirmed, including numeric zero", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(jsonResponse(0));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);

    fetchMock.mockClear();
    fetchMock.mockResolvedValue(jsonResponse(1));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — array bodies reject as unconfirmed, even one holding ok:true", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(jsonResponse([]));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);

    fetchMock.mockClear();
    fetchMock.mockResolvedValue(jsonResponse([{ ok: true }]));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — nonboolean ok values ('true'/1) reject as unconfirmed", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(jsonResponse({ ok: "true" }));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);

    fetchMock.mockClear();
    fetchMock.mockResolvedValue(jsonResponse({ ok: 1 }));
    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
  });

  it("SYNTHETIC wire fault — invalid JSON rejects as an unconfirmed malformed result, with one POST and no replay", async () => {
    const fetchMock = await stubFetchWithSeededCsrf();
    fetchMock.mockResolvedValue(malformedJsonResponse());

    await expect(armOnce()).rejects.toThrow(
      /arm unconfirmed: malformed response/,
    );
    expectSingleArmPost(fetchMock);
    // No automatic retry/replay after the honest failure.
    await new Promise((resolve) => {
      setTimeout(resolve, 100);
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});


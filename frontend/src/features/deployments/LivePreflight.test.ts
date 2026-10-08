import { createElement } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LivePreflight } from "./LivePreflight";

// This file is .ts (not .tsx) per the lane-D brief, so the component is
// mounted with createElement instead of JSX.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

type FetchCall = [string, RequestInit];

function lastFetchCall(fetchMock: ReturnType<typeof vi.fn>): FetchCall {
  expect(fetchMock).toHaveBeenCalled();
  return fetchMock.mock.calls[
    fetchMock.mock.calls.length - 1
  ] as unknown as FetchCall;
}

async function renderAndSubmit(
  fetchMock: ReturnType<typeof vi.fn>,
  overrides: { account_id?: string; revision_id?: string; mode?: string } = {},
): Promise<void> {
  render(createElement(LivePreflight));
  fireEvent.change(await screen.findByTestId("live-preflight-account"), {
    target: { value: overrides.account_id ?? "acct-1" },
  });
  fireEvent.change(screen.getByTestId("live-preflight-revision"), {
    target: { value: overrides.revision_id ?? "rev-1" },
  });
  if (overrides.mode !== undefined) {
    fireEvent.change(screen.getByTestId("live-preflight-mode"), {
      target: { value: overrides.mode },
    });
  }
  fireEvent.click(screen.getByTestId("live-preflight-submit"));
  await waitFor(() => {
    expect(screen.getByTestId("live-preflight-result")).toBeDefined();
  });
}

describe("LivePreflight submission", () => {
  it("posts live.preflight to /api/v1/commands with a payload body and sandbox mode", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        code: "ok",
        ok: true,
        message: "preflight ok",
        effect: "none",
        account_id: "acct-1",
        revision_id: "rev-1",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await renderAndSubmit(fetchMock);
    const [url, init] = lastFetchCall(fetchMock);
    expect(url).toBe("/api/v1/commands");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.headers).toHaveProperty("X-Krellbot-CSRF");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body).toEqual({
      schema_version: "1",
      command: "live.preflight",
      payload: {
        account_id: "acct-1",
        revision_id: "rev-1",
        mode: "sandbox",
      },
    });
    const payload = body.payload as Record<string, unknown>;
    expect(payload.account_id).toBe("acct-1");
    expect(payload.revision_id).toBe("rev-1");
    expect(payload.mode).toBe("sandbox");
  });

  it("never includes an args key in the posted body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        code: "ok",
        ok: true,
        message: "preflight ok",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await renderAndSubmit(fetchMock);
    const [, init] = lastFetchCall(fetchMock);
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body).not.toHaveProperty("args");
    expect(body.payload).toBeDefined();
  });

  it("shows the mode_not_sandbox refusal when the user selects live", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        code: "mode_not_sandbox",
        ok: false,
        message: "live mode is refused: sandbox only",
        effect: "refused",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await renderAndSubmit(fetchMock, { mode: "live" });
    const [, init] = lastFetchCall(fetchMock);
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    const payload = body.payload as Record<string, unknown>;
    expect(payload.mode).toBe("live");
    expect(body.command).toBe("live.preflight");
    const result = screen.getByTestId("live-preflight-result");
    expect(result.textContent ?? "").toMatch(/code: Mode not sandbox/);
    expect(result.textContent ?? "").toMatch(/live mode is refused/);
  });
});

describe("LivePreflight result rendering", () => {
  it("renders the ok code, message, account, and revision from the response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        code: "ok",
        ok: true,
        message: "preflight ok",
        effect: "none",
        account_id: "acct-1",
        revision_id: "rev-1",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await renderAndSubmit(fetchMock);
    const result = screen.getByTestId("live-preflight-result");
    expect(result.textContent ?? "").toMatch(/code: Ok/);
    expect(result.textContent ?? "").toMatch(/preflight ok/);
    expect(result.textContent ?? "").toMatch(/acct-1/);
    expect(result.textContent ?? "").toMatch(/rev-1/);
  });

  it("renders an account_mismatch refusal code and message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        schema_version: "1",
        code: "account_mismatch",
        ok: false,
        message: "account mismatch: acct-x is not stored",
        effect: "refused",
        account_id: "acct-1",
        revision_id: "rev-1",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await renderAndSubmit(fetchMock);
    const result = screen.getByTestId("live-preflight-result");
    expect(result.textContent ?? "").toMatch(/code: Account mismatch/);
    expect(result.textContent ?? "").toMatch(/account mismatch: acct-x/);
  });
});

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LivePreflight } from "./LivePreflight";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const verdict = { ok: true, code: "ok", message: "synthetic old verdict", account_id: "synthetic-A", revision_id: "synthetic-R1" };
function edit(field: string) {
  fireEvent.change(screen.getByTestId(`live-preflight-${field}`), { target: { value: field === "mode" ? "live" : "synthetic-new" } });
}
function submit() { fireEvent.click(screen.getByTestId("live-preflight-submit")); }

describe.each(["account", "revision", "mode"])("preflight %s intent edits", (field) => {
  it.each(["verdict", "error"])("clears a completed %s without submitting another request", async (kind) => {
    const fetchMock = kind === "verdict" ? vi.fn().mockResolvedValue(Response.json(verdict)) : vi.fn().mockRejectedValue(new Error("synthetic"));
    vi.stubGlobal("fetch", fetchMock);
    render(<LivePreflight />);
    submit();
    await screen.findByTestId(kind === "verdict" ? "live-preflight-result" : "live-preflight-error");
    edit(field);
    expect(screen.queryByTestId("live-preflight-result")).toBeNull();
    expect(screen.queryByTestId("live-preflight-error")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(["success", "refusal", "HTTP", "transport", "JSON"])("ignores obsolete %s completion after an edit", async (kind) => {
    const old = deferred<Response>();
    const fetchMock = vi.fn().mockReturnValue(old.promise);
    vi.stubGlobal("fetch", fetchMock);
    render(<LivePreflight />);
    submit();
    edit(field);
    await act(async () => {
      if (kind === "transport") old.reject(new Error("synthetic transport"));
      else if (kind === "HTTP") old.resolve(new Response(null, { status: 503 }));
      else if (kind === "JSON") old.resolve(new Response("not-json"));
      else old.resolve(Response.json({ ...verdict, ok: kind === "success" }));
    });
    expect(screen.queryByTestId("live-preflight-result")).toBeNull();
    expect(screen.queryByTestId("live-preflight-error")).toBeNull();
    expect((screen.getByTestId("live-preflight-submit") as HTMLButtonElement).disabled).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("invalidates an in-flight JSON completion without clearing newer pending state, then recovers", async () => {
    const body = deferred<typeof verdict>();
    const newer = deferred<Response>();
    const json = vi.fn().mockReturnValue(body.promise);
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json }).mockReturnValueOnce(newer.promise);
    vi.stubGlobal("fetch", fetchMock);
    render(<LivePreflight />);
    await act(async () => { submit(); });
    expect(json).toHaveBeenCalledTimes(1);
    edit(field);
    submit();
    await act(async () => { body.resolve(verdict); });
    expect(screen.queryByTestId("live-preflight-result")).toBeNull();
    expect((screen.getByTestId("live-preflight-submit") as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { newer.resolve(Response.json({ ...verdict, message: "synthetic current refusal", ok: false })); });
    expect((await screen.findByTestId("live-preflight-result")).textContent).toContain("synthetic current refusal");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const payload = JSON.parse(String(fetchMock.mock.calls[1][1].body)).payload;
    expect(payload[field === "account" ? "account_id" : field === "revision" ? "revision_id" : "mode"]).toBe(field === "mode" ? "live" : "synthetic-new");
  });
});

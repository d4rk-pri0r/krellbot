import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LivePreflight } from "./LivePreflight";

// Only the transport boundary is controlled; the real form handles every state transition.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function deferredResponse() {
  let resolve!: (response: Response) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Response>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const fields = ["account", "revision"] as const;
type Field = (typeof fields)[number];
const input = (field: Field) => screen.getByTestId(`live-preflight-${field}`);
const problemId = (field: Field) => `live-preflight-${field}-problem`;

function expectProblem(field: Field, invalid: boolean): void {
  expect(input(field).getAttribute("aria-invalid")).toBe(String(invalid));
  expect(input(field).getAttribute("aria-describedby")).toBe(invalid ? problemId(field) : null);
  const problem = screen.queryByTestId(problemId(field));
  if (invalid) {
    expect(problem?.tagName).toBe("P");
    expect(problem?.id).toBe(problemId(field));
    expect(problem?.textContent).toBe(`${field === "account" ? "Account" : "Revision"} ID is required`);
    expect(document.getElementById(problemId(field))).toBe(problem);
  } else {
    expect(problem).toBeNull();
  }
}

function submit(): HTMLButtonElement {
  const button = screen.getByTestId("live-preflight-submit") as HTMLButtonElement;
  fireEvent.click(button);
  return button;
}

describe("LivePreflight required input ARIA", () => {
  it("exposes both fields as required before submission, without premature problems", () => {
    render(<LivePreflight />);
    for (const field of fields) {
      expect(input(field).getAttribute("aria-required")).toBe("true");
      expectProblem(field, false);
    }
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each(["HTTP failure", "network rejection", "invalid JSON"])(
    "marks empty fields while pending and preserves their descriptions after %s",
    async (outcome) => {
      const request = deferredResponse();
      const fetchMock = vi.fn().mockReturnValue(request.promise);
      vi.stubGlobal("fetch", fetchMock);
      render(<LivePreflight />);
      input("account").focus();
      const button = submit();
      expect(button.disabled).toBe(true);
      expect(document.activeElement).toBe(input("account"));
      for (const field of fields) expectProblem(field, true);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(fetchMock).toHaveBeenCalledOnce();
      expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
        schema_version: "1", command: "live.preflight",
        payload: { account_id: "", revision_id: "", mode: "sandbox" },
      });
      await act(async () => {
        if (outcome === "network rejection") request.reject(new TypeError("Failed to fetch"));
        else if (outcome === "invalid JSON") request.resolve(new Response("not JSON"));
        else request.resolve(new Response(null, { status: 503 }));
      });
      expect(button.disabled).toBe(false);
      for (const field of fields) expectProblem(field, true);
      const alert = screen.getByTestId("live-preflight-error");
      expect(alert.getAttribute("role")).toBe("alert");
      expect(alert.className).toBe("kbot-feature__live-preflight-root__error");
      expect(alert.textContent).toBe("Preflight request failed");
    },
  );

  it.each(fields)("clears only the edited %s problem after a failed whitespace submission", async (field) => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<LivePreflight />);
    for (const name of fields) fireEvent.change(input(name), { target: { value: " \t " } });
    submit();
    await screen.findByTestId("live-preflight-error");
    for (const name of fields) expectProblem(name, true);
    fireEvent.change(input(field), { target: { value: "new-id" } });
    expectProblem(field, false);
    expectProblem(field === "account" ? "revision" : "account", true);
    expect(screen.getByRole("alert").textContent).toBe("Preflight request failed");
  });

  it.each(fields)("does not mark a populated %s invalid on request failure", async (field) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 500 })));
    render(<LivePreflight />);
    fireEvent.change(input(field), { target: { value: " valid-id " } });
    submit();
    await screen.findByTestId("live-preflight-error");
    expectProblem(field, false);
    expectProblem(field === "account" ? "revision" : "account", true);
  });

  it.each([true, false])("clears both problems after a parsed response (verdict ok=%s)", async (ok) => {
    const request = deferredResponse();
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(request.promise));
    render(<LivePreflight />);
    const button = submit();
    for (const field of fields) expectProblem(field, true);
    await act(async () => {
      request.resolve(Response.json({ code: ok ? "ok" : "account_mismatch", ok }));
    });
    expect(button.disabled).toBe(false);
    for (const field of fields) expectProblem(field, false);
    expect(screen.getByTestId("live-preflight-result")).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

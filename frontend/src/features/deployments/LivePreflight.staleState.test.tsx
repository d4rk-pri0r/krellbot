import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LivePreflight } from "./LivePreflight";

// Only the network boundary is controlled so pending and transport failures are deterministic.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const verdict = (fresh: boolean) => ({
  schema_version: "1",
  code: fresh ? "mode_not_sandbox" : "ok",
  ok: !fresh,
  message: fresh ? "live mode is refused: sandbox only" : "first preflight ok",
  effect: fresh ? "refused" : "none",
  account_id: fresh ? "acct-new" : "acct-old",
  revision_id: fresh ? "rev-new" : "rev-old",
});

function fill(fresh: boolean): void {
  fireEvent.change(screen.getByTestId("live-preflight-account"), {
    target: { value: fresh ? "acct-new" : "acct-old" },
  });
  fireEvent.change(screen.getByTestId("live-preflight-revision"), {
    target: { value: fresh ? "rev-new" : "rev-old" },
  });
  fireEvent.change(screen.getByTestId("live-preflight-mode"), {
    target: { value: fresh ? "live" : "sandbox" },
  });
}

function submit(): HTMLButtonElement {
  const button = screen.getByTestId("live-preflight-submit") as HTMLButtonElement;
  fireEvent.click(button);
  return button;
}

describe("LivePreflight repeat submission", () => {
  it.each(["fresh refusal", "HTTP failure", "network rejection", "invalid JSON"])(
    "flushes the old verdict before a pending request and shows only its %s",
    async (outcome) => {
      const next = deferred<Response>();
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(Response.json(verdict(false)))
        .mockReturnValueOnce(next.promise)
        .mockResolvedValueOnce(Response.json(verdict(true)));
      vi.stubGlobal("fetch", fetchMock);
      render(<LivePreflight />);
      fill(false);
      submit();
      expect((await screen.findByTestId("live-preflight-result")).textContent).toContain("acct-old");

      fill(true);
      const button = submit();
      expect(button.disabled).toBe(true);
      expect(screen.queryByTestId("live-preflight-result")).toBeNull();
      expect(screen.queryByTestId("live-preflight-error")).toBeNull();
      expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual({
        schema_version: "1",
        command: "live.preflight",
        payload: { account_id: "acct-new", revision_id: "rev-new", mode: "live" },
      });
      await act(async () => {
        if (outcome === "network rejection") next.reject(new TypeError("Failed to fetch"));
        else if (outcome === "HTTP failure") next.resolve(new Response(null, { status: 503 }));
        else if (outcome === "invalid JSON") next.resolve(new Response("not JSON"));
        else next.resolve(Response.json(verdict(true)));
      });
      await waitFor(() => expect(button.disabled).toBe(false));
      if (outcome === "fresh refusal") {
        const result = screen.getByTestId("live-preflight-result");
        expect(result.textContent).toContain("code: Mode not sandbox");
        expect(result.textContent).toContain("ok: false");
        expect(result.textContent).toContain(verdict(true).message);
        expect(result.textContent).toContain("acct-new");
        expect(result.textContent).toContain("rev-new");
        expect(result.textContent).not.toContain("acct-old");
        expect(result.textContent).not.toContain("rev-old");
        expect(screen.queryByTestId("live-preflight-error")).toBeNull();
      } else {
        expect(screen.getByRole("alert").textContent).toBe("Preflight request failed");
        expect(screen.queryByTestId("live-preflight-result")).toBeNull();
        submit();
        expect(screen.queryByTestId("live-preflight-error")).toBeNull();
        expect((await screen.findByTestId("live-preflight-result")).textContent).toContain("acct-new");
        expect(screen.queryByTestId("live-preflight-error")).toBeNull();
      }
    },
  );
});

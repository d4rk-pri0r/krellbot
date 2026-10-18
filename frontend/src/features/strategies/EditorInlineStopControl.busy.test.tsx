import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorInlineStopControl } from "./EditorInlineStopControl";
import type { PaperClient, PaperCommandResult, PaperStatus } from "../paper/client";

afterEach(cleanup);

const armed: PaperStatus = {
  schema_version: "1", armed: true, venue: "kraken", pair: "SUIUSD",
  entries_paused: false,
};
const intents = [
  { id: "pause", method: "pauseEntries", idle: "Pause entries", active: "Pausing…", command: "Pause" },
  { id: "resume", method: "resumeEntries", idle: "Resume entries", active: "Resuming…", command: "Resume" },
  { id: "disarm", method: "disarm", idle: "Disarm", active: "Disarming…", command: "Disarm" },
  { id: "refresh", method: "getStatus", idle: "Refresh status", active: "Refreshing…", command: "Refresh" },
  { id: "apply", method: "raiseStop", idle: "Apply new stop", active: "Applying…", command: "Apply new stop" },
] as const;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// A fake client boundary holds requests independently; the control and reducer
// are real. Native keyboard activation is checked by the Chromium verifier.
function client() {
  return {
    getStatus: vi.fn<PaperClient["getStatus"]>().mockResolvedValue(armed),
    pauseEntries: vi.fn<PaperClient["pauseEntries"]>().mockResolvedValue({ ok: true }),
    resumeEntries: vi.fn<PaperClient["resumeEntries"]>().mockResolvedValue({ ok: true }),
    disarm: vi.fn<PaperClient["disarm"]>().mockResolvedValue({ ok: true }),
    raiseStop: vi.fn<NonNullable<PaperClient["raiseStop"]>>().mockResolvedValue({ ok: true }),
  };
}

function button(id: string): HTMLButtonElement {
  return screen.getByTestId(`editor-inline-stop-${id}`) as HTMLButtonElement;
}
function live() {
  return within(screen.getByTestId("editor-inline-stop")).getByRole("status");
}
async function mount(paperClient: PaperClient) {
  render(<EditorInlineStopControl paperClient={paperClient} />);
  await screen.findByTestId("editor-inline-stop-new-stop");
  fireEvent.change(screen.getByTestId("editor-inline-stop-new-stop"), { target: { value: "2" } });
}
function idle(id: string, label: string) {
  expect(button(id).textContent).toBe(label);
  expect(button(id).getAttribute("aria-busy")).toBe("false");
  expect(live().textContent).toBe("");
}

describe.each(intents)("inline $idle busy feedback", (intent) => {
  it.each(["success", "refusal", "transport"] as const)("announces, blocks duplicates and restores on %s", async (outcome) => {
    const paperClient = client();
    const gate = deferred<PaperCommandResult & PaperStatus>();
    await mount(paperClient);
    paperClient[intent.method].mockReturnValueOnce(gate.promise);
    const target = button(intent.id);
    expect(target.getAttribute("aria-keyshortcuts")).toBe("Enter Space");
    idle(intent.id, intent.idle);
    target.focus();
    expect(document.activeElement).toBe(target);
    const before = paperClient[intent.method].mock.calls.length;
    fireEvent.click(target);
    expect(target.getAttribute("aria-busy")).toBe("true");
    expect(target.textContent).toBe(intent.active);
    expect(target.disabled).toBe(true);
    expect(live().getAttribute("aria-live")).toBe("polite");
    expect(live().textContent).toBe(intent.active);
    for (const sibling of intents) {
      expect(button(sibling.id).disabled).toBe(true);
      if (sibling.id !== intent.id) expect(button(sibling.id).getAttribute("aria-busy")).toBe("false");
      fireEvent.click(button(sibling.id));
    }
    fireEvent.click(target);
    fireEvent.keyDown(target, { key: "Enter", repeat: true });
    fireEvent.keyUp(target, { key: "Enter" });
    expect(paperClient[intent.method]).toHaveBeenCalledTimes(before + 1);
    if (intent.id !== "refresh") {
      expect(paperClient[intent.method]).toHaveBeenCalledWith(
        "kraken", "SUIUSD", ...(intent.id === "apply" ? ["2"] : []),
      );
    }
    await act(async () => {
      if (outcome === "transport" || (intent.id === "refresh" && outcome === "refusal")) {
        gate.reject(new Error("connection reset"));
      } else {
        gate.resolve({ ...armed, ok: outcome === "success", code: "invalid_stop", message: "typed refusal" });
      }
    });
    await waitFor(() => idle(intent.id, intent.idle));
    const caption = screen.getByTestId("inline-stop-caption");
    if (outcome === "transport" || (intent.id === "refresh" && outcome === "refusal")) {
      expect(caption.textContent).toBe("Armed at kraken SUIUSD · Entries active");
      expect(screen.getByTestId("editor-inline-stop-unknown").textContent).toBe(
        intent.id === "refresh"
          ? "Status refresh failed: connection reset. The last confirmed state is shown; refresh to reconcile."
          : `${intent.command} outcome unknown: connection reset. Refresh status to see the server state before retrying.`,
      );
    } else if (outcome === "refusal") {
      expect(caption.textContent).toBe("Refused: typed refusal");
    } else if (intent.id === "disarm") {
      expect(caption.textContent).toBe("Disarmed");
      expect(button("disarm").disabled).toBe(true);
      expect(screen.queryByTestId("editor-inline-stop-apply")).toBeNull();
    }
    expect(paperClient[intent.method]).toHaveBeenCalledTimes(before + 1);
    expect(paperClient.getStatus).toHaveBeenCalledTimes(
      intent.id === "refresh" || (outcome === "success" && intent.id !== "disarm") ? 2 : 1,
    );
  });
});

it.each(intents.filter(i => i.id === "pause" || i.id === "resume" || i.id === "apply"))(
  "$idle stays busy through the post-command status re-read", async (intent) => {
    const paperClient = client();
    await mount(paperClient);
    const reconcile = deferred<PaperStatus>();
    paperClient.getStatus.mockReturnValueOnce(reconcile.promise);
    fireEvent.click(button(intent.id));
    await waitFor(() => expect(paperClient.getStatus).toHaveBeenCalledTimes(2));
    expect(button(intent.id).getAttribute("aria-busy")).toBe("true");
    expect(button(intent.id).disabled).toBe(true);
    expect(live().textContent).toBe(intent.active);
    fireEvent.click(button("refresh"));
    expect(paperClient.getStatus).toHaveBeenCalledTimes(2);
    await act(async () => reconcile.resolve({ ...armed, entries_paused: true }));
    idle(intent.id, intent.idle);
    expect(screen.getByTestId("inline-stop-caption").textContent).toBe("Armed at kraken SUIUSD · Entries paused");
  },
);

it("keeps empty New stop idle and invalid; unarmed commands remain disabled", async () => {
  const paperClient = client();
  render(<EditorInlineStopControl paperClient={paperClient} />);
  await screen.findByTestId("editor-inline-stop-new-stop");
  expect(button("apply").disabled).toBe(true);
  expect(screen.getByTestId("editor-inline-stop-new-stop").getAttribute("aria-invalid")).toBe("true");
  for (const intent of intents) {
    expect(button(intent.id).getAttribute("aria-busy")).toBe("false");
    expect(button(intent.id).getAttribute("aria-keyshortcuts")).toBe("Enter Space");
  }
  fireEvent.click(button("apply"));
  expect(paperClient.raiseStop).not.toHaveBeenCalled();
  cleanup();
  paperClient.getStatus.mockResolvedValue({ schema_version: "1", armed: false });
  render(<EditorInlineStopControl paperClient={paperClient} />);
  await screen.findByTestId("editor-inline-stop-empty");
  for (const id of ["pause", "resume", "disarm"]) {
    expect(button(id).disabled).toBe(true);
    expect(button(id).getAttribute("aria-busy")).toBe("false");
    expect(button(id).getAttribute("aria-keyshortcuts")).toBe("Enter Space");
  }
  expect(screen.getByTestId("inline-stop-caption").textContent).toBe("Disarmed");
});

it.each(intents.filter(i => i.id === "pause" || i.id === "resume" || i.id === "apply"))(
  "$idle clears busy even when the reconciliation read fails", async (intent) => {
    const paperClient = client();
    await mount(paperClient);
    const reconcile = deferred<PaperStatus>();
    paperClient.getStatus.mockReturnValueOnce(reconcile.promise);
    fireEvent.click(button(intent.id));
    await waitFor(() => expect(paperClient.getStatus).toHaveBeenCalledTimes(2));
    expect(button(intent.id).disabled).toBe(true);
    await act(async () => reconcile.reject(new Error("read lost")));
    idle(intent.id, intent.idle);
    expect(button(intent.id).disabled).toBe(false);
    expect(screen.getByTestId("editor-inline-stop-unknown").textContent).toBe(
      "Status refresh failed: read lost. The command was confirmed; refresh to reconcile.",
    );
  },
);

it("preserves loading/unavailable captions and announces a recovery Refresh", async () => {
  const paperClient = client();
  const initial = deferred<PaperStatus>();
  paperClient.getStatus.mockReturnValueOnce(initial.promise);
  render(<EditorInlineStopControl paperClient={paperClient} />);
  expect(screen.getByTestId("editor-inline-stop-loading").textContent).toBe("Checking paper status…");
  expect(screen.getByTestId("inline-stop-caption").textContent).toBe("Reading paper status…");
  await act(async () => initial.reject(new Error("offline")));
  expect(screen.getByTestId("editor-inline-stop-unavailable").textContent).toBe("Paper status unavailable");
  expect(screen.getByTestId("inline-stop-caption").textContent).toBe("Status read failed; refresh to reconcile");
  const recovery = deferred<PaperStatus>();
  paperClient.getStatus.mockReturnValueOnce(recovery.promise);
  fireEvent.click(button("refresh"));
  expect(button("refresh").getAttribute("aria-busy")).toBe("true");
  expect(button("refresh").disabled).toBe(true);
  expect(live().textContent).toBe("Refreshing…");
  fireEvent.click(button("refresh"));
  expect(paperClient.getStatus).toHaveBeenCalledTimes(2);
  await act(async () => recovery.resolve(armed));
  idle("refresh", "Refresh status");
  expect(screen.getByTestId("inline-stop-caption").textContent).toBe("Armed at kraken SUIUSD · Entries active");
});

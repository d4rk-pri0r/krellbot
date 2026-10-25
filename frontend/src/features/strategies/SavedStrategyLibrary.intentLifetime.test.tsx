import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SavedStrategyLibrary,
  type LibraryClient,
  type OwnedDraftSummary,
  type OwnedRevisionBytes,
} from "./SavedStrategyLibrary";

afterEach(cleanup);

/**
 * Intent-lifetime regressions for the library's editor-changing reads.
 *
 * Only the I/O boundary (LibraryClient) is faked with deterministic
 * deferred promises; every handler below runs the real component. Each
 * test holds a Reopen/Copy read in flight across a newer editor intent
 * (New owned strategy), an unmount, or a client replacement, then
 * settles the old read and asserts the library's read-intent contract:
 * a superseded read must not change the host editor or this library's
 * busy/error state, while a current-generation read must still return
 * the actual stored bytes or the actual error.
 */

const rows: OwnedDraftSummary[] = ["rev-a", "rev-b"].map((revision_id) => ({
  revision_id,
  strategy_id: "intent-lifetime-test",
  parent_revision_id: null,
  state: "draft",
  runnable: false,
  created_at: "2026-10-25T10:00:00Z",
  id: "intent-lifetime-test",
  label: `Intent ${revision_id}`,
  pair: "SUIUSD",
  timeframe: "1h",
}));

type ReadGate = {
  promise: Promise<OwnedRevisionBytes>;
  resolve: (value: OwnedRevisionBytes) => void;
  reject: (reason: Error) => void;
};

function deferredRead(): ReadGate {
  let resolve!: (value: OwnedRevisionBytes) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<OwnedRevisionBytes>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

/**
 * Every client.getJson call hands back its own deferred gate, recorded
 * in order, so a test can settle exactly the read it wants — including
 * reads started after an invalidation.
 */
function gatedClient(rowList: OwnedDraftSummary[] = rows): {
  client: LibraryClient;
  reads: ReadGate[];
} {
  const reads: ReadGate[] = [];
  const client: LibraryClient = {
    listOwned: vi.fn().mockResolvedValue(rowList),
    getJson: vi.fn(() => {
      const gate = deferredRead();
      reads.push(gate);
      return gate.promise;
    }),
  };
  return { client, reads };
}

/** The actual stored bytes a given gated read resolves with. */
function storedBytes(readIndex: number): string {
  return JSON.stringify({
    id: "intent-lifetime-test",
    read: `gate-${readIndex}`,
  });
}

function resolveStored(gate: ReadGate, readIndex: number): void {
  gate.resolve({
    revision_id: rows[readIndex].revision_id,
    state: rows[readIndex].state,
    bytes: storedBytes(readIndex),
  });
}

async function mountLibrary(client: LibraryClient) {
  const onReopen = vi.fn();
  const onNewStrategy = vi.fn();
  const onCopyAsNew = vi.fn();
  const view = render(
    <SavedStrategyLibrary
      client={client}
      onReopen={onReopen}
      onNewStrategy={onNewStrategy}
      onCopyAsNew={onCopyAsNew}
    />,
  );
  const renderedRows = await screen.findAllByTestId("library-row");
  const at = (index: number) => ({
    reopen: within(renderedRows[index]).getByRole<HTMLButtonElement>("button", { name: "Reopen" }),
    copy: within(renderedRows[index]).getByTestId<HTMLButtonElement>("library-copy-as-new"),
  });
  return { view, onReopen, onNewStrategy, onCopyAsNew, renderedRows, at };
}

function newStrategyButton(): HTMLButtonElement {
  return screen.getByTestId<HTMLButtonElement>("library-new-owned-strategy");
}

describe("SavedStrategyLibrary — New owned strategy supersedes pending reads", () => {
  it("keeps the new editor: a late Reopen success after New never calls onReopen", async () => {
    const { client, reads } = gatedClient();
    const { onReopen, onNewStrategy, at } = await mountLibrary(client);
    fireEvent.click(at(0).reopen);
    expect(at(0).reopen.disabled).toBe(true);
    fireEvent.click(newStrategyButton());
    expect(onNewStrategy).toHaveBeenCalledTimes(1);
    await act(async () => {
      reads[0].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(0),
      });
    });
    expect(onReopen).not.toHaveBeenCalled();
    // The superseded read's finalizer must not leave the library busy:
    // fresh actions stay available instead of being globally disabled.
    expect(at(0).reopen.disabled).toBe(false);
    expect(at(1).reopen.disabled).toBe(false);
    expect(screen.queryByTestId("library-reopen-error")).toBeNull();
  });

  it("keeps the new editor: a late Copy success after New never calls onCopyAsNew", async () => {
    const { client, reads } = gatedClient();
    const { onCopyAsNew, onNewStrategy, at } = await mountLibrary(client);
    fireEvent.click(at(0).copy);
    expect(at(0).copy.textContent).toBe("Copying as new…");
    fireEvent.click(newStrategyButton());
    expect(onNewStrategy).toHaveBeenCalledTimes(1);
    await act(async () => {
      reads[0].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(0),
      });
    });
    expect(onCopyAsNew).not.toHaveBeenCalled();
    expect(at(0).copy.textContent).toBe("Copy as new");
    expect(at(0).copy.disabled).toBe(false);
    expect(screen.queryByTestId("library-copy-error")).toBeNull();
  });

  it("surfaces no Reopen error for an obsolete read and keeps a fresh action returning real bytes", async () => {
    const { client, reads } = gatedClient();
    const { onReopen, onCopyAsNew, at } = await mountLibrary(client);
    fireEvent.click(at(0).reopen);
    fireEvent.click(newStrategyButton());
    await act(async () => {
      reads[0].reject(new Error("library open failed: 503"));
    });
    expect(screen.queryByTestId("library-reopen-error")).toBeNull();
    // A current-generation action must still work and still receive the
    // actual stored bytes of its own read.
    fireEvent.click(at(0).copy);
    await act(async () => {
      reads[1].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(1),
      });
    });
    expect(onCopyAsNew).toHaveBeenCalledTimes(1);
    expect(onCopyAsNew).toHaveBeenCalledWith(rows[0], storedBytes(1));
    expect(onReopen).not.toHaveBeenCalled();
  });

  it("surfaces no Copy error for an obsolete read and keeps a fresh Reopen returning real bytes", async () => {
    const { client, reads } = gatedClient();
    const { onReopen, at } = await mountLibrary(client);
    fireEvent.click(at(0).copy);
    fireEvent.click(newStrategyButton());
    await act(async () => {
      reads[0].reject(new Error("library open failed: 500"));
    });
    expect(screen.queryByTestId("library-copy-error")).toBeNull();
    fireEvent.click(at(0).reopen);
    await act(async () => {
      reads[1].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(1),
      });
    });
    expect(onReopen).toHaveBeenCalledTimes(1);
    expect(onReopen).toHaveBeenCalledWith(rows[0], storedBytes(1));
  });
});

describe("SavedStrategyLibrary — unmount invalidates pending reads", () => {
  it("never invokes onReopen when a pending Reopen succeeds after unmount", async () => {
    const { client, reads } = gatedClient();
    const { view, onReopen } = await mountLibrary(client);
    fireEvent.click(screen.getAllByRole("button", { name: "Reopen" })[0]);
    view.unmount();
    await act(async () => {
      reads[0].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(0),
      });
    });
    expect(onReopen).not.toHaveBeenCalled();
  });

  it("never invokes onCopyAsNew when a pending Copy settles after unmount", async () => {
    const { client, reads } = gatedClient();
    const { view, onCopyAsNew } = await mountLibrary(client);
    fireEvent.click(screen.getAllByTestId("library-copy-as-new")[0]);
    view.unmount();
    await act(async () => {
      reads[0].reject(new Error("library open failed: 503"));
    });
    expect(onCopyAsNew).not.toHaveBeenCalled();
  });
});

describe("SavedStrategyLibrary — client replacement invalidates old-generation reads", () => {
  it("drops an old client's late Reopen success and error, then serves fresh reads from the new client", async () => {
    const oldLibrary = gatedClient();
    const mounted = await mountLibrary(oldLibrary.client);
    fireEvent.click(mounted.at(0).reopen);
    expect(mounted.at(0).reopen.disabled).toBe(true);

    // Re-render the mounted library with the replacement client.
    const nextLibrary = gatedClient();
    mounted.view.rerender(
      <SavedStrategyLibrary
        client={nextLibrary.client}
        onReopen={mounted.onReopen}
        onNewStrategy={mounted.onNewStrategy}
        onCopyAsNew={mounted.onCopyAsNew}
      />,
    );
    await screen.findAllByTestId("library-row");
    await act(async () => {
      oldLibrary.reads[0].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(0),
      });
    });
    expect(mounted.onReopen).not.toHaveBeenCalled();
    // Stale busy markers from the retired generation must not disable
    // the refreshed library.
    const refreshedRows = screen.getAllByTestId("library-row");
    const refreshedReopen = within(refreshedRows[0]).getByRole<HTMLButtonElement>("button", { name: "Reopen" });
    expect(refreshedReopen.disabled).toBe(false);

    fireEvent.click(refreshedReopen);
    await act(async () => {
      nextLibrary.reads[0].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(1),
      });
    });
    expect(mounted.onReopen).toHaveBeenCalledTimes(1);
    expect(mounted.onReopen).toHaveBeenCalledWith(rows[0], storedBytes(1));
  });

  it("drops an old client's late Copy failure without polluting the refreshed library", async () => {
    const oldLibrary = gatedClient();
    const mounted = await mountLibrary(oldLibrary.client);
    fireEvent.click(mounted.at(0).copy);

    const nextLibrary = gatedClient();
    mounted.view.rerender(
      <SavedStrategyLibrary
        client={nextLibrary.client}
        onReopen={mounted.onReopen}
        onNewStrategy={mounted.onNewStrategy}
        onCopyAsNew={mounted.onCopyAsNew}
      />,
    );
    await screen.findAllByTestId("library-row");
    await act(async () => {
      oldLibrary.reads[0].reject(new Error("library open failed: 500"));
    });
    expect(screen.queryByTestId("library-copy-error")).toBeNull();
    expect(mounted.onCopyAsNew).not.toHaveBeenCalled();

    const refreshedRows = screen.getAllByTestId("library-row");
    const refreshedCopy = within(refreshedRows[0]).getByTestId<HTMLButtonElement>("library-copy-as-new");
    expect(refreshedCopy.disabled).toBe(false);
    fireEvent.click(refreshedCopy);
    await act(async () => {
      nextLibrary.reads[0].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(1),
      });
    });
    expect(mounted.onCopyAsNew).toHaveBeenCalledTimes(1);
    expect(mounted.onCopyAsNew).toHaveBeenCalledWith(rows[0], storedBytes(1));
  });
});

describe("SavedStrategyLibrary — current-generation actions keep exact contracts", () => {
  it("still passes the clicked summary and the actual stored bytes to onReopen (control)", async () => {
    const { client, reads } = gatedClient();
    const { onReopen, at } = await mountLibrary(client);
    fireEvent.click(at(1).reopen);
    await act(async () => {
      reads[0].resolve({
        revision_id: rows[1].revision_id,
        state: rows[1].state,
        bytes: storedBytes(0),
      });
    });
    expect(onReopen).toHaveBeenCalledTimes(1);
    expect(onReopen).toHaveBeenCalledWith(rows[1], storedBytes(0));
    expect(client.getJson).toHaveBeenCalledWith("rev-b");
    expect(at(1).reopen.disabled).toBe(false);
  });

  it("still surfaces a current Copy failure with its real error text", async () => {
    const { client, reads } = gatedClient();
    const { onCopyAsNew, at } = await mountLibrary(client);
    fireEvent.click(at(0).copy);
    await act(async () => {
      reads[0].reject(new Error("library open failed: 503"));
    });
    const banner = screen.getByTestId("library-copy-error");
    expect(banner.getAttribute("role")).toBe("alert");
    expect(banner.textContent).toBe("Copy as new failed: library open failed: 503");
    expect(onCopyAsNew).not.toHaveBeenCalled();
    expect(at(0).copy.textContent).toBe("Copy as new");
    expect(at(0).copy.disabled).toBe(false);
  });

  it("still supports parallel Copy requests in one generation, settling independently with real bytes", async () => {
    const { client, reads } = gatedClient();
    const { onCopyAsNew, at } = await mountLibrary(client);
    fireEvent.click(at(0).copy);
    fireEvent.click(at(1).copy);
    expect(at(0).copy.textContent).toBe("Copying as new…");
    expect(at(1).copy.textContent).toBe("Copying as new…");
    await act(async () => {
      reads[0].resolve({
        revision_id: rows[0].revision_id,
        state: rows[0].state,
        bytes: storedBytes(0),
      });
    });
    expect(onCopyAsNew).toHaveBeenCalledTimes(1);
    expect(onCopyAsNew).toHaveBeenCalledWith(rows[0], storedBytes(0));
    expect(at(1).copy.textContent).toBe("Copying as new…");
    await act(async () => {
      reads[1].resolve({
        revision_id: rows[1].revision_id,
        state: rows[1].state,
        bytes: storedBytes(1),
      });
    });
    expect(onCopyAsNew).toHaveBeenCalledTimes(2);
    expect(onCopyAsNew).toHaveBeenNthCalledWith(2, rows[1], storedBytes(1));
    expect(at(0).copy.textContent).toBe("Copy as new");
    expect(at(1).copy.textContent).toBe("Copy as new");
    expect(client.getJson).toHaveBeenCalledTimes(2);
  });
});

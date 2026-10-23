import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SavedStrategyLibrary, type LibraryClient, type OwnedDraftSummary } from "./SavedStrategyLibrary";

afterEach(cleanup);

function row(state: OwnedDraftSummary["state"]): OwnedDraftSummary {
  return {
    revision_id: state, strategy_id: "local-test", parent_revision_id: null,
    state, runnable: state !== "draft", created_at: "2026-10-16T10:00:00Z",
    id: "local-test", label: `LOCAL TEST ${state}`, pair: "SUIUSD", timeframe: "1h",
  };
}

// Substitute only the client boundary so the real component logic runs.
function client(rows: OwnedDraftSummary[]): LibraryClient {
  return {
    listOwned: async () => rows,
    getJson: async () => { throw new Error("Unexpected revision read"); },
  };
}
const twoRows = [row("draft"), row("validated")];
const noop = (): void => {};
async function mount() {
  render(<SavedStrategyLibrary client={client(twoRows)} onReopen={noop} />);
  await screen.findByTestId("library-search-count");
}

describe("SavedStrategyLibrary search toolbar accessibility", () => {
  it("gives the existing search input a structural id without renaming it", async () => {
    await mount();
    const input = screen.getByTestId<HTMLInputElement>("library-search");
    expect(input.getAttribute("id")).toBe("library-search");
    expect(input.getAttribute("aria-label")).toBe("Search saved strategies");
    expect(input.getAttribute("aria-keyshortcuts")).toBe("Control+F Meta+F");
    expect(screen.queryByLabelText("Search label, id, pair or timeframe")).toBeNull();
    expect(document.getElementById("library-search")).toBe(input);
  });

  it("announces the clear shortcut on the conditionally rendered clear button", async () => {
    await mount();
    expect(screen.queryByTestId("library-search-clear")).toBeNull();
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "draft" } });
    const clear = screen.getByTestId<HTMLButtonElement>("library-search-clear");
    expect(clear.getAttribute("aria-label")).toBe("Clear search query");
    expect(clear.getAttribute("aria-keyshortcuts")).toBe("Escape");
    expect(clear.textContent).toBe("Clear search");
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "  " } });
    expect(screen.queryByTestId("library-search-clear")).toBeNull();
  });
  it("keeps the state filter label binding and announces its shortcut", async () => {
    await mount();
    const select = screen.getByTestId<HTMLSelectElement>("library-state-filter");
    expect(screen.getByLabelText("State")).toBe(select);
    expect(select.getAttribute("id")).toBe("library-state-filter");
    expect(select.getAttribute("aria-keyshortcuts")).toBe("Control+Alt+S Meta+Alt+S");
  });

  it("keeps the in-input Escape clear behavior byte-equal in effect", async () => {
    await mount();
    const input = screen.getByTestId<HTMLInputElement>("library-search");
    fireEvent.change(input, { target: { value: "draft" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
    expect(screen.queryByTestId("library-search-clear")).toBeNull();
    expect(screen.getAllByTestId("library-row")).toHaveLength(2);
  });

  it("honors the announced Escape on the Clear control itself and returns focus to search", async () => {
    await mount();
    const input = screen.getByTestId<HTMLInputElement>("library-search");
    fireEvent.change(input, { target: { value: "validated" } });
    const clear = screen.getByTestId<HTMLButtonElement>("library-search-clear");
    clear.focus();
    expect(document.activeElement).toBe(clear);
    expect(fireEvent.keyDown(clear, { key: "Escape" })).toBe(false);
    expect(input.value).toBe("");
    expect(screen.queryByTestId("library-search-clear")).toBeNull();
    expect(document.activeElement).toBe(input);
    expect(screen.getAllByTestId("library-row")).toHaveLength(2);
  });

  it("moves focus to search with the announced Control+F chord from inside the library", async () => {
    await mount();
    const input = screen.getByTestId<HTMLInputElement>("library-search");
    const other = screen.getAllByRole<HTMLButtonElement>("button", {
      name: /compare revisions of/i,
    })[0];
    other.focus();
    expect(document.activeElement).toBe(other);
    expect(fireEvent.keyDown(other, { key: "f", ctrlKey: true })).toBe(false);
    expect(document.activeElement).toBe(input);
  });

  it("moves focus to the state filter with the announced Control+Alt+S chord", async () => {
    await mount();
    const select = screen.getByTestId<HTMLSelectElement>("library-state-filter");
    const input = screen.getByTestId<HTMLInputElement>("library-search");
    input.focus();
    expect(document.activeElement).toBe(input);
    expect(
      fireEvent.keyDown(input, { key: "s", ctrlKey: true, altKey: true }),
    ).toBe(false);
    expect(document.activeElement).toBe(select);
  });
});

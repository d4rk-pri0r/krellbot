import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SavedStrategyLibrary, type LibraryClient, type OwnedDraftSummary } from "./SavedStrategyLibrary";
import { summarizeDraftState } from "./draftStateLabel";

afterEach(cleanup);

function row(state: OwnedDraftSummary["state"]): OwnedDraftSummary {
  return {
    revision_id: state, strategy_id: "local-test", parent_revision_id: null,
    state, runnable: state !== "draft", created_at: "2026-10-16T10:00:00Z",
    id: "local-test", label: `LOCAL TEST ${state}`, pair: "SUIUSD", timeframe: "1h",
  };
}

// Substitute only the client boundary to control asynchronous load/refresh races.
function client(rows: OwnedDraftSummary[]): LibraryClient {
  return {
    listOwned: async () => rows,
    getJson: async () => { throw new Error("Unexpected revision read"); },
  };
}
const twoRows = [row("draft"), row("validated")];
const noop = (): void => {};
async function mount() {
  const view = render(<SavedStrategyLibrary client={client(twoRows)} onReopen={noop} />);
  await screen.findByTestId("library-search-count");
  return view;
}
function select(state: string) {
  fireEvent.change(screen.getByTestId("library-state-filter"), { target: { value: state } });
}
function count(text: string) {
  expect(screen.getByTestId("library-search-count").textContent).toBe(text);
}

describe("SavedStrategyLibrary state filter", () => {
  it("adds the missing native select to the existing toolbar (RED on the old toolbar)", async () => {
    await mount();
    const control = screen.getByTestId("library-state-filter");
    expect(control.tagName).toBe("SELECT");
    expect(control.closest(".kbot-strategy-library__toolbar")).not.toBeNull();
    expect(screen.getByLabelText("State")).toBe(control);
    expect(control.getAttribute("id")).toBe("library-state-filter");
  });

  it("defaults to all with exactly the documented ordered options and total count", async () => {
    await mount();
    const control = screen.getByRole<HTMLSelectElement>("combobox", { name: "State" });
    expect(control.value).toBe("all");
    expect(within(control).getAllByRole<HTMLOptionElement>("option").map(option => [option.value, option.textContent])).toEqual([
      ["all", "All states"],
      ...(["draft", "validated", "deployed", "archived"] as const).map(state => [state, summarizeDraftState(state).label]),
    ]);
    count("2 of 2 saved revisions");
  });

  it("unmounts other states and preserves the visible row's state chip", async () => {
    await mount();
    select("draft");
    expect(screen.getAllByTestId("library-row")).toHaveLength(1);
    expect(screen.queryByText("LOCAL TEST validated")).toBeNull();
    const chip = screen.getByTestId("library-row").querySelector("[data-state]");
    expect(chip?.getAttribute("data-state")).toBe("draft");
    expect(chip?.textContent).toBe("Draft");
    count("1 of 2 saved revisions");
  });

  it("restores all rows and applies search only within the selected state", async () => {
    await mount();
    select("draft");
    select("all");
    expect(screen.getAllByTestId("library-row")).toHaveLength(2);
    count("2 of 2 saved revisions");
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "valid" } });
    expect(screen.getByText("LOCAL TEST validated")).toBeDefined();
    select("draft");
    expect(screen.queryByText("LOCAL TEST validated")).toBeNull();
    expect(screen.getByTestId("library-search-empty")).toBeDefined();
    count("0 of 2 saved revisions");
    fireEvent.keyDown(screen.getByTestId("library-search"), { key: "Escape" });
    expect(screen.getByRole<HTMLSelectElement>("combobox").value).toBe("draft");
    expect(screen.getByRole<HTMLInputElement>("searchbox").value).toBe("");
    count("1 of 2 saved revisions");
  });

  it("preserves state and search through a pending client-driven row refresh", async () => {
    const view = await mount();
    select("deployed");
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "deployed" } });
    let resolve!: (rows: OwnedDraftSummary[]) => void;
    const pending = new Promise<OwnedDraftSummary[]>(done => { resolve = done; });
    view.rerender(<SavedStrategyLibrary client={{ ...client([]), listOwned: () => pending }} onReopen={noop} />);
    expect(screen.getByTestId("library-loading")).toBeDefined();
    expect(screen.queryByTestId("library-state-filter")).toBeNull();
    await act(async () => { resolve([...twoRows, row("deployed")]); });
    expect(screen.getByRole<HTMLSelectElement>("combobox").value).toBe("deployed");
    expect(screen.getByRole<HTMLInputElement>("searchbox").value).toBe("deployed");
    expect(screen.getAllByTestId("library-row")).toHaveLength(1);
    expect(screen.getByText("LOCAL TEST deployed")).toBeDefined();
    count("1 of 3 saved revisions");
  });

  it("keeps search clear independent of state selection", async () => {
    await mount();
    select("validated");
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "missing" } });
    fireEvent.click(screen.getByTestId("library-search-clear"));
    expect(screen.getByRole<HTMLSelectElement>("combobox").value).toBe("validated");
    count("1 of 2 saved revisions");
  });

  it("never renders the filter for loading, empty or failed inventory", async () => {
    const view = render(<SavedStrategyLibrary client={client([])} onReopen={noop} />);
    expect(screen.queryByTestId("library-state-filter")).toBeNull();
    await screen.findByTestId("library-empty");
    expect(screen.queryByTestId("library-state-filter")).toBeNull();
    view.rerender(<SavedStrategyLibrary client={{ ...client([]), listOwned: async () => { throw new Error("local list failure"); } }} onReopen={noop} />);
    await screen.findByTestId("library-error");
    expect(screen.queryByTestId("library-state-filter")).toBeNull();
  });
});

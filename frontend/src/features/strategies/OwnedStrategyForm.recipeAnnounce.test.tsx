import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { OwnedStrategyForm } from "./OwnedStrategyForm";
import { seedOwnedStrategyForm, seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(cleanup);

const single = "Recipe: close versus one average. Enter and exit comparisons now mean close versus the single average. The Fast average length field is hidden.";
const cross = "Recipe: two-average crossover. Enter and exit comparisons now mean fast average versus slow average. A Fast average length field has appeared.";

function Harness() {
  const [state, setState] = useState(seedOwnedStrategyForm());
  return <OwnedStrategyForm state={state} basePack={seedOwnedStrategyPack(state.name)}
    onStateChange={setState} onApply={() => {}} />;
}

it("keeps one atomic polite status mounted with the actual recipe meaning on repeated toggles", () => {
  const view = render(<Harness />);
  const status = screen.getByTestId("owned-strategy-form-recipe-status");
  const recipe = screen.getByLabelText(/^recipe$/i);
  expect(status.tagName).toBe("P");
  expect(status.id).toBe("owned-strategy-form-recipe-status");
  expect(status.className).toBe("kbot-owned-strategy-form__recipe-status");
  expect(status.getAttribute("role")).toBe("status");
  expect(status.getAttribute("aria-live")).toBe("polite");
  expect(status.getAttribute("aria-atomic")).toBe("true");
  expect(recipe.parentElement?.nextElementSibling).toBe(status);
  expect(status.textContent).toBe(single);
  expect(document.getElementById("kbot-owned-strategy-fastLength")).toBeNull();

  const observer = new MutationObserver(() => {});
  observer.observe(status, { childList: true, characterData: true, subtree: true });
  try {
    view.rerender(<Harness />);
    fireEvent.change(screen.getByLabelText(/^strategy name/i), { target: { value: "Renamed" } });
    expect(observer.takeRecords()).toHaveLength(0);
    for (const value of ["ma_cross", "close_vs_ma", "ma_cross", "close_vs_ma"]) {
      fireEvent.change(recipe, { target: { value } });
      expect(observer.takeRecords()).toHaveLength(1);
      expect(screen.getByTestId("owned-strategy-form-recipe-status")).toBe(status);
      expect(status.textContent).toBe(value === "ma_cross" ? cross : single);
      expect(document.getElementById("kbot-owned-strategy-fastLength") !== null).toBe(value === "ma_cross");
    }
  } finally {
    observer.disconnect();
  }
});

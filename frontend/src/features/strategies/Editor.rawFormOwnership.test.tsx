import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Editor, type StrategyClient } from "./Editor";
import { seedOwnedStrategyPack } from "./ownedStrategy";

afterEach(cleanup);
function setup() {
  // Synthetic client; browser coverage separately verifies backend persistence.
  const client: StrategyClient = {
    create: vi.fn(), edit: vi.fn(async (_id, pack) => ({ revision_id: "edited", state: "draft" as const, pack, errors: [] })),
    validate: vi.fn(), arm: vi.fn(),
  };
  const pack = seedOwnedStrategyPack("Synthetic mixed editing");
  render(<Editor client={client} initial={{ revision_id: "original", state: "draft", bytes: JSON.stringify(pack) }} />);
  const raw = screen.getByLabelText(/raw json/i) as HTMLTextAreaElement;
  return { client, raw };
}

it("reflects a supported raw edit and preserves it through another readable edit and Save", async () => {
  const { client, raw } = setup();
  const pack = JSON.parse(raw.value);
  pack.indicators.ma.len = 41;
  fireEvent.change(raw, { target: { value: JSON.stringify(pack) } });
  expect((screen.getByLabelText("Average length (bars)") as HTMLInputElement).value).toBe("41");
  fireEvent.change(screen.getByLabelText("Protective stop percent"), { target: { value: "7" } });
  expect(JSON.parse(raw.value).indicators.ma.len).toBe(41);
  expect(JSON.parse(raw.value).risk.stop.pct).toBe(7);
  fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
  await waitFor(() => expect(client.edit).toHaveBeenCalled());
  expect(vi.mocked(client.edit).mock.calls[0][1]).toMatchObject({ indicators: { ma: { len: 41 } }, risk: { stop: { pct: 7 } } });
  expect(client.create).not.toHaveBeenCalled();
  expect(client.validate).not.toHaveBeenCalled();
  expect(client.arm).not.toHaveBeenCalled();
});

it("preserves incomplete form input until the user deliberately edits raw JSON", () => {
  const { raw } = setup();
  fireEvent.change(screen.getByLabelText("Average length (bars)"), { target: { value: "" } });
  fireEvent.change(screen.getByLabelText("Protective stop percent"), { target: { value: "7" } });
  expect((screen.getByLabelText("Average length (bars)") as HTMLInputElement).value).toBe("");
  fireEvent.change(screen.getByLabelText("Average length (bars)"), { target: { value: "42" } });
  expect(JSON.parse(raw.value).indicators.ma.len).toBe(42);
  expect(JSON.parse(raw.value).risk.stop.pct).toBe(7);
});

it.each(["{ invalid", JSON.stringify({ unsupported: { nested: true } })])("leaves unsupported raw bytes untouched: %s", (text) => {
  const { raw } = setup();
  fireEvent.change(raw, { target: { value: text } });
  expect(raw.value).toBe(text);
  expect(screen.queryByTestId("owned-strategy-form")).toBeNull();
});

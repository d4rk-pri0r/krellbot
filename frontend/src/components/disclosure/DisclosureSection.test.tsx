import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DisclosureSection } from "./DisclosureSection";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("DisclosureSection progressive disclosure", () => {
  it("keeps children mounted while collapsed so field values survive", () => {
    render(
      <DisclosureSection title="Advanced" data-testid="disc" defaultOpen={false}>
        <input data-testid="disc-input" defaultValue="kept" />
      </DisclosureSection>,
    );
    expect(screen.getByTestId("disc").getAttribute("data-open")).toBe("0");
    const input = screen.getByTestId("disc-input") as HTMLInputElement;
    expect(input.value).toBe("kept");
    fireEvent.change(input, { target: { value: "edited" } });
    expect(input.value).toBe("edited");
    // Still collapsed; value preserved without reopening.
    expect(screen.getByTestId("disc").getAttribute("data-open")).toBe("0");
    fireEvent.click(screen.getByTestId("disc-toggle"));
    expect(screen.getByTestId("disc").getAttribute("data-open")).toBe("1");
    expect((screen.getByTestId("disc-input") as HTMLInputElement).value).toBe(
      "edited",
    );
  });

  it("forceOpen surfaces a caution badge and opens the body", () => {
    const { rerender } = render(
      <DisclosureSection title="Keys" data-testid="keys" defaultOpen={false}>
        <p>body</p>
      </DisclosureSection>,
    );
    expect(screen.getByTestId("keys").getAttribute("data-open")).toBe("0");
    rerender(
      <DisclosureSection
        title="Keys"
        data-testid="keys"
        defaultOpen={false}
        forceOpen
      >
        <p>body</p>
      </DisclosureSection>,
    );
    expect(screen.getByTestId("keys").getAttribute("data-open")).toBe("1");
    expect(screen.getByText("Needs attention")).toBeDefined();
  });

  it("persists open state under storageKey", () => {
    render(
      <DisclosureSection
        title="Journal"
        data-testid="journal"
        storageKey="krellbot.test.disclosure.journal"
        defaultOpen={false}
      >
        <p>rows</p>
      </DisclosureSection>,
    );
    fireEvent.click(screen.getByTestId("journal-toggle"));
    expect(window.localStorage.getItem("krellbot.test.disclosure.journal")).toBe(
      "1",
    );
    cleanup();
    render(
      <DisclosureSection
        title="Journal"
        data-testid="journal"
        storageKey="krellbot.test.disclosure.journal"
        defaultOpen={false}
      >
        <p>rows</p>
      </DisclosureSection>,
    );
    expect(screen.getByTestId("journal").getAttribute("data-open")).toBe("1");
  });
});

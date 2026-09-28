import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EdgeRefusalNotice } from "./EdgeRefusalNotice";
import type { EdgeRefusal } from "./edges";

afterEach(cleanup);

const REASONS: EdgeRefusal[] = [
  "timeframe missing",
  "timeframe invalid",
  "timeframe mismatch",
];

describe("EdgeRefusalNotice", () => {
  it("renders the exact reason string verbatim", () => {
    for (const reason of REASONS) {
      cleanup();
      const { container } = render(
        <EdgeRefusalNotice reason={reason} onDismiss={() => {}} />,
      );
      const alert = screen.getByRole("alert");
      expect(alert.textContent).toContain(reason);
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
      const exactNodes: Text[] = [];
      let node = walker.nextNode();
      while (node) {
        if (node.nodeValue === reason) exactNodes.push(node as Text);
        node = walker.nextNode();
      }
      expect(exactNodes.length).toBeGreaterThanOrEqual(1);
      const padded = ` ${alert.textContent ?? ""} `;
      for (const paraphrase of [
        `Refused: ${reason}`,
        `Refusal: ${reason}`,
        `Cannot connect: ${reason}`,
      ]) {
        expect(padded).not.toContain(paraphrase);
      }
    }
  });

  it("exposes a single element with role='alert'", () => {
    render(
      <EdgeRefusalNotice reason="timeframe missing" onDismiss={() => {}} />,
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("renders a real Dismiss edge refusal button that is enabled and focusable", () => {
    render(
      <EdgeRefusalNotice reason="timeframe missing" onDismiss={() => {}} />,
    );
    const button = screen.getByRole("button", { name: "Dismiss edge refusal" });
    expect(button).toBeDefined();
    expect(button.tagName).toBe("BUTTON");
    expect((button as HTMLButtonElement).disabled).toBe(false);
    expect((button as HTMLButtonElement).tabIndex).not.toBe(-1);
  });

  it("invokes the provided onDismiss handler when the button is clicked", () => {
    const onDismiss = vi.fn();
    render(
      <EdgeRefusalNotice reason="timeframe mismatch" onDismiss={onDismiss} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss edge refusal" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
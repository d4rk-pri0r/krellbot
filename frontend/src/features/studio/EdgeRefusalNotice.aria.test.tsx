/**
 * EdgeRefusalNotice keyboard / screen-reader announcement slice.
 *
 * A keyboard-only / screen-reader operator who drags an incompatible
 * edge in Studio must be able to (1) hear the refusal mount as an
 * assertive live announcement, (2) locate the alert through the stable
 * test id, (3) Tab onto the dismiss control and activate it with Enter
 * or Space — not only a mouse click — and (4) land back on the
 * GraphCanvas container so connecting can continue without hunting
 * the page.
 *
 * Every ``aria-describedby`` value asserted here is resolved against
 * the real document so the wiring can never reference a detached id.
 *
 * RED on the base where the alert div carried no aria-live, no
 * data-testid, no message id, and the button had neither key
 * activation nor any focus-return wiring.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { Node, OnConnect } from "@xyflow/react";
import type { JSX } from "react";
import { EdgeRefusalNotice } from "./EdgeRefusalNotice";
import { GraphCanvas } from "./GraphCanvas";
import type { EdgeRefusal } from "./edges";

afterEach(cleanup);

const NOTICE = "edge-refusal-notice";
const MESSAGE_ID = "edge-refusal-notice-message";
const DISMISS = "edge-refusal-notice-dismiss";

function notice(): HTMLElement | null {
  return document.querySelector(`[data-testid="${NOTICE}"]`);
}

function dismissButton(): HTMLButtonElement {
  return screen.getByTestId(DISMISS) as HTMLButtonElement;
}

function message(): HTMLElement | null {
  return document.getElementById(MESSAGE_ID);
}

describe("EdgeRefusalNotice aria — assertive announcement wiring", () => {
  it("mounts with role=alert and aria-live=assertive on the same element", () => {
    render(
      <EdgeRefusalNotice reason="timeframe mismatch" onDismiss={() => {}} />,
    );
    const alert = notice();
    expect(alert).not.toBeNull();
    expect(alert!.getAttribute("role")).toBe("alert");
    expect(alert!.getAttribute("aria-live")).toBe("assertive");
  });

  it("exposes exactly one element with the stable alert test id", () => {
    render(
      <EdgeRefusalNotice reason="timeframe mismatch" onDismiss={() => {}} />,
    );
    expect(screen.getAllByTestId(NOTICE)).toHaveLength(1);
  });

  it("keeps the visible verbatim label and gives it the message id", () => {
    render(
      <EdgeRefusalNotice reason="timeframe mismatch" onDismiss={() => {}} />,
    );
    const node = message();
    expect(node).not.toBeNull();
    expect(node!.tagName).toBe("P");
    expect(node!.textContent).toBe("Timeframe mismatch");
  });

  it("announces every known refusal reason through the same message id", () => {
    const cases: Record<string, string> = {
      "timeframe missing": "Timeframe missing",
      "timeframe invalid": "Timeframe invalid",
      "timeframe mismatch": "Timeframe mismatch",
    };
    for (const [reason, label] of Object.entries(cases)) {
      cleanup();
      render(
        <EdgeRefusalNotice
          reason={reason as EdgeRefusal}
          onDismiss={() => {}}
        />,
      );
      expect(message()?.textContent).toBe(label);
      expect(notice()?.getAttribute("aria-live")).toBe("assertive");
    }
  });

  it("announces an unknown refusal reason without paraphrasing it away", () => {
    // summarizeEdgeRefusal is defensive about future/unknown reasons;
    // the notice must render whatever it resolves to, verbatim.
    render(
      <EdgeRefusalNotice
        reason={"venue_unreachable" as unknown as EdgeRefusal}
        onDismiss={() => {}}
      />,
    );
    expect(message()?.textContent).toBe("Venue unreachable");
    cleanup();
    render(
      <EdgeRefusalNotice
        reason={"" as unknown as EdgeRefusal}
        onDismiss={() => {}}
      />,
    );
    expect(message()?.textContent).toBe("(unknown refusal)");
  });

  it("wires the dismiss button with the test id and announcement hints", () => {
    render(
      <EdgeRefusalNotice reason="timeframe mismatch" onDismiss={() => {}} />,
    );
    const button = dismissButton();
    expect(button.tagName).toBe("BUTTON");
    expect(button.getAttribute("type")).toBe("button");
    expect(button.getAttribute("aria-keyshortcuts")).toBe("Enter");
    expect(button.getAttribute("aria-describedby")).toBe(MESSAGE_ID);
    expect(message()).not.toBeNull();
    expect(button.textContent).toBe("Dismiss edge refusal");
  });

  it("exposes the accessible name Dismiss edge refusal", () => {
    render(
      <EdgeRefusalNotice reason="timeframe mismatch" onDismiss={() => {}} />,
    );
    expect(
      screen.getByRole("button", { name: "Dismiss edge refusal" }),
    ).toBeDefined();
  });
});

describe("EdgeRefusalNotice aria — keyboard activation", () => {
  it("invokes onDismiss exactly once for Enter", () => {
    const onDismiss = vi.fn();
    render(
      <EdgeRefusalNotice
        reason="timeframe mismatch"
        onDismiss={onDismiss}
      />,
    );
    fireEvent.keyDown(dismissButton(), { key: "Enter" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("invokes onDismiss exactly once for Space", () => {
    const onDismiss = vi.fn();
    render(
      <EdgeRefusalNotice reason="timeframe missing" onDismiss={onDismiss} />,
    );
    fireEvent.keyDown(dismissButton(), { key: " " });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("ignores unrelated keys and held-key repeats", () => {
    const onDismiss = vi.fn();
    render(
      <EdgeRefusalNotice
        reason="timeframe mismatch"
        onDismiss={onDismiss}
      />,
    );
    const button = dismissButton();
    fireEvent.keyDown(button, { key: "Tab" });
    fireEvent.keyDown(button, { key: "Escape" });
    fireEvent.keyDown(button, { key: "a" });
    fireEvent.keyDown(button, { key: "Enter", repeat: true });
    fireEvent.keyDown(button, { key: " ", repeat: true });
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("keeps the mouse click path working on its own", () => {
    const onDismiss = vi.fn();
    render(
      <EdgeRefusalNotice
        reason="timeframe invalid"
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(dismissButton());
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

/* ------------------------------------------------------------------ */
/* Focus return through the real GraphCanvas mount                     */
/* ------------------------------------------------------------------ */

let lastOnConnect: OnConnect | null = null;

vi.mock("@xyflow/react", async () => {
  const actual =
    await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  function CapturedReactFlow(props: {
    onConnect?: OnConnect;
    children?: React.ReactNode;
  }): JSX.Element {
    lastOnConnect = props.onConnect ?? null;
    return (
      <div data-testid="react-flow-stub" className="react-flow">
        {props.children}
      </div>
    );
  }
  return { ...actual, ReactFlow: CapturedReactFlow };
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  if (typeof globalThis.ResizeObserver !== "function") {
    globalThis.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
});

function nodeOf(
  id: string,
  timeframe: string | undefined,
): Node<{ timeframe?: string }> {
  return { id, type: "default", position: { x: 0, y: 0 }, data: { timeframe } };
}

function canvasHost(): HTMLElement | null {
  return document.querySelector('[data-testid="graph-canvas"]');
}

function mountRefusedCanvas() {
  render(
    <GraphCanvas
      nodes={[nodeOf("a", "1h"), nodeOf("b", "4h")]}
      edges={[]}
      onAddConnection={() => {}}
    />,
  );
  act(() => {
    lastOnConnect!({
      source: "a",
      target: "b",
      sourceHandle: null,
      targetHandle: null,
    });
  });
  expect(notice()).not.toBeNull();
}

describe("EdgeRefusalNotice aria — focus returns to the GraphCanvas host", () => {
  it("keeps the canvas host as the kbot-graph-canvas graph-canvas element", () => {
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h")]}
        edges={[]}
        onAddConnection={() => {}}
      />,
    );
    const host = canvasHost();
    expect(host).not.toBeNull();
    expect(host!.getAttribute("data-testid")).toBe("graph-canvas");
    expect(host!.getAttribute("class")).toBe("kbot-graph-canvas");
  });

  it("moves focus to the canvas host after Enter dismissal", () => {
    mountRefusedCanvas();
    dismissButton().focus();
    expect(dismissButton()).toBe(document.activeElement);
    fireEvent.keyDown(dismissButton(), { key: "Enter" });
    expect(notice()).toBeNull();
    expect(canvasHost()).toBe(document.activeElement);
  });

  it("moves focus to the canvas host after Space dismissal", () => {
    mountRefusedCanvas();
    dismissButton().focus();
    fireEvent.keyDown(dismissButton(), { key: " " });
    expect(notice()).toBeNull();
    expect(canvasHost()).toBe(document.activeElement);
  });

  it("moves focus to the canvas host after a mouse click dismissal", () => {
    mountRefusedCanvas();
    dismissButton().focus();
    fireEvent.click(dismissButton());
    expect(notice()).toBeNull();
    expect(canvasHost()).toBe(document.activeElement);
  });

  it("does not steal focus while the refusal is simply mounted", () => {
    mountRefusedCanvas();
    expect(canvasHost()).not.toBe(document.activeElement);
  });
});

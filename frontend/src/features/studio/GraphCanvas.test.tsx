import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type {
  Connection,
  Edge,
  Node,
  NodeTypes,
  OnConnect,
} from "@xyflow/react";
import type { JSX } from "react";
import { GraphCanvas } from "./GraphCanvas";
import type { EdgeRefusal } from "./edges";

const here = dirname(fileURLToPath(import.meta.url));

type CapturedReactFlowProps = {
  onConnect?: OnConnect;
  nodes?: Node[];
  edges?: Edge[];
  nodeTypes?: NodeTypes;
  fitView?: boolean;
};

type CapturedReactFlowRendererProps = CapturedReactFlowProps & {
  children?: React.ReactNode;
};

let lastReactFlowProps: CapturedReactFlowProps | null = null;

vi.mock("@xyflow/react", async () => {
  const actual =
    await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  function CapturedReactFlow(
    props: CapturedReactFlowRendererProps,
  ): JSX.Element {
    lastReactFlowProps = props;
    return (
      <div
        data-testid="react-flow-stub"
        className="react-flow"
        role="application"
      >
        {props.children}
      </div>
    );
  }
  return {
    ...actual,
    ReactFlow: CapturedReactFlow,
  };
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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  lastReactFlowProps = null;
});

function nodeOf(
  id: string,
  timeframe: string | undefined,
): Node<{ timeframe?: string }> {
  return {
    id,
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe },
  };
}

function getCaptured(): CapturedReactFlowProps {
  expect(lastReactFlowProps).not.toBeNull();
  return lastReactFlowProps as CapturedReactFlowProps;
}

function connection(source: string, target: string): Connection {
  return {
    source,
    target,
    sourceHandle: null,
    targetHandle: null,
  };
}

function triggerConnect(target: string, source: string = "a"): void {
  act(() => {
    const captured = getCaptured();
    captured.onConnect!(connection(source, target));
  });
}

describe("GraphCanvas — onConnect routes through refuseIncompatibleEdge", () => {
  it("records a connection when both endpoints share 1h", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "1h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    const { onConnect } = getCaptured();
    expect(onConnect).toBeDefined();
    onConnect!(connection("a", "b"));
    expect(onAddConnection).toHaveBeenCalledTimes(1);
    expect(onAddConnection).toHaveBeenCalledWith({
      source: "a",
      target: "b",
      sourceHandle: null,
      targetHandle: null,
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("records a connection when both endpoints share 4h", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "4h"), nodeOf("b", "4h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(onAddConnection).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("records a connection when both endpoints share 1d", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1d"), nodeOf("b", "1d")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(onAddConnection).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses a 1h vs 4h connection and shows the timeframe mismatch notice", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "4h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(onAddConnection).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("timeframe mismatch");
    const walker = document.createTreeWalker(alert, NodeFilter.SHOW_TEXT);
    const exact: Text[] = [];
    let node = walker.nextNode();
    while (node) {
      if (node.nodeValue === "timeframe mismatch") exact.push(node as Text);
      node = walker.nextNode();
    }
    expect(exact.length).toBeGreaterThanOrEqual(1);
  });

  it("refuses a 1h vs 1d connection and shows the timeframe mismatch notice", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "1d")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(onAddConnection).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain(
      "timeframe mismatch",
    );
  });

  it("refuses a connection when the source has no timeframe", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", undefined), nodeOf("b", "1h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(onAddConnection).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("timeframe missing");
  });

  it("refuses a connection when the target has no timeframe", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", undefined)]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(onAddConnection).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain(
      "timeframe missing",
    );
  });

  it("refuses an illegal timeframe (1m) with the timeframe invalid notice", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1m"), nodeOf("b", "1m")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(onAddConnection).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("timeframe invalid");
  });

  it("dismisses the notice when the user clicks Dismiss edge refusal", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "4h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(screen.getByRole("alert")).toBeDefined();
    fireEvent.click(
      screen.getByRole("button", { name: "Dismiss edge refusal" }),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onAddConnection).not.toHaveBeenCalled();
  });

  it("replaces an earlier notice when a second refusal is raised", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[
          nodeOf("a", "1h"),
          nodeOf("b", "4h"),
          nodeOf("c", undefined),
        ]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    const captured = getCaptured();
    triggerConnect("b");
    expect(screen.getByRole("alert").textContent).toContain(
      "timeframe mismatch",
    );
    triggerConnect("c");
    expect(screen.getByRole("alert").textContent).toContain(
      "timeframe missing",
    );
    expect(onAddConnection).not.toHaveBeenCalled();
  });

  it("does not call onAddConnection for a refused edge even if a prior edge succeeded", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[
          nodeOf("a", "1h"),
          nodeOf("b", "1h"),
          nodeOf("c", "1d"),
        ]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    const captured = getCaptured();
    triggerConnect("b");
    triggerConnect("c");
    expect(onAddConnection).toHaveBeenCalledTimes(1);
    expect(onAddConnection).toHaveBeenCalledWith({
      source: "a",
      target: "b",
      sourceHandle: null,
      targetHandle: null,
    });
    expect(screen.getByRole("alert").textContent).toContain(
      "timeframe mismatch",
    );
  });

  it("renders exactly one element with role='alert' on a refusal", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "4h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("renders no notice when a connection is recorded", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "1h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("b");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders the notice with the exact refusal string for every EdgeRefusal value", () => {
    const onAddConnection = vi.fn();
    const cases: {
      sourceTimeframe: string | undefined;
      targetTimeframe: string | undefined;
      reason: EdgeRefusal;
    }[] = [
      {
        sourceTimeframe: undefined,
        targetTimeframe: "1h",
        reason: "timeframe missing",
      },
      {
        sourceTimeframe: "1h",
        targetTimeframe: undefined,
        reason: "timeframe missing",
      },
      {
        sourceTimeframe: "1h",
        targetTimeframe: "4h",
        reason: "timeframe mismatch",
      },
      {
        sourceTimeframe: "1h",
        targetTimeframe: "1d",
        reason: "timeframe mismatch",
      },
      {
        sourceTimeframe: "1m",
        targetTimeframe: "1m",
        reason: "timeframe invalid",
      },
    ];
    for (const { sourceTimeframe, targetTimeframe, reason } of cases) {
      cleanup();
      onAddConnection.mockClear();
      render(
        <GraphCanvas
          nodes={[
            nodeOf("a", sourceTimeframe),
            nodeOf("b", targetTimeframe),
          ]}
          edges={[]}
          onAddConnection={onAddConnection}
        />,
      );
      triggerConnect("b");
      const alert = screen.getByRole("alert");
      expect(alert.textContent).toContain(reason);
      const walker = document.createTreeWalker(
        alert,
        NodeFilter.SHOW_TEXT,
      );
      const exact: Text[] = [];
      let node = walker.nextNode();
      while (node) {
        if (node.nodeValue === reason) exact.push(node as Text);
        node = walker.nextNode();
      }
      expect(exact.length).toBeGreaterThanOrEqual(1);
      expect(onAddConnection).not.toHaveBeenCalled();
    }
  });

  it("forwards the supplied nodes and edges to ReactFlow", () => {
    const onAddConnection = vi.fn();
    const nodes = [nodeOf("a", "1h"), nodeOf("b", "1h")];
    const edges: Edge[] = [
      {
        id: "existing",
        source: "a",
        target: "b",
      },
    ];
    render(
      <GraphCanvas
        nodes={nodes}
        edges={edges}
        onAddConnection={onAddConnection}
      />,
    );
    const captured = getCaptured();
    expect(captured.nodes).toBe(nodes);
    expect(captured.edges).toBe(edges);
  });
});

describe("GraphCanvas — refuses before adding an edge", () => {
  it("does not invoke onAddConnection when the source or target node is missing", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "1h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("ghost");
    expect(onAddConnection).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("routes matching connect attempts through the recorded path", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "1h")]}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    const captured = getCaptured();
    triggerConnect("b");
    triggerConnect("b");
    expect(onAddConnection).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("GraphCanvas — side-effect freedom", () => {
  it("does not read localStorage during a successful connect attempt", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "1h")]}
        edges={[]}
        onAddConnection={() => {}}
      />,
    );
    triggerConnect("b");
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not read localStorage during a refused connect attempt", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem");
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "4h")]}
        edges={[]}
        onAddConnection={() => {}}
      />,
    );
    triggerConnect("b");
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not call fetch during a connect attempt", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <GraphCanvas
        nodes={[nodeOf("a", "1h"), nodeOf("b", "1h")]}
        edges={[]}
        onAddConnection={() => {}}
      />,
    );
    triggerConnect("b");
    triggerConnect("b");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("GraphCanvas — graph library is not loaded from a CDN", () => {
  it("does not reference a remote URL in GraphCanvas.tsx", () => {
    const source = readFileSync(
      resolve(here, "GraphCanvas.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/https?:\/\//);
    expect(source).not.toMatch(/<script\b/i);
    expect(source).not.toMatch(/<link\b/i);
    expect(source).not.toMatch(/cdn\./i);
    expect(source).not.toMatch(/unpkg\./i);
    expect(source).not.toMatch(/jsdelivr\./i);
  });

  it("imports @xyflow/react as a module, not from a CDN", () => {
    const source = readFileSync(
      resolve(here, "GraphCanvas.tsx"),
      "utf8",
    );
    expect(source).toMatch(/from\s+["']@xyflow\/react["']/);
  });
});

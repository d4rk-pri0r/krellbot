import { act, cleanup, render, screen } from "@testing-library/react";
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

const NODE_COUNT = 200;

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

function workloadNodes(): Node<{ timeframe?: string }>[] {
  const nodes: Node<{ timeframe?: string }>[] = [];
  for (let index = 0; index < NODE_COUNT; index += 1) {
    const id = `n${index}`;
    const timeframe =
      index === 0
        ? "1h"
        : index === NODE_COUNT - 1
          ? "4h"
          : "1h";
    nodes.push({
      id,
      type: "default",
      position: { x: index, y: 0 },
      data: { timeframe },
    });
  }
  return nodes;
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

function triggerConnect(target: string, source: string = "n0"): void {
  act(() => {
    const captured = getCaptured();
    captured.onConnect!(connection(source, target));
  });
}

describe("GraphCanvas — 200-node workload still refuses a bad edge", () => {
  it("forwards the full 200-node list to ReactFlow", () => {
    const onAddConnection = vi.fn();
    const nodes = workloadNodes();
    render(
      <GraphCanvas nodes={nodes} edges={[]} onAddConnection={onAddConnection} />,
    );
    const captured = getCaptured();
    expect(captured.nodes).toBe(nodes);
    expect(captured.nodes).toHaveLength(NODE_COUNT);
    expect(captured.nodes?.[0]?.id).toBe("n0");
    expect(captured.nodes?.[0]?.data?.timeframe).toBe("1h");
    expect(captured.nodes?.[1]?.id).toBe("n1");
    expect(captured.nodes?.[1]?.data?.timeframe).toBe("1h");
    expect(captured.nodes?.[NODE_COUNT - 1]?.id).toBe("n199");
    expect(captured.nodes?.[NODE_COUNT - 1]?.data?.timeframe).toBe("4h");
  });

  it("refuses a n0→n199 edge with the exact 'timeframe mismatch' string and does not call onAddConnection", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={workloadNodes()}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("n199");
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

  it("records a n0→n1 edge and does not render any refusal notice", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={workloadNodes()}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("n1");
    expect(onAddConnection).toHaveBeenCalledTimes(1);
    expect(onAddConnection).toHaveBeenCalledWith({
      source: "n0",
      target: "n1",
      sourceHandle: null,
      targetHandle: null,
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses n0→n199 even after a successful n0→n1 connection in the same render", () => {
    const onAddConnection = vi.fn();
    render(
      <GraphCanvas
        nodes={workloadNodes()}
        edges={[]}
        onAddConnection={onAddConnection}
      />,
    );
    triggerConnect("n1");
    triggerConnect("n199");
    expect(onAddConnection).toHaveBeenCalledTimes(1);
    expect(onAddConnection).toHaveBeenCalledWith({
      source: "n0",
      target: "n1",
      sourceHandle: null,
      targetHandle: null,
    });
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
});
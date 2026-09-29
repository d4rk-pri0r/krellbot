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
import type { PaperClient } from "../features/paper/client";
import type { ResearchClient } from "../features/research/client";
import type { StrategyClient } from "../features/strategies/client";
import { WorkstationShell } from "./WorkstationShell";

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

function makePaperClient(): PaperClient {
  return {
    getStatus: vi.fn().mockResolvedValue({
      schema_version: "1",
      armed: false,
    }),
    pauseEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_paused",
      ok: true,
    }),
    resumeEntries: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "entries_resumed",
      ok: true,
    }),
    disarm: vi.fn().mockResolvedValue({
      schema_version: "1",
      code: "disarmed",
      ok: true,
    }),
  };
}

function makeResearchClient(): ResearchClient {
  return {
    submitRun: vi.fn().mockResolvedValue({ id: "job-1", state: "queued" }),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    getResult: vi.fn().mockResolvedValue(null),
  };
}

function makeStrategyClient(): StrategyClient {
  return {
    create: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "draft",
      pack: {},
      errors: [],
    }),
    edit: vi.fn().mockResolvedValue({
      revision_id: "rev-2",
      state: "draft",
      pack: {},
      errors: [],
    }),
    validate: vi.fn().mockResolvedValue({
      revision_id: "rev-1",
      state: "validated",
      pack: {},
      errors: [],
    }),
    arm: vi.fn().mockResolvedValue(undefined),
  };
}

function renderShell(): void {
  render(
    <WorkstationShell
      paperClient={makePaperClient()}
      researchClient={makeResearchClient()}
      strategyClient={makeStrategyClient()}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  lastReactFlowProps = null;
});

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

function countText(): string {
  return screen.getByTestId("studio-connection-count").textContent ?? "";
}

describe("WorkstationShell — studio view routing", () => {
  it("renders the Studio view as a button (not an anchor) inside the navigation", () => {
    renderShell();
    const nav = screen.getByRole("navigation", {
      name: /workstation navigation/i,
    });
    expect(nav.querySelector("a")).toBeNull();
    const studio = screen.getByRole("button", { name: "Studio" });
    expect(studio.tagName).toBe("BUTTON");
  });

  it("keeps Workstation, Strategies, and Research alongside Studio", () => {
    renderShell();
    const nav = screen.getByRole("navigation", {
      name: /workstation navigation/i,
    });
    const buttons = nav.querySelectorAll("button");
    const labels = Array.from(buttons).map((b) => b.textContent?.trim());
    expect(labels).toEqual(
      expect.arrayContaining([
        "Workstation",
        "Strategies",
        "Research",
        "Studio",
      ]),
    );
  });

  it("clicking Studio mounts the canvas and hides the Paper workstation heading", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.getByTestId("react-flow-stub")).toBeDefined();
    expect(screen.queryByText("Paper workstation")).toBeNull();
  });

  it("clicking Workstation after Studio shows the Paper workstation heading again", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.queryByText("Paper workstation")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Workstation" }));
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(screen.queryByTestId("react-flow-stub")).toBeNull();
  });

  it("does not mount the canvas while the Workstation view is active", () => {
    renderShell();
    expect(screen.getByText("Paper workstation")).toBeDefined();
    expect(screen.queryByTestId("react-flow-stub")).toBeNull();
  });
});

describe("WorkstationShell — studio canvas drives refusal through mounted GraphCanvas", () => {
  it("calls the captured onConnect only when the timeframe matches", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    const captured = getCaptured();
    expect(captured.onConnect).toBeDefined();
  });

  it("refuses n0→n1 with the exact 'timeframe mismatch' string and records no connection", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    triggerConnect("n1");
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
    expect(countText()).toMatch(/0/);
  });

  it("records exactly one connection for n0→n2 and shows no timeframe mismatch", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    triggerConnect("n2");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(countText()).toMatch(/1/);
    expect(getCaptured().edges).toHaveLength(1);
    expect(getCaptured().edges?.[0]?.source).toBe("n0");
    expect(getCaptured().edges?.[0]?.target).toBe("n2");
  });

  it("records two connections when two valid edges are added in sequence", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    triggerConnect("n2");
    triggerConnect("n0", "n2");
    expect(countText()).toMatch(/2/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not record a refused connection even after a successful one", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    triggerConnect("n2");
    expect(countText()).toMatch(/1/);
    triggerConnect("n1");
    expect(countText()).toMatch(/1/);
    expect(screen.getByRole("alert").textContent).toContain(
      "timeframe mismatch",
    );
  });

  it("workload=200 opens the studio with 200 nodes", () => {
    window.history.pushState({}, "", "/?workload=200");
    renderShell();
    expect(screen.getByTestId("studio-node-count").textContent).toBe("200");
    expect(getCaptured().nodes).toHaveLength(200);
    window.history.pushState({}, "", "/");
  });
});

describe("WorkstationShell — saved strategy studio", () => {
  it("renders the saved pack instead of the demo nodes", async () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: {
        value: JSON.stringify({
          id: "trend-follow",
          timeframe: "1h",
          indicators: { sma20: { fn: "sma" } },
          entry: ["close", ">", "sma20"],
          exit: ["close", "<", "sma20"],
        }),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await screen.findByTestId("editor-revision-id");
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    expect(screen.getByTestId("studio-pack-id").textContent).toBe("trend-follow");
    const ids = (getCaptured().nodes ?? []).map((node) => node.id);
    expect(ids).toContain("entry");
    expect(ids).toContain("exit");
    expect(ids).toContain("sma20");
    expect(ids).not.toContain("n0");
  });

  it("restores saved edges onto the canvas", async () => {
    const strategy = makeStrategyClient();
    strategy.loadEditor = vi.fn().mockResolvedValue({
      edges: [{ source: "entry", target: "sma20" }],
    });
    render(
      <WorkstationShell
        paperClient={makePaperClient()}
        researchClient={makeResearchClient()}
        strategyClient={strategy}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Strategies" }));
    fireEvent.change(screen.getByLabelText(/raw json/i), {
      target: {
        value: JSON.stringify({
          id: "trend-follow",
          timeframe: "1h",
          indicators: { sma20: { fn: "sma" } },
          entry: ["close", ">", "sma20"],
          exit: ["close", "<", "sma20"],
        }),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await screen.findByTestId("editor-revision-id");
    fireEvent.click(screen.getByRole("button", { name: "Studio" }));
    await vi.waitFor(() => {
      expect(getCaptured().edges?.[0]?.source).toBe("entry");
      expect(getCaptured().edges?.[0]?.target).toBe("sma20");
    });
  });
});

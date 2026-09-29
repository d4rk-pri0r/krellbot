import { useCallback, useEffect, useMemo, useState, type JSX } from "react";
import type { Connection } from "@xyflow/react";
import type { PaperClient } from "../features/paper/client";
import { StatusPanel } from "../features/paper/StatusPanel";
import { createHttpClient as createPaperHttpClient } from "../features/paper/client";
import { ResearchView } from "../features/research/ResearchView";
import { createHttpClient as createResearchHttpClient } from "../features/research/client";
import type { ResearchClient } from "../features/research/client";
import { Editor } from "../features/strategies/Editor";
import { createHttpClient } from "../features/strategies/client";
import type { StrategyClient } from "../features/strategies/client";
import {
  GraphCanvas,
  type GraphCanvasNode,
} from "../features/studio/GraphCanvas";
import { redeemBootstrap } from "../session";
import { CommandPalette } from "./CommandPalette";
import { Inspector } from "./Inspector";
import { JobsDrawer } from "./JobsDrawer";
import { Navigation, type View } from "./Navigation";
import { StatusStrip } from "./StatusStrip";

const BOOTSTRAP_META = "krellbot-bootstrap";

function workloadNodes(search: string): ReadonlyArray<GraphCanvasNode> | null {
  const params = new URLSearchParams(search);
  if (params.get("workload") !== "200") {
    return null;
  }
  return Array.from({ length: 200 }, (_, index) => ({
    id: `w${index}`,
    type: "default",
    position: { x: (index % 20) * 40, y: Math.floor(index / 20) * 40 },
    data: { timeframe: index % 2 === 0 ? "1h" : "4h" },
  }));
}

const STUDIO_NODES: ReadonlyArray<GraphCanvasNode> = [
  {
    id: "n0",
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe: "1h" },
  },
  {
    id: "n1",
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe: "4h" },
  },
  {
    id: "n2",
    type: "default",
    position: { x: 0, y: 0 },
    data: { timeframe: "1h" },
  },
];

function consumeBootstrapToken(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const meta = document.querySelector(
    `meta[name="${BOOTSTRAP_META}"]`,
  );
  if (meta === null) {
    return null;
  }
  const token = meta.getAttribute("content") ?? "";
  meta.remove();
  return token;
}

export type WorkstationShellProps = {
  paperClient?: PaperClient;
  researchClient?: ResearchClient;
  strategyClient?: StrategyClient;
};

export function WorkstationShell({
  paperClient,
  researchClient,
  strategyClient,
}: WorkstationShellProps = {}): JSX.Element {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const workload = workloadNodes(
    typeof window === "undefined" ? "" : window.location.search,
  );
  const [active, setActive] = useState<View>(workload ? "studio" : "workstation");
  const [connections, setConnections] = useState<ReadonlyArray<Connection>>([]);
  const handleAddConnection = useCallback((connection: Connection): void => {
    setConnections((prev) => [...prev, connection]);
  }, []);
  const client = useMemo(
    () => strategyClient ?? createHttpClient(),
    [strategyClient],
  );
  const research = useMemo(
    () => researchClient ?? createResearchHttpClient(),
    [researchClient],
  );
  const paper = useMemo(
    () => paperClient ?? createPaperHttpClient(),
    [paperClient],
  );

  useEffect(() => {
    const token = consumeBootstrapToken();
    if (token) {
      void redeemBootstrap(token);
    }
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.key.toLowerCase() === "k" &&
        (event.ctrlKey || event.metaKey)
      ) {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="kbot-shell">
      <div className="kbot-shell__topbar">
        <StatusStrip />
        <JobsDrawer />
      </div>
      <Navigation active={active} onChange={setActive} />
      <main className="kbot-shell__main">
        {active === "workstation" ? (
          <>
            <h1 className="kbot-shell__heading">Paper workstation</h1>
            <StatusPanel client={paper} />
            <Inspector />
          </>
        ) : null}
        {active === "strategies" ? <Editor client={client} /> : null}
        {active === "research" ? (
          <ResearchView client={research} />
        ) : null}
        {active === "studio" ? (
          <>
            <GraphCanvas
              nodes={(workload ?? STUDIO_NODES) as GraphCanvasNode[]}
              edges={[]}
              onAddConnection={handleAddConnection}
            />
            <p data-testid="studio-node-count">{(workload ?? STUDIO_NODES).length}</p>
            <p data-testid="studio-connection-count">
              Connections: {connections.length}
            </p>
          </>
        ) : null}
      </main>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
      />
    </div>
  );
}

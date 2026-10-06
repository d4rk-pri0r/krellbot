import "@xyflow/react/dist/style.css";
import { useEffect, useRef, useState, type JSX } from "react";
import {
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeTypes,
  type OnConnect,
} from "@xyflow/react";
import { refuseIncompatibleEdge } from "./edges";
import type { EdgeRefusal } from "./edges";
import { EdgeRefusalNotice } from "./EdgeRefusalNotice";

export type GraphCanvasNodeData = {
  timeframe?: string;
};

export type GraphCanvasNode = Node<GraphCanvasNodeData>;

export type GraphCanvasProps = {
  nodes: GraphCanvasNode[];
  edges?: Edge[];
  onAddConnection: (connection: Connection) => void;
  onSelectNode?: (nodeId: string) => void;
  nodeTypes?: NodeTypes;
  fitView?: boolean;
};

function connectionKey(
  source: string | null | undefined,
  target: string | null | undefined,
  sourceHandle: string | null | undefined,
  targetHandle: string | null | undefined,
): string {
  return `${source ?? ""}\u0000${target ?? ""}\u0000${sourceHandle ?? ""}\u0000${
    targetHandle ?? ""
  }`;
}

function edgeKey(edge: Edge): string {
  return connectionKey(
    edge.source,
    edge.target,
    edge.sourceHandle,
    edge.targetHandle,
  );
}

export function GraphCanvas(props: GraphCanvasProps): JSX.Element {
  const {
    nodes,
    edges = [],
    onAddConnection,
    onSelectNode,
    nodeTypes,
    fitView = false,
  } = props;
  const [refusal, setRefusal] = useState<EdgeRefusal | null>(null);

  // Connections forwarded to the parent while the rerender that adds the
  // matching edge is still pending. A key is released only once the parent
  // actually renders that edge, never because the ``edges`` array identity
  // changed (a recreated equivalent array or a self-render from a refusal
  // must not re-arm the guard).
  const pendingConnections = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (pendingConnections.current.size === 0) {
      return;
    }
    const confirmed = new Set(edges.map(edgeKey));
    pendingConnections.current = new Set(
      [...pendingConnections.current].filter((key) => !confirmed.has(key)),
    );
  }, [edges]);

  const handleConnect: OnConnect = (connection) => {
    const source = nodes.find((n) => n.id === connection.source);
    const target = nodes.find((n) => n.id === connection.target);
    if (!source || !target) {
      return;
    }
    const verdict = refuseIncompatibleEdge(
      { timeframe: source.data?.timeframe },
      { timeframe: target.data?.timeframe },
    );
    if (verdict === null) {
      const key = connectionKey(
        connection.source,
        connection.target,
        connection.sourceHandle,
        connection.targetHandle,
      );
      if (edges.some((edge) => edgeKey(edge) === key)) {
        return;
      }
      if (pendingConnections.current.has(key)) {
        return;
      }
      pendingConnections.current.add(key);
      setRefusal(null);
      onAddConnection(connection);
      return;
    }
    setRefusal(verdict);
  };

  const handleNodeClick: NodeMouseHandler = (_event, node) => {
    if (onSelectNode) {
      onSelectNode(String(node.id));
    }
  };

  return (
    <div data-testid="graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onConnect={handleConnect}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        nodesConnectable
        edgesFocusable={false}
        fitView={fitView}
        proOptions={{ hideAttribution: true }}
      />
      {refusal !== null ? (
        <EdgeRefusalNotice
          reason={refusal}
          onDismiss={() => setRefusal(null)}
        />
      ) : null}
    </div>
  );
}

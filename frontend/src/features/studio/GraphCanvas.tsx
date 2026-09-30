import "@xyflow/react/dist/style.css";
import { useState, type JSX } from "react";
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

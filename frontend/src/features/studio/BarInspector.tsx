import type { JSX } from "react";
import { observeNode, type ObserveNodeInput } from "./observe";

export type BarInspectorProps = {
  node: ObserveNodeInput;
  decisionBar: number;
};

export function BarInspector(props: BarInspectorProps): JSX.Element {
  const { node, decisionBar } = props;
  const result = observeNode(node, decisionBar);
  const status: string = result.available ? "closed" : result.reason;
  return (
    <div>
      <label htmlFor="bar-inspector-selected-bar">Selected bar</label>
      <input
        id="bar-inspector-selected-bar"
        type="number"
        value={decisionBar}
        readOnly
      />
      <p>{status}</p>
    </div>
  );
}
import "./BarInspector.signal.css";
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
    <div className="kbot-feature__bar-inspector-root">
      <label htmlFor="bar-inspector-selected-bar">Selected bar</label>
      <input
        id="bar-inspector-selected-bar"
        type="number"
        value={decisionBar}
        readOnly
      />
      <p
        className={
          result.available
            ? "kbot-feature__bar-inspector-root__status kbot-feature__bar-inspector-root__status--closed"
            : "kbot-feature__bar-inspector-root__status kbot-feature__bar-inspector-root__status--unavailable"
        }
      >
        {status}
      </p>
    </div>
  );
}
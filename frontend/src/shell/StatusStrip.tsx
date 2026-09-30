import type { JSX } from "react";
import "../styles/shell.css";

export function StatusStrip(): JSX.Element {
  return (
    <div className="kbot-status" role="region" aria-label="Status">
      <span className="kbot-status__mode" aria-label="Mode Paper">
        Paper
      </span>
      <span className="kbot-status__divider" aria-hidden="true">·</span>
      <span className="kbot-status__orders" data-testid="live-orders-status">
        Live orders unavailable
      </span>
    </div>
  );
}

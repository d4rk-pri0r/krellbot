import type { JSX } from "react";

export function App(): JSX.Element {
  return (
    <main>
      <h1>Paper workstation</h1>
      <p data-testid="live-orders-status">Live orders unavailable</p>
    </main>
  );
}

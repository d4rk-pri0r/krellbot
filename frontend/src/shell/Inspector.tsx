import type { JSX } from "react";

export function Inspector(): JSX.Element {
  return (
    <section
      className="kbot-inspector"
      role="region"
      aria-label="Inspector"
    >
      <header className="kbot-inspector__head">
        <h2 className="kbot-inspector__title">Inspector</h2>
      </header>
      <div className="kbot-inspector__body">
        <p className="kbot-inspector__empty">Nothing selected</p>
      </div>
    </section>
  );
}

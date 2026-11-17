import { useEffect, useState, type JSX } from "react";
import {
  createDemoFixtureHttpClient,
  type DemoFixtureClient,
  type DemoFixtureStatus,
} from "./demoFixtureClient";
import "./DemoFixturePanel.signal.css";

export type DemoFixturePanelProps = {
  client?: DemoFixtureClient;
  enabled?: boolean;
};

/**
 * Opt-in local demo/fixture seed controls (M18.5 / docs/ui-density.md).
 * When enabled, shows a Fixture demo badge and labeled rehearsal rows —
 * never live P&L or soak proof.
 */
export function DemoFixturePanel({
  client,
  enabled = true,
}: DemoFixturePanelProps): JSX.Element {
  const [status, setStatus] = useState<DemoFixtureStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const api = client ?? createDemoFixtureHttpClient();

  useEffect(() => {
    if (!enabled) {
      setStatus(null);
      return;
    }
    let cancelled = false;
    setError(null);
    api
      .getStatus()
      .then((next) => {
        if (!cancelled) setStatus(next);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, enabled]);

  async function runSeed(): Promise<void> {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.seed(true);
      setStatus(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function runClear(): Promise<void> {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.clear();
      setStatus(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!enabled) {
    return (
      <p className="kbot-demo-fixture__empty" data-testid="demo-fixture-waiting">
        Waiting for the local session…
      </p>
    );
  }

  const seeded = status?.enabled === true;

  return (
    <section
      className="kbot-demo-fixture"
      data-testid="demo-fixture-panel"
      aria-label="Demo fixture seed"
    >
      {seeded ? (
        <p className="kbot-demo-fixture__badge" data-testid="demo-fixture-badge">
          {status?.badge ?? "Fixture demo"}
        </p>
      ) : null}
      <p className="kbot-demo-fixture__copy" data-testid="demo-fixture-honesty">
        {status?.honesty_note ??
          "Opt-in local preview seed only. Labeled fixture/demo/rehearsal — never live P&L, market performance, or soak PASS."}
      </p>
      <p className="kbot-demo-fixture__message" data-testid="demo-fixture-message">
        {status?.message ?? "Loading demo fixture status…"}
      </p>
      {seeded && status?.label ? (
        <p className="kbot-demo-fixture__label" data-testid="demo-fixture-label">
          {status.label}
        </p>
      ) : null}
      {seeded ? (
        <ul className="kbot-demo-fixture__list" data-testid="demo-fixture-list">
          {status?.deployments.map((row) => (
            <li
              key={row.id}
              className="kbot-demo-fixture__row"
              data-testid={`demo-fixture-row-${row.id}`}
            >
              <span className="kbot-demo-fixture__row-label">{row.label}</span>
              <span className="kbot-demo-fixture__row-meta">
                {row.venue} {row.pair} · fixture
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="kbot-demo-fixture__actions">
        <button
          type="button"
          className="kbot-demo-fixture__action"
          data-testid="demo-fixture-seed"
          disabled={busy || seeded}
          onClick={() => {
            void runSeed();
          }}
        >
          {busy && !seeded ? "Seeding…" : "Enable fixture demo"}
        </button>
        <button
          type="button"
          className="kbot-demo-fixture__action"
          data-testid="demo-fixture-clear"
          disabled={busy || !seeded}
          onClick={() => {
            void runClear();
          }}
        >
          {busy && seeded ? "Clearing…" : "Clear fixture demo"}
        </button>
      </div>
      {error !== null ? (
        <p className="kbot-demo-fixture__error" role="alert" data-testid="demo-fixture-error">
          {error}
        </p>
      ) : null}
    </section>
  );
}

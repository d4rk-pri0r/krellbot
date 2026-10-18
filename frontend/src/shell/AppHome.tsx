import { useRef, useState, type JSX } from "react";
import { BrandMark } from "../components/brand/BrandMark";
import type { View } from "./Navigation";
import "./AppHome.signal.css";

/**
 * Application Home — Signal composition (KRELL-SIGNAL-20261010).
 *
 * A welcoming application overview that routes a new user to the areas
 * this build actually supports. It is informational navigation only:
 * it renders before authenticated data loads, claims no connection,
 * account, license or market state, and never gates on engine
 * telemetry. Operational views keep their own bootstrap gates.
 */

type HomeCard = {
  view: View;
  action: string;
  detail: string;
  testid: string;
};

const HOME_CARDS: ReadonlyArray<HomeCard> = [
  {
    view: "strategies",
    action: "Create or open a strategy",
    detail:
      "Write or paste a strategy pack, save a draft, and reopen it from your library.",
    testid: "app-home-card-strategies",
  },
  {
    view: "research",
    action: "Explore research",
    detail:
      "Run a backtest over your own dataset and read the recorded evidence.",
    testid: "app-home-card-research",
  },
  {
    view: "studio",
    action: "Open Studio",
    detail:
      "See a saved strategy as a graph of indicators, entries and exits.",
    testid: "app-home-card-studio",
  },
  {
    view: "workstation",
    action: "Paper workstation",
    detail:
      "Check the paper engine status, last runs and stop controls.",
    testid: "app-home-card-workstation",
  },
  {
    view: "operations",
    action: "Operations",
    detail:
      "Review alerts and the kill switch for the local workstation.",
    testid: "app-home-card-operations",
  },
];

type AppHomeProps = {
  onNavigate: (view: View) => void;
  /** True while the local session bootstrap has not settled yet. */
  sessionPending?: boolean;
  /**
   * True when the one-time session bootstrap was rejected. Shown
   * honestly instead of presenting startup as complete.
   */
  sessionFailed?: boolean;
  /** Offered only on failure; re-reads the CSRF for the existing session. */
  onRecoverSession?: () => Promise<{ ok: boolean; error?: string }>;
};

export function AppHome({
  onNavigate,
  sessionPending = false,
  sessionFailed = false,
  onRecoverSession,
}: AppHomeProps): JSX.Element {
  const [recoverError, setRecoverError] = useState<string | null>(null);
  const recoveryAttempt = useRef(0);

  async function recoverSession(): Promise<void> {
    const attempt = ++recoveryAttempt.current;
    setRecoverError(null);
    try {
      const result = await onRecoverSession?.();
      if (attempt === recoveryAttempt.current) {
        setRecoverError(result?.ok ? null : result?.error || "recovery refused");
      }
    } catch (error) {
      if (attempt === recoveryAttempt.current) {
        setRecoverError(error instanceof Error ? error.message : String(error));
      }
    }
  }

  return (
    <section
      className="app-home"
      data-testid="app-home"
      aria-labelledby="app-home-title"
    >
      <div className="app-home__welcome">
        <BrandMark />
        <div>
          <h1 className="app-home__title" id="app-home-title">
            Your crypto workstation, local by design
          </h1>
          <p className="app-home__purpose">
            Build, inspect and paper-test strategy packs on this machine.
            Every view below is real navigation in this application.
          </p>
        </div>
        <p
          className="app-home__availability"
          data-testid="app-home-availability"
        >
          <span className="app-home__availability-mode">Local preview</span>
          <span aria-hidden="true"> · </span>
          <span className="app-home__availability-live">
            Live trading unavailable
          </span>
        </p>
        {sessionPending && !sessionFailed ? (
          <p
            className="app-home__session"
            data-testid="app-home-session"
            role="status"
          >
            Starting the local session… areas that need it will load their own
            data.
          </p>
        ) : null}
        {sessionFailed ? (
          <div
            className="app-home__session app-home__session--failed"
            data-testid="app-home-session-failure"
            role="alert"
          >
            <p className="app-home__note-copy">
              The local session could not start. Areas that need it will show
              their own errors, and nothing can be saved or changed until the
              session recovers. Navigation still works offline.
            </p>
            {onRecoverSession ? (
              <button
                type="button"
                className="app-home__recover"
                data-testid="app-home-recover-session"
                onClick={() => { void recoverSession(); }}
              >
                Recover the local session
              </button>
            ) : null}
            {recoverError !== null ? (
              <p data-testid="apphome-recover-error" role="alert">
                Recovery failed: {recoverError}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      <ul className="app-home__cards">
        {HOME_CARDS.map((card) => (
          <li key={card.view} className="app-home__card-item">
            <button
              type="button"
              className="app-home__card"
              data-testid={card.testid}
              onClick={() => {
                onNavigate(card.view);
              }}
            >
              <span className="app-home__card-action">{card.action}</span>
              <span className="app-home__card-detail">{card.detail}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className="app-home__notes">
        <section
          className="app-home__note"
          aria-labelledby="app-home-works-title"
        >
          <h2 className="app-home__note-title" id="app-home-works-title">
            What works here
          </h2>
          <ul className="app-home__note-list">
            <li>Creating, editing and validating your own strategy packs.</li>
            <li>Reopening saved drafts and copying them as new drafts.</li>
            <li>Research runs over a dataset you provide.</li>
            <li>Graph editing for saved packs in Studio.</li>
            <li>Paper status, last runs and stop controls.</li>
          </ul>
        </section>
        <section
          className="app-home__note"
          aria-labelledby="app-home-unfinished-title"
        >
          <h2 className="app-home__note-title" id="app-home-unfinished-title">
            Not connected yet
          </h2>
          <p className="app-home__note-copy">
            No exchange is connected in this build and live trading is
            unavailable. Nothing here places real orders, requests credentials,
            or reports account state. Engine work is still in progress: when an
            area cannot reach the local service it shows its own unavailable or
            error state instead of example results.
          </p>
          <p className="app-home__note-copy">
            Navigation works without the engine: you can move between these
            areas at any time.
          </p>
        </section>
      </div>
    </section>
  );
}

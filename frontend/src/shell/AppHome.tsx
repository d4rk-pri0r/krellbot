import { useRef, useState, type JSX } from "react";
import { BrandMark } from "../components/brand/BrandMark";
import { KeysOnboardingPanel } from "../features/keys/KeysOnboardingPanel";
import {
  createKeysHttpClient,
  type KeysClient,
} from "../features/keys/client";
import type { View } from "./Navigation";
import "./AppHome.signal.css";

/**
 * Application Home — Signal workspace composition (KRELL-SIGNAL-20261010).
 *
 * A welcoming workspace overview that routes a new user to the areas
 * this build actually supports. It is informational navigation only:
 * it renders before authenticated data loads, claims no connection,
 * account, license or market state, and never gates on engine
 * telemetry. Operational views keep their own bootstrap gates.
 *
 * Layout mirrors the approved Signal workspace reference (main column +
 * aside) without inventing equity, returns, health, or sample bots.
 */

type HomeCard = {
  view: View;
  action: string;
  detail: string;
  testid: string;
  meta: string;
};

const HOME_CARDS: ReadonlyArray<HomeCard> = [
  {
    view: "workstation",
    action: "Paper workstation",
    detail:
      "Check the paper engine status, last runs and stop controls.",
    testid: "app-home-card-workstation",
    meta: "Paper · local",
  },
  {
    view: "strategies",
    action: "Create or open a strategy",
    detail:
      "Write or paste a strategy pack, save a draft, and reopen it from your library.",
    testid: "app-home-card-strategies",
    meta: "Author · library",
  },
  {
    view: "studio",
    action: "Open Studio",
    detail:
      "See a saved strategy as a graph of indicators, entries and exits.",
    testid: "app-home-card-studio",
    meta: "Graph · edit",
  },
  {
    view: "research",
    action: "Explore research",
    detail:
      "Run a backtest over your own dataset and read the recorded evidence.",
    testid: "app-home-card-research",
    meta: "Backtest · evidence",
  },
  {
    view: "operations",
    action: "Operations",
    detail:
      "Review alerts and the kill switch for the local workstation.",
    testid: "app-home-card-operations",
    meta: "Alerts · controls",
  },
];

const ACTIVITY_ROWS: ReadonlyArray<{ title: string; detail: string }> = [
  {
    title: "Author a strategy pack",
    detail: "Create or paste rules, validate them, and save a draft locally.",
  },
  {
    title: "Inspect decisions in Studio",
    detail: "Open a saved pack as a graph before you paper-arm it.",
  },
  {
    title: "Paper-arm and observe",
    detail: "Run on this machine with simulated funds and review last runs.",
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
  /** Injectable keys client; defaults to the loopback HTTP client. */
  keysClient?: KeysClient;
};

export function AppHome({
  onNavigate,
  sessionPending = false,
  sessionFailed = false,
  onRecoverSession,
  keysClient,
}: AppHomeProps): JSX.Element {
  const [recoverError, setRecoverError] = useState<string | null>(null);
  const recoveryAttempt = useRef(0);
  const fallbackKeysRef = useRef<KeysClient | null>(null);
  if (fallbackKeysRef.current === null && keysClient === undefined) {
    fallbackKeysRef.current = createKeysHttpClient();
  }
  const keys = keysClient ?? fallbackKeysRef.current!;

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

  const sessionLabel = sessionFailed
    ? "Local session failed"
    : sessionPending
      ? "Starting the local session"
      : "Local session ready";

  return (
    <section
      className="app-home"
      data-testid="app-home"
      aria-labelledby="app-home-title"
    >
      <header className="app-home__hero">
        <div className="app-home__hero-copy">
          <h1 className="app-home__title" id="app-home-title">
            Your workspace
          </h1>
          <p className="app-home__purpose">
            A clear view of your strategies, paper bots, and next decisions.
          </p>
        </div>
        <button
          type="button"
          className="app-home__cta"
          data-testid="app-home-cta-paper"
          onClick={() => {
            onNavigate("workstation");
          }}
        >
          <span aria-hidden="true">+</span> New paper bot
        </button>
      </header>

      <div className="app-home__layout">
        <div className="app-home__main">
          <section
            className="app-home__summary"
            aria-labelledby="app-home-summary-title"
          >
            <div className="app-home__summary-head">
              <BrandMark />
              <div>
                <h2
                  className="app-home__summary-title"
                  id="app-home-summary-title"
                >
                  Local preview
                </h2>
                <p className="app-home__summary-lead">
                  Build, inspect and paper-test strategy packs on this machine.
                  Every area below is real navigation in this application.
                </p>
              </div>
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
                Starting the local session… areas that need it will load their
                own data.
              </p>
            ) : null}
            {sessionFailed ? (
              <div
                className="app-home__session app-home__session--failed"
                data-testid="app-home-session-failure"
                role="alert"
              >
                <p className="app-home__note-copy">
                  The local session could not start. Areas that need it will
                  show their own errors, and nothing can be saved or changed
                  until the session recovers. Navigation still works offline.
                </p>
                {onRecoverSession ? (
                  <button
                    type="button"
                    className="app-home__recover"
                    data-testid="app-home-recover-session"
                    onClick={() => {
                      void recoverSession();
                    }}
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
          </section>

          <section
            className="app-home__bots"
            aria-labelledby="app-home-bots-title"
          >
            <div className="app-home__section-head">
              <h2 className="app-home__section-title" id="app-home-bots-title">
                Where to work
              </h2>
              <p className="app-home__section-meta">
                {HOME_CARDS.length} areas
              </p>
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
                    {/*
                      Single stacked body: shell buttons are inline-flex,
                      which otherwise lays mark/action/detail/footer in a
                      row and squeezes descriptions into ~51–77px columns.
                    */}
                    <span className="app-home__card-body">
                      <span className="app-home__card-mark" aria-hidden="true" />
                      <span className="app-home__card-action">{card.action}</span>
                      <span className="app-home__card-detail">{card.detail}</span>
                      <span className="app-home__card-footer">
                        <span className="app-home__card-meta">{card.meta}</span>
                        <span className="app-home__card-link">Open →</span>
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section
            className="app-home__activity"
            aria-labelledby="app-home-works-title"
          >
            <h2 className="app-home__section-title" id="app-home-works-title">
              What works here
            </h2>
            <ul className="app-home__activity-list">
              {ACTIVITY_ROWS.map((row) => (
                <li key={row.title} className="app-home__activity-row">
                  <div className="app-home__activity-copy">
                    <p className="app-home__activity-title">{row.title}</p>
                    <p className="app-home__activity-detail">{row.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
            <ul className="app-home__note-list app-home__note-list--compact">
              <li>Creating, editing and validating your own strategy packs.</li>
              <li>Reopening saved drafts and copying them as new drafts.</li>
              <li>Research runs over a dataset you provide.</li>
              <li>Graph editing for saved packs in Studio.</li>
              <li>Paper status, last runs and stop controls.</li>
            </ul>
          </section>
        </div>

        <aside className="app-home__aside" aria-label="Workspace context">
          <section
            className="app-home__rail"
            aria-labelledby="app-home-session-rail-title"
          >
            <h2
              className="app-home__rail-title"
              id="app-home-session-rail-title"
            >
              Local session
            </h2>
            <p className="app-home__rail-lead" data-testid="app-home-rail-session">
              <span
                className={
                  sessionFailed
                    ? "app-home__rail-dot app-home__rail-dot--caution"
                    : "app-home__rail-dot"
                }
                aria-hidden="true"
              />
              {sessionLabel}
            </p>
            <p className="app-home__rail-copy">
              Live trading stays unavailable in this paper-only release. Link a
              trade-only Kraken key below when you are ready.
            </p>
          </section>

          <section
            className="app-home__rail app-home__rail--emphasis"
            aria-labelledby="keys-onboarding-title"
            data-testid="app-home-keys-rail"
          >
            <KeysOnboardingPanel
              client={keys}
              enabled={!sessionPending && !sessionFailed}
            />
          </section>

          <section
            className="app-home__rail"
            aria-labelledby="app-home-packs-rail-title"
          >
            <h2 className="app-home__rail-title" id="app-home-packs-rail-title">
              Strategy packs
            </h2>
            <p className="app-home__rail-copy">
              Browse installed and available packs from the Strategies view.
            </p>
            <button
              type="button"
              className="app-home__rail-link"
              data-testid="app-home-rail-packs"
              onClick={() => {
                onNavigate("strategies");
              }}
            >
              Explore your packs →
            </button>
          </section>

          <section className="app-home__rail" aria-labelledby="app-home-ops-rail-title">
            <h2 className="app-home__rail-title" id="app-home-ops-rail-title">
              Operations
            </h2>
            <p className="app-home__note-copy">
              Nothing here places real orders. When an area cannot reach the
              local service it shows its own unavailable or error state instead
              of example results. Navigation still works offline.
            </p>
            <button
              type="button"
              className="app-home__rail-link"
              data-testid="app-home-rail-ops"
              onClick={() => {
                onNavigate("operations");
              }}
            >
              See operations →
            </button>
          </section>
        </aside>
      </div>
    </section>
  );
}

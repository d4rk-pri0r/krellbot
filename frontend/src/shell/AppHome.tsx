import { useRef, useState, type JSX } from "react";
import type { VersionClient } from "../api/version";
import { BrandMark } from "../components/brand/BrandMark";
import { DisclosureSection } from "../components/disclosure/DisclosureSection";
import { KeysOnboardingPanel } from "../features/keys/KeysOnboardingPanel";
import {
  createKeysHttpClient,
  type KeysClient,
} from "../features/keys/client";
import type { ReconnectIssue } from "../session";
import { AboutPanel } from "./AboutPanel";
import type { View } from "./Navigation";
import { ReconnectQr } from "./ReconnectQr";
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
    title: "1. Author a strategy",
    detail: "Create or paste rules, validate them, and save a draft locally.",
  },
  {
    title: "2. Inspect in Studio",
    detail: "Open a saved pack as a graph before you paper-arm it.",
  },
  {
    title: "3. Paper-arm and watch",
    detail: "Use simulated funds on this machine; pause entries or disarm when needed.",
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
  /** Injectable version/about client; defaults to the loopback HTTP client. */
  versionClient?: VersionClient;
  /**
   * Primary session: mint a short-lived reconnect token/QR for a second
   * browser. Absent when the local session is not ready.
   */
  onIssueReconnect?: () => Promise<ReconnectIssue>;
  /**
   * Second browser / failed session: redeem a pasted reconnect token.
   */
  onRedeemReconnect?: (token: string) => Promise<{ ok: boolean; error?: string }>;
};

export function AppHome({
  onNavigate,
  sessionPending = false,
  sessionFailed = false,
  onRecoverSession,
  keysClient,
  versionClient,
  onIssueReconnect,
  onRedeemReconnect,
}: AppHomeProps): JSX.Element {
  const [recoverError, setRecoverError] = useState<string | null>(null);
  const recoveryAttempt = useRef(0);
  const fallbackKeysRef = useRef<KeysClient | null>(null);
  if (fallbackKeysRef.current === null && keysClient === undefined) {
    fallbackKeysRef.current = createKeysHttpClient();
  }
  const keys = keysClient ?? fallbackKeysRef.current!;
  const [reconnectOffer, setReconnectOffer] = useState<ReconnectIssue | null>(null);
  const [reconnectBusy, setReconnectBusy] = useState(false);
  const [reconnectError, setReconnectError] = useState<string | null>(null);
  const [pasteToken, setPasteToken] = useState("");
  const [pasteError, setPasteError] = useState<string | null>(null);
  const [pasteBusy, setPasteBusy] = useState(false);

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

  async function issueReconnect(): Promise<void> {
    if (!onIssueReconnect || reconnectBusy) return;
    setReconnectBusy(true);
    setReconnectError(null);
    try {
      const offer = await onIssueReconnect();
      setReconnectOffer(offer);
    } catch (error) {
      setReconnectOffer(null);
      setReconnectError(error instanceof Error ? error.message : String(error));
    } finally {
      setReconnectBusy(false);
    }
  }

  async function redeemPasted(): Promise<void> {
    if (!onRedeemReconnect || pasteBusy) return;
    const token = pasteToken.trim();
    if (!token) {
      setPasteError("Enter the reconnect token from the other browser");
      return;
    }
    setPasteBusy(true);
    setPasteError(null);
    try {
      const result = await onRedeemReconnect(token);
      if (!result.ok) {
        setPasteError(result.error || "reconnect refused");
      }
    } catch (error) {
      setPasteError(error instanceof Error ? error.message : String(error));
    } finally {
      setPasteBusy(false);
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
            Start with paper on this machine — live trading stays unavailable
            in this release.
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
          Open paper workstation
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
                {onRedeemReconnect ? (
                  <div
                    className="app-home__reconnect-paste"
                    data-testid="app-home-reconnect-paste"
                  >
                    <p className="app-home__note-copy">
                      Or paste a short-lived reconnect token from a browser that
                      already has a local session — no process restart needed.
                    </p>
                    <label className="app-home__reconnect-label" htmlFor="app-home-reconnect-token">
                      Reconnect token
                    </label>
                    <input
                      id="app-home-reconnect-token"
                      className="app-home__reconnect-input"
                      data-testid="app-home-reconnect-token-input"
                      type="text"
                      autoComplete="off"
                      spellCheck={false}
                      value={pasteToken}
                      disabled={pasteBusy}
                      onChange={(event) => {
                        setPasteToken(event.target.value);
                      }}
                    />
                    <button
                      type="button"
                      className="app-home__recover"
                      data-testid="app-home-reconnect-redeem"
                      disabled={pasteBusy}
                      onClick={() => {
                        void redeemPasted();
                      }}
                    >
                      Join with reconnect token
                    </button>
                    {pasteError !== null ? (
                      <p data-testid="app-home-reconnect-paste-error" role="alert">
                        {pasteError}
                      </p>
                    ) : null}
                  </div>
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
            role="region"
          >
            <h2 className="app-home__section-title" id="app-home-works-title">
              What works here
            </h2>
            <p className="app-home__section-lede">
              Author and validate strategy packs, run research on your own
              dataset, inspect graphs in Studio, then paper-arm and observe.
              Nothing here places real orders.
            </p>
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
              Live trading stays unavailable in this paper-only release.
            </p>
            <div className="app-home__rail-links">
              <button
                type="button"
                className="app-home__rail-link"
                data-testid="app-home-rail-packs"
                onClick={() => {
                  onNavigate("packs");
                }}
              >
                Browse packs →
              </button>
              <button
                type="button"
                className="app-home__rail-link"
                data-testid="app-home-rail-ops"
                onClick={() => {
                  onNavigate("operations");
                }}
              >
                Open operations →
              </button>
            </div>
          </section>

          <DisclosureSection
            title="Exchange keys"
            summary="Optional trade-only key material for later live work. Storing a key does not enable live trading."
            badge="Advanced"
            badgeTone="advanced"
            defaultOpen={false}
            storageKey="krellbot.disclosure.home.keys"
            bare
            data-testid="app-home-keys-rail"
          >
            <div className="app-home__rail app-home__rail--emphasis app-home__rail--nested">
              <KeysOnboardingPanel
                client={keys}
                venue="kraken"
                enabled={!sessionPending && !sessionFailed}
              />
              <KeysOnboardingPanel
                client={keys}
                venue="coinbase"
                enabled={!sessionPending && !sessionFailed}
              />
            </div>
          </DisclosureSection>

          {!sessionPending && !sessionFailed && onIssueReconnect ? (
            <DisclosureSection
              title="Reconnect another browser"
              summary="Short-lived token or QR for a second browser on this machine."
              badge="Advanced"
              badgeTone="advanced"
              defaultOpen={false}
              storageKey="krellbot.disclosure.home.reconnect"
              bare
              data-testid="app-home-reconnect"
            >
              <div className="app-home__rail app-home__rail--nested">
                <p className="app-home__rail-copy">
                  Invite another browser on this machine. The one-time bootstrap
                  stays spent.
                </p>
                <button
                  type="button"
                  className="app-home__rail-link"
                  data-testid="app-home-reconnect-issue"
                  disabled={reconnectBusy}
                  onClick={() => {
                    void issueReconnect();
                  }}
                >
                  {reconnectBusy
                    ? "Creating reconnect code…"
                    : "Show reconnect code →"}
                </button>
                {reconnectError !== null ? (
                  <p
                    className="app-home__rail-copy"
                    data-testid="app-home-reconnect-error"
                    role="alert"
                  >
                    {reconnectError}
                  </p>
                ) : null}
                {reconnectOffer !== null ? (
                  <div
                    className="app-home__reconnect-offer"
                    data-testid="app-home-reconnect-offer"
                  >
                    <ReconnectQr
                      payload={reconnectOffer.token}
                      label="Reconnect token QR code"
                    />
                    <p className="app-home__reconnect-token-label">Token</p>
                    <code
                      className="app-home__reconnect-token"
                      data-testid="app-home-reconnect-token"
                    >
                      {reconnectOffer.token}
                    </code>
                    <p className="app-home__rail-copy">
                      Open in the other browser, or paste the token there:
                    </p>
                    <code
                      className="app-home__reconnect-url"
                      data-testid="app-home-reconnect-url"
                    >
                      {reconnectOffer.qrPayload}
                    </code>
                    <p className="app-home__rail-copy">
                      Expires in {reconnectOffer.expiresIn}s.
                    </p>
                  </div>
                ) : null}
              </div>
            </DisclosureSection>
          ) : null}

          <DisclosureSection
            title="About this build"
            summary="Version, channel, and signing honesty for this local preview."
            badge="Advanced"
            badgeTone="advanced"
            defaultOpen={false}
            storageKey="krellbot.disclosure.home.about"
            bare
            data-testid="app-home-about-rail"
          >
            <div className="app-home__rail app-home__rail--nested">
              <AboutPanel client={versionClient} enabled={!sessionPending} />
            </div>
          </DisclosureSection>
        </aside>
      </div>
    </section>
  );
}

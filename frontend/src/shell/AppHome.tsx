import { useEffect, useRef, useState, type JSX } from "react";
import type { VersionClient } from "../api/version";
import { BrandMark } from "../components/brand/BrandMark";
import { DisclosureSection } from "../components/disclosure/DisclosureSection";
import { DemoFixturePanel } from "../features/demo/DemoFixturePanel";
import { KeysOnboardingPanel } from "../features/keys/KeysOnboardingPanel";
import {
  createKeysHttpClient,
  type KeysClient,
} from "../features/keys/client";
import { LiveWizardPanel } from "../features/onboarding/LiveWizardPanel";
import {
  createTrustHttpClient,
  type TrustClient,
} from "../features/onboarding/client";
import { PaidDisclosuresPanel } from "../features/packs/PaidDisclosuresPanel";
import { ReferralDisclosurePanel } from "../features/referral/ReferralDisclosurePanel";
import {
  createReferralHttpClient,
  type ReferralClient,
} from "../features/referral/client";
import type { ReconnectIssue } from "../session";
import {
  ActivationChecklist,
  markActivationStarterChosen,
} from "../features/onboarding/ActivationChecklist";
import {
  isFirstRunCoachDismissed,
  readFirstRunCoachState,
} from "../features/onboarding/firstRunCoachPersistence";
import { PaperStarterChooser } from "../features/onboarding/PaperStarterChooser";
import type { StrategyClient } from "../features/strategies/client";
import type { StarterCatalogue } from "../features/strategies/StarterPicker.client";
import { AboutPanel } from "./AboutPanel";
import type { View } from "./Navigation";
import { ReconnectQr } from "./ReconnectQr";
import "./AppHome.signal.css";

/**
 * Application Home — Signal workspace composition (KRELL-SIGNAL-20261010).
 *
 * First-viewport density (docs/ui-density.md / M25.7): brand + one headline
 * + one supporting sentence + one sage CTA while the first-run coach is
 * active. Advanced rails and the activation checklist stay out of the first
 * viewport until coach skip/complete — checklist **or** coach, never both.
 */

type HomePath = {
  view: View;
  action: string;
  detail: string;
  testid: string;
  meta: string;
};

/** Demoted peer destinations — Advanced “All areas”, not first viewport. */
const HOME_PATH: ReadonlyArray<HomePath> = [
  {
    view: "workstation",
    action: "Open Run",
    detail: "Paper status, last runs, and pause / stop controls.",
    testid: "app-home-card-workstation",
    meta: "Paper · local",
  },
  {
    view: "strategies",
    action: "Edit strategies",
    detail: "Write or paste a pack, save, and reopen from the library.",
    testid: "app-home-card-strategies",
    meta: "Author · library",
  },
  {
    view: "packs",
    action: "Browse packs",
    detail: "Install free or catalogue strategies on this machine.",
    testid: "app-home-card-packs",
    meta: "Catalogue · install",
  },
  {
    view: "studio",
    action: "Open Studio",
    detail: "Inspect a saved strategy as a graph when you want depth.",
    testid: "app-home-card-studio",
    meta: "Graph · edit",
  },
  {
    view: "research",
    action: "Explore research",
    detail: "Backtest your own dataset and read recorded evidence.",
    testid: "app-home-card-research",
    meta: "Backtest · evidence",
  },
  {
    view: "operations",
    action: "Operations",
    detail: "Alerts and the kill switch for this machine.",
    testid: "app-home-card-operations",
    meta: "Alerts · controls",
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
  /** Injectable trust / live-wizard honesty client. */
  trustClient?: TrustClient;
  /** Injectable referral client; defaults to the loopback HTTP client. */
  referralClient?: ReferralClient;
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
  /** Injectable strategy client for the home starter chooser. */
  strategyClient?: StrategyClient;
  /** Starter catalogue loader override (tests). */
  loadStarters?: () => Promise<StarterCatalogue>;
  /** After create+validate, hand off to Run with this revision selected. */
  onStarterReady?: (ready: { revisionId: string; label: string }) => void;
  /**
   * When true, hide the activation checklist so an active FirstRunCoach
   * step owns the chrome (M25.2+). Checklist stays mountable otherwise.
   */
  suppressActivationChecklist?: boolean;
  /** Incomplete checklist: reopen guided setup (coach resume). */
  onResumeActivationSetup?: () => void;
  /**
   * Bump to request opening the home starter chooser (first-run coach).
   * Does not rewrite chooser cards — open only.
   */
  openChooserSignal?: number;
  /**
   * When set, controls whether Advanced home chrome is mounted. When
   * omitted, derived from first-run coach persistence (shown only after
   * skip/complete). Shell passes activationUnlocked.
   */
  showHomeAdvanced?: boolean;
  /** Re-read coach persistence when this bumps (skip / resume / arm). */
  coachSyncKey?: number;
};

export function AppHome({
  onNavigate,
  sessionPending = false,
  sessionFailed = false,
  onRecoverSession,
  keysClient,
  trustClient,
  referralClient,
  versionClient,
  onIssueReconnect,
  onRedeemReconnect,
  strategyClient,
  loadStarters,
  onStarterReady,
  suppressActivationChecklist = false,
  onResumeActivationSetup,
  openChooserSignal = 0,
  showHomeAdvanced,
  coachSyncKey = 0,
}: AppHomeProps): JSX.Element {
  const [chooserOpen, setChooserOpen] = useState(false);
  const lastChooserSignal = useRef(0);
  useEffect(() => {
    if (openChooserSignal > 0 && openChooserSignal !== lastChooserSignal.current) {
      lastChooserSignal.current = openChooserSignal;
      setChooserOpen(true);
    }
  }, [openChooserSignal]);
  const [coachDismissed, setCoachDismissed] = useState(() =>
    isFirstRunCoachDismissed(readFirstRunCoachState()),
  );
  useEffect(() => {
    setCoachDismissed(isFirstRunCoachDismissed(readFirstRunCoachState()));
  }, [coachSyncKey]);
  const advancedVisible =
    showHomeAdvanced !== undefined ? showHomeAdvanced : coachDismissed;
  // Coach owns chrome until skip/complete — never fight the checklist.
  const checklistVisible =
    advancedVisible && !suppressActivationChecklist;
  const [recoverError, setRecoverError] = useState<string | null>(null);
  const recoveryAttempt = useRef(0);
  const fallbackKeysRef = useRef<KeysClient | null>(null);
  if (fallbackKeysRef.current === null && keysClient === undefined) {
    fallbackKeysRef.current = createKeysHttpClient();
  }
  const keys = keysClient ?? fallbackKeysRef.current!;
  const fallbackTrustRef = useRef<TrustClient | null>(null);
  if (fallbackTrustRef.current === null && trustClient === undefined) {
    fallbackTrustRef.current = createTrustHttpClient();
  }
  const trust = trustClient ?? fallbackTrustRef.current!;
  const fallbackReferralRef = useRef<ReferralClient | null>(null);
  if (fallbackReferralRef.current === null && referralClient === undefined) {
    fallbackReferralRef.current = createReferralHttpClient();
  }
  const referral = referralClient ?? fallbackReferralRef.current!;
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
      data-home-advanced={advancedVisible ? "1" : "0"}
      aria-labelledby="app-home-title"
    >
      <header
        className="app-home__hero"
        data-testid="app-home-first-viewport"
      >
        <div className="app-home__hero-brand">
          <BrandMark />
          <div className="app-home__hero-copy">
            <h1 className="app-home__title" id="app-home-title">
              Paper trading on this computer
            </h1>
            <p className="app-home__purpose">
              Start a free strategy with pretend money. Live trading stays off
              in this release.
            </p>
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
                    <label
                      className="app-home__reconnect-label"
                      htmlFor="app-home-reconnect-token"
                    >
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
                      <p
                        data-testid="app-home-reconnect-paste-error"
                        role="alert"
                      >
                        {pasteError}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
        {chooserOpen ? null : (
          <div className="app-home__cta-group">
            <button
              type="button"
              className="app-home__cta"
              data-testid="app-home-cta-paper"
              data-coach-anchor="choose_starter"
              onClick={() => {
                setChooserOpen(true);
              }}
            >
              Start with a free paper strategy
            </button>
            <button
              type="button"
              className="app-home__cta-link"
              data-testid="app-home-cta-packs"
              onClick={() => {
                onNavigate("packs");
              }}
            >
              I already have a pack
            </button>
          </div>
        )}
      </header>

      {chooserOpen ? (
        <PaperStarterChooser
          strategyClient={strategyClient}
          loadStarters={loadStarters}
          onDismiss={() => {
            setChooserOpen(false);
          }}
          onBrowsePacks={() => {
            setChooserOpen(false);
            onNavigate("packs");
          }}
          onReady={(ready) => {
            setChooserOpen(false);
            markActivationStarterChosen(ready);
            if (onStarterReady) {
              onStarterReady(ready);
              return;
            }
            onNavigate("workstation");
          }}
        />
      ) : null}

      {advancedVisible ? (
      <div className="app-home__layout" data-testid="app-home-advanced-stack">
        <div className="app-home__main">
          {checklistVisible ? (
            <div className="app-home__activity" data-testid="app-home-works">
              <ActivationChecklist
                onResumeSetup={onResumeActivationSetup}
                lede="One path: choose a free strategy, start a paper run, and watch status on this machine. Nothing here places real orders."
              />
            </div>
          ) : null}

          <DisclosureSection
            title="All areas"
            summary="Every destination in this app"
            badge="Advanced"
            badgeTone="advanced"
            storageKey="krellbot.disclosure.home.all-areas"
            data-testid="app-home-path"
          >
            <ul className="app-home__cards">
              {HOME_PATH.map((card) => (
                <li key={card.view} className="app-home__card-item">
                  <button
                    type="button"
                    className="app-home__card"
                    data-testid={card.testid}
                    onClick={() => {
                      onNavigate(card.view);
                    }}
                  >
                    <span className="app-home__card-body">
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
          </DisclosureSection>
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
            title="Settings & trust"
            summary="Paid disclosures, referral, telemetry consent, and About — on this computer only. No separate Settings view."
            badge="Advanced"
            badgeTone="advanced"
            defaultOpen={false}
            storageKey="krellbot.disclosure.home.settings-trust"
            bare
            data-testid="app-home-settings-trust"
          >
            <div className="app-home__rail app-home__rail--nested">
              <DisclosureSection
                title="Paid disclosures"
                summary="Fee share / referral when shown; packs not personalized advice; refund window pointer; telemetry opt-in. Does not promise gains."
                badge="Settings"
                badgeTone="advanced"
                defaultOpen={false}
                storageKey="krellbot.disclosure.home.paid-disclosures"
                bare
                data-testid="app-home-paid-disclosures-rail"
              >
                <div className="app-home__rail app-home__rail--nested">
                  <PaidDisclosuresPanel variant="settings" />
                </div>
              </DisclosureSection>

              <DisclosureSection
                title="Exchange fee share / referral"
                summary="Disclosed attribution when an operator creates or links an exchange account through a Krellbot referral path."
                badge="Settings"
                badgeTone="advanced"
                defaultOpen={false}
                storageKey="krellbot.disclosure.home.referral"
                bare
                data-testid="app-home-referral-rail"
              >
                <div className="app-home__rail app-home__rail--nested">
                  <ReferralDisclosurePanel
                    client={referral}
                    enabled={!sessionPending && !sessionFailed}
                  />
                </div>
              </DisclosureSection>

              <DisclosureSection
                title="About this build"
                summary="Version, digest/signing posture honesty, and how to reproduce a starter pack."
                badge="Settings"
                badgeTone="advanced"
                defaultOpen={false}
                storageKey="krellbot.disclosure.home.about"
                bare
                data-testid="app-home-about-rail"
              >
                <div className="app-home__rail app-home__rail--nested">
                  <AboutPanel
                    client={versionClient}
                    enabled={!sessionPending}
                  />
                </div>
              </DisclosureSection>
            </div>
          </DisclosureSection>

          <DisclosureSection
            title="Live-ready path"
            summary="Welcome, trust snapshot, trade-only Exchange probe, and paper-only release vs live grant — no license ask."
            badge="Advanced"
            badgeTone="advanced"
            defaultOpen={false}
            storageKey="krellbot.disclosure.home.live-wizard"
            bare
            data-testid="app-home-live-wizard-rail"
          >
            <div className="app-home__rail app-home__rail--emphasis app-home__rail--nested">
              <LiveWizardPanel
                trustClient={trust}
                keysClient={keys}
                enabled={!sessionPending && !sessionFailed}
              />
            </div>
          </DisclosureSection>

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

          <DisclosureSection
            title="Demo fixture seed"
            summary="Opt-in labeled fixture/demo rows for local preview — never live P&L or soak proof."
            badge="Advanced"
            badgeTone="advanced"
            defaultOpen={false}
            storageKey="krellbot.disclosure.home.demo-fixture"
            bare
            data-testid="app-home-demo-fixture"
          >
            <div className="app-home__rail app-home__rail--nested">
              <DemoFixturePanel
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

        </aside>
      </div>
      ) : null}
    </section>
  );
}

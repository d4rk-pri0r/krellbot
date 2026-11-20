import { useRef, useState, type JSX } from "react";
import { BrandMark } from "../components/brand/BrandMark";
import type { DeploymentRow } from "../features/operations/client";
import { PaperStarterChooser } from "../features/onboarding/PaperStarterChooser";
import type { StrategyClient } from "../features/strategies/client";
import { CONSUMER_STARTER_CARDS } from "../features/strategies/consumerStarterCopy";
import type { StarterCatalogue } from "../features/strategies/StarterPicker.client";
import type { View } from "./Navigation";
import "./AppHome.signal.css";

/**
 * Application Home — Signal workspace composition (KRELL-SIGNAL-20261010).
 *
 * Single focused job: start or open a paper run. Settings, exchange keys,
 * disclosures, local reconnect, and demo fixtures live in the dedicated
 * Settings destination (`?view=settings`).
 */

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
  /**
   * Second browser / failed session: redeem a pasted reconnect token.
   */
  onRedeemReconnect?: (
    token: string,
  ) => Promise<{ ok: boolean; error?: string }>;
  /** Injectable strategy client for the home starter chooser. */
  strategyClient?: StrategyClient;
  /** Starter catalogue loader override (tests). */
  loadStarters?: () => Promise<StarterCatalogue>;
  /** After create+validate, hand off to Run with this revision selected. */
  onStarterReady?: (ready: { revisionId: string; label: string }) => void;
  /** Real armed paper runs reported by /api/v1/operations (empty when none). */
  armedPaperRuns?: ReadonlyArray<DeploymentRow>;
  /** Replay the post-wizard setup tour. Absent in tests that render home alone. */
  onReplaySetupTour?: () => void;
};

function friendlyPaperRunName(packId: string): string {
  return CONSUMER_STARTER_CARDS[packId]?.title ?? packId;
}

export function AppHome({
  onNavigate,
  sessionPending = false,
  sessionFailed = false,
  onRecoverSession,
  onRedeemReconnect,
  strategyClient,
  loadStarters,
  onStarterReady,
  armedPaperRuns = [],
  onReplaySetupTour,
}: AppHomeProps): JSX.Element {
  const [chooserOpen, setChooserOpen] = useState(false);
  const [recoverError, setRecoverError] = useState<string | null>(null);
  const recoveryAttempt = useRef(0);
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

  const primaryPaperRun = armedPaperRuns[0] ?? null;
  const hasPaperRun = primaryPaperRun !== null;
  const primaryPaperTitle = primaryPaperRun
    ? friendlyPaperRunName(primaryPaperRun.pack_id)
    : null;
  const extraPaperRunCount =
    armedPaperRuns.length > 1 ? armedPaperRuns.length - 1 : 0;

  return (
    <section
      className="app-home"
      data-testid="app-home"
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
            {hasPaperRun ? (
              <div
                className="app-home__active-paper"
                data-testid="app-home-active-paper"
                data-paper-state={
                  primaryPaperRun.entries_paused ? "waiting" : "running"
                }
                role="status"
              >
                <span
                  className={
                    primaryPaperRun.entries_paused
                      ? "app-home__active-paper-dot app-home__active-paper-dot--waiting"
                      : "app-home__active-paper-dot"
                  }
                  aria-hidden="true"
                />
                <div className="app-home__active-paper-copy">
                  <p className="app-home__active-paper-title">
                    {primaryPaperRun.entries_paused ? "Waiting" : "Running"}:{" "}
                    {primaryPaperTitle}
                    {extraPaperRunCount > 0
                      ? ` (+${extraPaperRunCount} more)`
                      : ""}
                  </p>
                  <p className="app-home__active-paper-note">
                    Paper only on this computer — pretend money, no real orders.
                  </p>
                </div>
              </div>
            ) : (
              <p className="app-home__purpose">
                Start a free strategy with pretend money. Live trading stays off
                in this release.
              </p>
            )}
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
            {hasPaperRun ? (
              <>
                <button
                  type="button"
                  className="app-home__cta"
                  data-testid="app-home-cta-paper"
                  onClick={() => {
                    onNavigate("workstation");
                  }}
                >
                  Open paper run
                </button>
                <button
                  type="button"
                  className="app-home__cta-link"
                  data-testid="app-home-cta-try-another"
                  onClick={() => {
                    setChooserOpen(true);
                  }}
                >
                  Try another strategy
                </button>
              </>
            ) : (
              <button
                type="button"
                className="app-home__cta"
                data-testid="app-home-cta-paper"
                onClick={() => {
                  setChooserOpen(true);
                }}
              >
                Start with a free paper strategy
              </button>
            )}
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
            {onReplaySetupTour ? (
              <button
                type="button"
                className="app-home__cta-link app-home__cta-tour"
                data-testid="workspace-setup-tour-replay"
                onClick={onReplaySetupTour}
              >
                Take setup tour
              </button>
            ) : null}
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
            if (onStarterReady) {
              onStarterReady(ready);
              return;
            }
            onNavigate("workstation");
          }}
        />
      ) : null}
    </section>
  );
}

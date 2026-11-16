import { useEffect, useRef, useState, type JSX } from "react";
import {
  channelMatchesSigning,
  createVersionHttpClient,
  type VersionClient,
  type VersionInfo,
} from "../api/version";
import "./AboutPanel.signal.css";

export type AboutPanelProps = {
  /** Injectable version client; defaults to the loopback HTTP client. */
  client?: VersionClient;
  /** When false, skip the network read (session still starting). */
  enabled?: boolean;
};

function channelLabel(channel: VersionInfo["channel"]): string {
  return channel === "ga" ? "GA" : "Prerelease";
}

function signingLabel(signed: boolean): string {
  return signed ? "Signed artifacts" : "Unsigned artifacts";
}

/**
 * About / version surface (KRELL-SIGNAL-20261010).
 *
 * Surfaces the engine version string and release-channel honesty from
 * ``GET /api/v1/version``. Never invents a GA claim while artifacts are
 * unsigned.
 */
export function AboutPanel({
  client,
  enabled = true,
}: AboutPanelProps): JSX.Element {
  const fallbackRef = useRef<VersionClient | null>(null);
  if (fallbackRef.current === null && client === undefined) {
    fallbackRef.current = createVersionHttpClient();
  }
  const versionClient = client ?? fallbackRef.current!;
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void versionClient
      .getVersion()
      .then((payload) => {
        if (cancelled) return;
        if (!channelMatchesSigning(payload)) {
          setInfo(null);
          setError("Release channel claim does not match signing state");
          return;
        }
        setInfo(payload);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setInfo(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, versionClient]);

  return (
    <section
      className="kbot-about"
      aria-labelledby="kbot-about-title"
      data-testid="app-home-about"
    >
      <h2 className="kbot-about__title" id="kbot-about-title">
        About
      </h2>
      {loading ? (
        <p className="kbot-about__copy" data-testid="app-home-about-loading">
          Reading version…
        </p>
      ) : null}
      {error !== null ? (
        <p
          className="kbot-about__copy kbot-about__copy--caution"
          data-testid="app-home-about-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      {info !== null ? (
        <dl className="kbot-about__facts" data-testid="app-home-about-facts">
          <div className="kbot-about__row">
            <dt>Version</dt>
            <dd data-testid="app-home-about-version">v{info.version}</dd>
          </div>
          <div className="kbot-about__row">
            <dt>Channel</dt>
            <dd data-testid="app-home-about-channel">
              {channelLabel(info.channel)}
            </dd>
          </div>
          <div className="kbot-about__row">
            <dt>Signing</dt>
            <dd data-testid="app-home-about-signing">
              {signingLabel(info.artifacts_signed)}
            </dd>
          </div>
        </dl>
      ) : null}
      {!loading && error === null && info === null ? (
        <p className="kbot-about__copy" data-testid="app-home-about-empty">
          Version unavailable.
        </p>
      ) : null}
      <p className="kbot-about__copy">
        Public GA releases require signed artifacts. This surface reports the
        channel the engine claims, not a marketing label.
      </p>
    </section>
  );
}

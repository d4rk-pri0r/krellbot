import { useRef, useState, type JSX } from "react";
import {
  createHttpClient,
  type StrategyClient,
} from "../strategies/client";
import {
  StarterPicker,
  type StarterPickerProps,
} from "../strategies/StarterPicker";
import type { StarterExample } from "../strategies/StarterPicker.client";
import "./PaperStarterChooser.signal.css";

export type PaperStarterReady = {
  revisionId: string;
  label: string;
};

export type PaperStarterChooserProps = {
  strategyClient?: StrategyClient;
  loadStarters?: StarterPickerProps["loadStarters"];
  onReady: (ready: PaperStarterReady) => void;
  onBrowsePacks?: () => void;
  onDismiss?: () => void;
};

type BusyState =
  | { kind: "idle" }
  | { kind: "working"; label: string }
  | { kind: "error"; message: string };

/**
 * Home-mounted Chooser A (M24.3): pick a free local starter, create +
 * validate via existing strategy clients, then hand off to Run with a
 * clear paper-arm affordance. Never opens keys or live paths.
 */
export function PaperStarterChooser({
  strategyClient,
  loadStarters,
  onReady,
  onBrowsePacks,
  onDismiss,
}: PaperStarterChooserProps): JSX.Element {
  const fallbackRef = useRef<StrategyClient | null>(null);
  if (fallbackRef.current === null && strategyClient === undefined) {
    fallbackRef.current = createHttpClient();
  }
  const client = strategyClient ?? fallbackRef.current!;
  const [busy, setBusy] = useState<BusyState>({ kind: "idle" });
  const inFlight = useRef(false);

  async function handlePick(example: StarterExample): Promise<void> {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setBusy({ kind: "working", label: example.label });
    try {
      const created = await client.create(example.pack);
      const validated = await client.validate(created.revision_id);
      if (validated.state !== "validated" && validated.state !== "deployed") {
        const detail =
          validated.errors.map((error) => error.message).join("; ") ||
          `validation left state ${validated.state}`;
        setBusy({ kind: "error", message: detail });
        return;
      }
      onReady({
        revisionId: validated.revision_id,
        label: example.label,
      });
    } catch (error) {
      setBusy({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <section
      className="kbot-paper-starter-chooser"
      data-testid="paper-starter-chooser"
      aria-label="Choose a free paper strategy"
    >
      <div className="kbot-paper-starter-chooser__head">
        <h2 className="kbot-paper-starter-chooser__title">
          Choose a free paper strategy
        </h2>
        <p className="kbot-paper-starter-chooser__lede">
          Three free starters with pretend money on this computer. Browse packs
          instead when you already know what you want.
        </p>
        {onDismiss ? (
          <button
            type="button"
            className="kbot-paper-starter-chooser__dismiss"
            data-testid="paper-starter-chooser-dismiss"
            onClick={onDismiss}
          >
            Back
          </button>
        ) : null}
      </div>
      <StarterPicker
        eager
        variant="consumer"
        loadStarters={loadStarters}
        onPick={(example) => {
          void handlePick(example);
        }}
      />
      {busy.kind === "working" ? (
        <p
          className="kbot-paper-starter-chooser__status"
          data-testid="paper-starter-chooser-busy"
          role="status"
        >
          Saving and checking “{busy.label}”…
        </p>
      ) : null}
      {busy.kind === "error" ? (
        <p
          className="kbot-paper-starter-chooser__error"
          data-testid="paper-starter-chooser-error"
          role="alert"
        >
          Could not start that strategy: {busy.message}
        </p>
      ) : null}
      {onBrowsePacks ? (
        <p className="kbot-paper-starter-chooser__secondary">
          <button
            type="button"
            className="kbot-paper-starter-chooser__packs"
            data-testid="paper-starter-chooser-packs"
            onClick={onBrowsePacks}
          >
            Browse packs instead
          </button>
        </p>
      ) : null}
    </section>
  );
}

/**
 * Full-screen Krell first-run wizard (KRELL-SIGNAL-20261010).
 *
 * ≤5 steps; one visual; ≤1 short sentence; one big sage CTA; quiet Skip
 * setup after welcome; persist complete/skip so users are never re-trapped.
 * When strategy and paper clients are passed (the App gate does), step 2
 * saves a free starter, step 3 arms paper only, and step 4 quotes real
 * paper status. Without those clients the shell still walks the steps.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
} from "react";
import type { PaperClient, PaperCommandResult, PaperStatus } from "../paper/client";
import type { StrategyClient } from "../strategies/client";
import {
  CONSUMER_STARTER_CARD_ORDER,
  CONSUMER_STARTER_CARDS,
} from "../strategies/consumerStarterCopy";
import {
  fetchStarters,
  type StarterCatalogue,
  type StarterExample,
} from "../strategies/StarterPicker.client";
import {
  FIRST_RUN_WIZARD_STORAGE_KEY,
  isFirstRunWizardDismissed,
  readFirstRunWizardState,
  writeFirstRunWizardState,
  type FirstRunWizardPersisted,
  type FirstRunWizardStepId,
} from "./firstRunWizardPersistence";
import { WIZARD_STEP_VISUALS } from "./wizardAssets";
import "./FirstRunWizard.signal.css";

export type FirstRunWizardStep = {
  id: FirstRunWizardStepId;
  sentence: string;
  primaryLabel: string;
};

export const DEFAULT_FIRST_RUN_WIZARD_STEPS: ReadonlyArray<FirstRunWizardStep> =
  [
    {
      id: "welcome",
      sentence:
        "Let’s set up a pretend trading bot on this computer — no real money.",
      primaryLabel: "Let’s go",
    },
    {
      id: "choose",
      sentence: "Pick one free strategy to try.",
      primaryLabel: "Use",
    },
    {
      id: "start_paper",
      sentence:
        "Start it with pretend money so you can see how it behaves.",
      primaryLabel: "Start paper run",
    },
    {
      id: "status",
      sentence:
        "It’s running on this computer (paper only — not live trading).",
      primaryLabel: "Looks good",
    },
    {
      id: "win",
      sentence: "You’re set. Here’s your workspace.",
      primaryLabel: "Open Krellbot",
    },
  ];

/** Same initial paper-arm defaults as the Run panel. Paper mode only. */
const WIZARD_PAPER_VENUE = "kraken";
const WIZARD_PAPER_BALANCE = "1000";

export const WIZARD_LIVE_TRADING_UNAVAILABLE = "Live trading unavailable";

export type WizardStatusPhase =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "ready"; status: PaperStatus };

export type WizardStatusChipKind =
  | "checking"
  | "running"
  | "waiting"
  | "not-running"
  | "unavailable"
  | "live-blocked";

export type FirstRunWizardProps = {
  storageKey?: string;
  steps?: ReadonlyArray<FirstRunWizardStep>;
  /**
   * When true, show even if persisted as skipped (tests / explicit resume).
   * Completed stays hidden unless forceShow is set.
   */
  forceShow?: boolean;
  onStepChange?: (stepId: FirstRunWizardStepId) => void;
  onSkip?: () => void;
  onComplete?: () => void;
  /**
   * Fired when the step primary is pressed. Return false to keep the step.
   */
  onPrimaryAction?: (stepId: FirstRunWizardStepId) => boolean | void;
  /**
   * Fired when a starter tile Use is pressed on the choose step.
   * Return false to keep the choose step.
   */
  onSelectStarter?: (starterId: string) => boolean | void;
  /**
   * When this value changes, re-read persisted wizard state.
   */
  syncKey?: number | string;
  /** Existing strategy draft client. Omit to keep the choose step local. */
  strategyClient?: StrategyClient;
  /** Catalogue loader. Defaults to the session starter fetch when saving. */
  loadStarters?: () => Promise<StarterCatalogue>;
  /** Existing paper client. Omit to advance Start paper run without arming. */
  paperClient?: PaperClient;
};

function stepIndexOf(
  steps: ReadonlyArray<FirstRunWizardStep>,
  stepId: FirstRunWizardStepId,
): number {
  const index = steps.findIndex((step) => step.id === stepId);
  return index < 0 ? 0 : index;
}

function persisted(
  status: FirstRunWizardPersisted["status"],
  stepId: FirstRunWizardStepId,
  selectedStarterId: string | null,
  revisionId?: string,
): FirstRunWizardPersisted {
  const next: FirstRunWizardPersisted = {
    status,
    stepId,
    selectedStarterId,
  };
  if (typeof revisionId === "string" && revisionId.length > 0) {
    next.revisionId = revisionId;
  }
  return next;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * One honest sentence from a real paper status read. Never invents P&L
 * and never calls an unconfirmed or non-paper arm "running".
 */
export function honestWizardStatusSentence(phase: WizardStatusPhase): string {
  if (phase.kind === "loading") {
    return "Checking this computer…";
  }
  if (phase.kind === "unavailable") {
    return "Paper status unavailable.";
  }
  const status = phase.status;
  if (status.armed === true && status.mode === "paper") {
    if (status.entries_paused === true) {
      return "Waiting on this computer (paper only — not live trading).";
    }
    return "It’s running on this computer (paper only — not live trading).";
  }
  if (status.armed === true) {
    return "Live trading unavailable.";
  }
  return "Not running on this computer yet.";
}

export function wizardStatusChipKind(
  phase: WizardStatusPhase,
): WizardStatusChipKind {
  if (phase.kind === "loading") {
    return "checking";
  }
  if (phase.kind === "unavailable") {
    return "unavailable";
  }
  const status = phase.status;
  if (status.armed === true && status.mode === "paper") {
    return status.entries_paused === true ? "waiting" : "running";
  }
  if (status.armed === true) {
    return "live-blocked";
  }
  return "not-running";
}

async function validateStarter(
  strategyClient: StrategyClient,
  loadStarters: () => Promise<StarterCatalogue>,
  starterId: string,
): Promise<{ revisionId: string } | { message: string }> {
  let catalogue: StarterCatalogue;
  try {
    catalogue = await loadStarters();
  } catch (error) {
    return { message: `Could not save that strategy: ${errorText(error)}` };
  }
  const example: StarterExample | undefined = catalogue.examples.find(
    (row) => row.id === starterId,
  );
  if (!example) {
    return { message: "That free strategy is not available." };
  }
  try {
    const created = await strategyClient.create(example.pack);
    const validated = await strategyClient.validate(created.revision_id);
    if (validated.state !== "validated" && validated.state !== "deployed") {
      const detail =
        validated.errors
          .map((error) => error.message)
          .filter((message) => message.length > 0)
          .join("; ") || `validation left state ${validated.state}`;
      return { message: `Could not save that strategy: ${detail}` };
    }
    return { revisionId: validated.revision_id };
  } catch (error) {
    return { message: `Could not save that strategy: ${errorText(error)}` };
  }
}

function armRefusal(result: PaperCommandResult | null | undefined): string {
  const message = result?.message;
  if (typeof message === "string" && message.length > 0) {
    return message;
  }
  return "Start paper run refused";
}

export function FirstRunWizard({
  storageKey = FIRST_RUN_WIZARD_STORAGE_KEY,
  steps = DEFAULT_FIRST_RUN_WIZARD_STEPS,
  forceShow = false,
  onStepChange,
  onSkip,
  onComplete,
  onPrimaryAction,
  onSelectStarter,
  syncKey = 0,
  strategyClient,
  loadStarters,
  paperClient,
}: FirstRunWizardProps): JSX.Element | null {
  const [state, setState] = useState<FirstRunWizardPersisted>(() =>
    readFirstRunWizardState(storageKey),
  );
  const [enterKey, setEnterKey] = useState(0);
  const [chooseBusyId, setChooseBusyId] = useState<string | null>(null);
  const [chooseError, setChooseError] = useState<string | null>(null);
  const [armBusy, setArmBusy] = useState(false);
  const [armError, setArmError] = useState<string | null>(null);
  const [statusPhase, setStatusPhase] = useState<WizardStatusPhase>({
    kind: "loading",
  });
  const inFlight = useRef(false);

  useEffect(() => {
    setState(readFirstRunWizardState(storageKey));
  }, [storageKey, syncKey]);

  const persist = useCallback(
    (next: FirstRunWizardPersisted) => {
      writeFirstRunWizardState(next, storageKey);
      setState(next);
      setEnterKey((key) => key + 1);
    },
    [storageKey],
  );

  const dismissed = isFirstRunWizardDismissed(state);
  const visible = forceShow || !dismissed;

  const activeStep = useMemo(() => {
    const index = stepIndexOf(steps, state.stepId);
    return steps[index] ?? steps[0]!;
  }, [steps, state.stepId]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    onStepChange?.(activeStep.id);
  }, [activeStep.id, onStepChange, visible]);

  useEffect(() => {
    if (!visible || activeStep.id !== "status" || !paperClient) {
      return;
    }
    let cancelled = false;
    setStatusPhase({ kind: "loading" });
    paperClient
      .getStatus()
      .then((status) => {
        if (!cancelled) {
          setStatusPhase({ kind: "ready", status });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatusPhase({ kind: "unavailable" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeStep.id, paperClient, visible]);

  if (!visible) {
    return null;
  }

  const showSkip = state.status === "active" || activeStep.id !== "welcome";
  const visual = WIZARD_STEP_VISUALS[activeStep.id];
  const stepNumber = stepIndexOf(steps, activeStep.id) + 1;
  const isWin = activeStep.id === "win";
  const statusWired = activeStep.id === "status" && paperClient !== undefined;
  const sentence = statusWired
    ? honestWizardStatusSentence(statusPhase)
    : activeStep.sentence;
  const statusLoading = statusWired && statusPhase.kind === "loading";
  const catalogueLoader = loadStarters ?? fetchStarters;

  function dismissedNow(): boolean {
    const latest = readFirstRunWizardState(storageKey);
    return latest.status === "skipped" || latest.status === "completed";
  }

  function advanceTo(nextId: FirstRunWizardStepId, revisionId?: string): void {
    persist(
      persisted(
        "active",
        nextId,
        state.selectedStarterId ?? null,
        revisionId ?? state.revisionId,
      ),
    );
  }

  async function saveStarter(starterId: string): Promise<void> {
    if (!strategyClient) {
      persist(persisted("active", "start_paper", starterId));
      return;
    }
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setChooseError(null);
    setChooseBusyId(starterId);
    try {
      const saved = await validateStarter(
        strategyClient,
        catalogueLoader,
        starterId,
      );
      if (dismissedNow()) {
        return;
      }
      if ("message" in saved) {
        setChooseError(saved.message);
        return;
      }
      persist(persisted("active", "start_paper", starterId, saved.revisionId));
    } finally {
      inFlight.current = false;
      setChooseBusyId(null);
    }
  }

  async function armAndAdvance(): Promise<void> {
    if (!paperClient || inFlight.current) {
      return;
    }
    inFlight.current = true;
    setArmError(null);
    setArmBusy(true);
    try {
      let revisionId = state.revisionId;
      if (!revisionId) {
        const starterId = state.selectedStarterId;
        if (!starterId || !strategyClient) {
          setArmError("Pick a strategy first.");
          return;
        }
        const saved = await validateStarter(
          strategyClient,
          catalogueLoader,
          starterId,
        );
        if (dismissedNow()) {
          return;
        }
        if ("message" in saved) {
          setArmError(saved.message);
          return;
        }
        revisionId = saved.revisionId;
        persist(
          persisted(
            "active",
            "start_paper",
            starterId,
            revisionId,
          ),
        );
      }
      const arm = paperClient.arm;
      if (arm === undefined) {
        setArmError("Start paper run controls unavailable");
        return;
      }
      let result: PaperCommandResult;
      try {
        result = await arm.call(paperClient, {
          revision_id: revisionId,
          venue: WIZARD_PAPER_VENUE,
          mode: "paper",
          paper_balance: WIZARD_PAPER_BALANCE,
        });
      } catch (reason) {
        if (!dismissedNow()) {
          setArmError(
            `Start paper run outcome unknown: ${errorText(reason)}. Refresh status to see the server state before retrying.`,
          );
        }
        return;
      }
      if (dismissedNow()) {
        return;
      }
      if (result?.ok !== true) {
        setArmError(armRefusal(result));
        return;
      }
      const index = stepIndexOf(steps, "start_paper");
      const nextStep = steps[index + 1];
      if (!nextStep) {
        return;
      }
      persist(
        persisted(
          "active",
          nextStep.id,
          state.selectedStarterId ?? null,
          revisionId,
        ),
      );
    } finally {
      inFlight.current = false;
      setArmBusy(false);
    }
  }

  function handlePrimary(): void {
    const gate = onPrimaryAction?.(activeStep.id);
    if (gate === false) {
      return;
    }
    if (activeStep.id === "welcome") {
      persist(persisted("active", "choose", null));
      return;
    }
    if (activeStep.id === "win") {
      persist(
        persisted(
          "completed",
          "win",
          state.selectedStarterId ?? null,
          state.revisionId,
        ),
      );
      onComplete?.();
      return;
    }
    if (activeStep.id === "choose") {
      return;
    }
    if (activeStep.id === "start_paper" && paperClient) {
      void armAndAdvance();
      return;
    }
    if (statusLoading) {
      return;
    }
    const index = stepIndexOf(steps, activeStep.id);
    const nextStep = steps[index + 1];
    if (!nextStep) {
      persist(
        persisted(
          "completed",
          "win",
          state.selectedStarterId ?? null,
          state.revisionId,
        ),
      );
      onComplete?.();
      return;
    }
    advanceTo(nextStep.id);
  }

  function handleSelectStarter(starterId: string): void {
    const gate = onSelectStarter?.(starterId);
    if (gate === false) {
      return;
    }
    void saveStarter(starterId);
  }

  function handleSkip(): void {
    persist(
      persisted(
        "skipped",
        activeStep.id,
        state.selectedStarterId ?? null,
        state.revisionId,
      ),
    );
    onSkip?.();
  }

  const primaryLabel =
    activeStep.id === "start_paper" && armBusy
      ? "Starting…"
      : activeStep.primaryLabel;

  return (
    <div
      className={
        isWin
          ? "kbot-first-run-wizard kbot-first-run-wizard--win"
          : "kbot-first-run-wizard"
      }
      data-testid="first-run-wizard"
      data-wizard-status={state.status}
      data-wizard-step={activeStep.id}
      role="dialog"
      aria-modal="true"
      aria-labelledby="kbot-first-run-wizard-sentence"
    >
      <div className="kbot-first-run-wizard__chrome">
        <div
          className="kbot-first-run-wizard__progress"
          data-testid="first-run-wizard-progress"
          aria-hidden="true"
        >
          {steps.map((step, index) => (
            <span
              key={step.id}
              className={
                index < stepNumber
                  ? "kbot-first-run-wizard__dot kbot-first-run-wizard__dot--on"
                  : "kbot-first-run-wizard__dot"
              }
              data-testid={`first-run-wizard-dot-${step.id}`}
            />
          ))}
        </div>

        <div
          className="kbot-first-run-wizard__stage"
          key={`${activeStep.id}-${enterKey}`}
          data-testid="first-run-wizard-stage"
        >
          <img
            className="kbot-first-run-wizard__visual"
            data-testid="first-run-wizard-visual"
            data-wizard-visual={visual.name}
            src={visual.src}
            alt=""
          />

          <p
            id="kbot-first-run-wizard-sentence"
            className="kbot-first-run-wizard__sentence"
            data-testid="first-run-wizard-sentence"
          >
            {sentence}
          </p>

          {statusWired ? (
            <p
              className="kbot-first-run-wizard__chip"
              data-testid="first-run-wizard-status-chip"
              data-paper-status={wizardStatusChipKind(statusPhase)}
            >
              {WIZARD_LIVE_TRADING_UNAVAILABLE}
            </p>
          ) : null}

          {activeStep.id === "choose" ? (
            <>
              <ul
                className="kbot-first-run-wizard__tiles"
                data-testid="first-run-wizard-tiles"
              >
                {CONSUMER_STARTER_CARD_ORDER.map((id) => {
                  const card = CONSUMER_STARTER_CARDS[id]!;
                  const busy = chooseBusyId === id;
                  return (
                    <li key={id} className="kbot-first-run-wizard__tile">
                      <p className="kbot-first-run-wizard__tile-title">
                        {card.title}
                      </p>
                      <button
                        type="button"
                        className="kbot-first-run-wizard__primary"
                        data-testid={`first-run-wizard-use-${id}`}
                        disabled={chooseBusyId !== null}
                        onClick={() => handleSelectStarter(id)}
                      >
                        {busy ? "Saving…" : "Use"}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {chooseError !== null ? (
                <p
                  className="kbot-first-run-wizard__alert"
                  data-testid="first-run-wizard-choose-error"
                  role="alert"
                >
                  {chooseError}
                </p>
              ) : null}
            </>
          ) : (
            <button
              type="button"
              className="kbot-first-run-wizard__primary"
              data-testid="first-run-wizard-primary"
              disabled={armBusy || statusLoading}
              onClick={handlePrimary}
            >
              {primaryLabel}
            </button>
          )}

          {activeStep.id === "start_paper" && armError !== null ? (
            <p
              className="kbot-first-run-wizard__alert"
              data-testid="first-run-wizard-arm-error"
              role="alert"
            >
              {armError}
            </p>
          ) : null}

          {showSkip ? (
            <button
              type="button"
              className="kbot-first-run-wizard__skip"
              data-testid="first-run-wizard-skip"
              disabled={chooseBusyId !== null || armBusy}
              onClick={handleSkip}
            >
              Skip setup
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export {
  DEFAULT_FIRST_RUN_WIZARD_STATE,
  FIRST_RUN_WIZARD_STORAGE_KEY,
  isFirstRunWizardDismissed,
  readFirstRunWizardState,
  writeFirstRunWizardState,
} from "./firstRunWizardPersistence";

/**
 * Arrow-style setup tour (KRELL-SIGNAL-20261010).
 *
 * Mounted only after the intro wizard has exited. The scrim does not
 * take pointer events — existing cockpit clicks pass through. The card
 * tracks a real control and stays inside the viewport.
 */
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type JSX,
} from "react";
import {
  placeSetupTourCallout,
  type Box,
  type SetupTourPlacement,
} from "./workspaceSetupTourPlacement";
import {
  WORKSPACE_SETUP_TOUR_STEPS,
  type WorkspaceSetupTourStepId,
} from "./workspaceSetupTourPersistence";
import "./WorkspaceSetupTour.signal.css";

export type WorkspaceSetupTourProps = {
  stepId: WorkspaceSetupTourStepId;
  paperArmed: boolean;
  launchBusy?: boolean;
  launchError?: string | null;
  onBack: () => void;
  onNext: () => void;
  onStartPaper: () => void;
  onComplete: () => void;
  onDismiss: () => void;
};

type Copy = {
  title: string;
  body: string;
};

const COPY: Record<WorkspaceSetupTourStepId, Copy> = {
  workspace: {
    title: "Paper mode on this computer",
    body: "This workspace simulates on your computer with pretend money. Live trading stays off in this release.",
  },
  keys: {
    title: "Exchange keys, if you want them",
    body: "Trade-only keys live in Settings and stay in the local keyring on this computer. Paper simulation does not need keys.",
  },
  strategy: {
    title: "Strategy and pretend balance",
    body: "Pick or swap a free starter and set the pretend paper balance. That cash never leaves this computer.",
  },
  run: {
    title: "Check the paper simulation",
    body: "Start the paper run if it is not going yet. When it is running, free pretend cash and pause or stop sit on this control.",
  },
};

const RUNNING_STRATEGY_COPY: Copy = {
  title: "Active strategy and pretend balance",
  body: "Your paper strategy and pretend balance sit here in Run. That cash never leaves this computer.",
};

const RUNNING_COPY: Copy = {
  title: "Your paper simulation is running",
  body: "This active paper run is simulating on your computer. Free pretend cash sits with the position. Pause new buys or stop the run from here.",
};

function targetIds(stepId: WorkspaceSetupTourStepId): readonly string[] {
  if (stepId === "workspace") {
    return [
      "app-home-active-paper",
      "app-home-availability",
      "app-home-first-viewport",
      "kbot-status-strip",
    ];
  }
  if (stepId === "keys") {
    return ["keys-public-kraken", "keys-form-kraken", "keys-onboarding-kraken"];
  }
  if (stepId === "strategy") {
    return [
      "paper-arm-balance",
      "paper-arm-revision",
      "paper-arm-empty",
      "paper-status-empty",
      "paper-status-pack",
      "paper-position",
      "paper-arm-form",
    ];
  }
  return [
    "paper-status-entries",
    "paper-position",
    "paper-arm-submit",
    "paper-arm-balance",
    "paper-arm-empty",
    "paper-status-empty",
    "paper-arm-form",
  ];
}

function boxOf(element: HTMLElement): Box {
  const rect = element.getBoundingClientRect();
  return {
    top: rect.top,
    left: rect.left,
    width: rect.width,
    height: rect.height,
  };
}

function visibleBox(element: HTMLElement): Box | null {
  const box = boxOf(element);
  if (box.width <= 2 || box.height <= 2) {
    return null;
  }
  return box;
}

function findAnchor(stepId: WorkspaceSetupTourStepId): {
  id: string;
  element: HTMLElement;
  box: Box;
} | null {
  for (const id of targetIds(stepId)) {
    const element = document.querySelector<HTMLElement>(
      `[data-testid="${id}"]`,
    );
    if (!element) {
      continue;
    }
    const box = visibleBox(element);
    if (!box) {
      continue;
    }
    return { id, element, box };
  }
  return null;
}

function collectBoxes(anchor: HTMLElement | null, selectors: readonly string[]): Box[] {
  const boxes: Box[] = [];
  const seen = new Set<HTMLElement>();
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    if (!(element instanceof HTMLElement) || element === anchor || seen.has(element)) {
      continue;
    }
    seen.add(element);
    const box = visibleBox(element);
    if (box) {
      boxes.push(box);
    }
  }
  return boxes;
}

function blockedBoxes(anchor: HTMLElement | null): Box[] {
  return collectBoxes(anchor, [
    '[data-testid="kbot-nav"]',
    '[data-testid="app-home-cta-paper"]',
    '[data-testid="app-home-availability"]',
    ".kbot-shell__header",
  ]);
}

function avoidBoxes(anchor: HTMLElement | null): Box[] {
  return collectBoxes(anchor, [
    '[data-testid="kbot-shell-palette-hint"]',
    '[data-testid="keys-store-kraken"]',
    '[data-testid="paper-arm-submit"]',
    '[data-testid="first-win-celebrate"]',
    ".kbot-paper-status__actions",
  ]);
}

function viewportSize(): { width: number; height: number } {
  const width = window.innerWidth || document.documentElement.clientWidth || 1440;
  const height = window.innerHeight || document.documentElement.clientHeight || 900;
  return { width, height };
}

function cardWidthFor(viewportWidth: number): number {
  return Math.min(360, Math.max(200, viewportWidth - 24));
}

function runIsShowing(): boolean {
  return (
    document.querySelector(
      '[data-testid="paper-status-entries"], [data-testid="paper-position"], [data-testid="app-home-active-paper"]',
    ) !== null
  );
}

function placementSignature(
  placement: SetupTourPlacement,
  anchorId: string | null,
  width: number,
): string {
  const round = (value: number): number => Math.round(value);
  return [
    anchorId ?? "",
    width,
    round(placement.card.top),
    round(placement.card.left),
    round(placement.card.width),
    round(placement.card.height),
    placement.arrow
      ? [
          round(placement.arrow.x1),
          round(placement.arrow.y1),
          round(placement.arrow.x2),
          round(placement.arrow.y2),
        ].join(",")
      : "",
  ].join("|");
}

export function WorkspaceSetupTour({
  stepId,
  paperArmed,
  launchBusy = false,
  launchError = null,
  onBack,
  onNext,
  onStartPaper,
  onComplete,
  onDismiss,
}: WorkspaceSetupTourProps): JSX.Element {
  const titleId = useId();
  const markerId = useId().replace(/:/g, "");
  const cardRef = useRef<HTMLElement | null>(null);
  const scrolledFor = useRef<string | null>(null);
  const [anchorId, setAnchorId] = useState<string | null>(null);
  const [running, setRunning] = useState(paperArmed);
  const [placement, setPlacement] = useState<SetupTourPlacement>(() =>
    placeSetupTourCallout({
      viewport: { width: 1440, height: 900 },
      target: null,
      card: { width: 360, height: 220 },
    }),
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== "Escape" || event.altKey || event.ctrlKey || event.metaKey) {
        return;
      }
      onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onDismiss]);

  useLayoutEffect(() => {
    let frame = 0;
    let cancelled = false;
    const measure = (): void => {
      if (cancelled) {
        return;
      }
      const viewport = viewportSize();
      const width = cardWidthFor(viewport.width);
      const showing = paperArmed || runIsShowing();
      setRunning((current) => (current === showing ? current : showing));
      const anchor = findAnchor(stepId);
      if (anchor) {
        const headerBottom =
          document.querySelector(".kbot-shell__header")?.getBoundingClientRect().bottom ??
          72;
        // Room for the sticky header plus the heading that sits above the
        // control (for example "Start your paper run" over the empty line).
        const clearance = Math.ceil(headerBottom + 72);
        const scrollKey = `${stepId}:${anchor.id}`;
        const rect = anchor.element.getBoundingClientRect();
        const inBand =
          rect.top >= clearance - 4 &&
          rect.bottom <= viewport.height - 16 &&
          rect.left >= -1 &&
          rect.right <= viewport.width + 1;
        anchor.element.style.scrollMarginTop = `${clearance}px`;
        anchor.element.style.scrollMarginBottom = "24px";
        const retryKey = `${scrollKey}:retried`;
        const attempts = scrolledFor.current;
        if (!inBand && attempts !== retryKey) {
          anchor.element.scrollIntoView({
            block: "start",
            inline: "nearest",
            behavior: "auto",
          });
          scrolledFor.current = attempts === scrollKey ? retryKey : scrollKey;
          requestAnimationFrame(() => {
            requestAnimationFrame(measure);
          });
          return;
        }
      }
      const fresh = findAnchor(stepId);
      const measured = cardRef.current?.getBoundingClientRect().height ?? 0;
      const height = measured > 40 ? measured : 220;
      const next = placeSetupTourCallout({
        viewport,
        target: fresh?.box ?? null,
        card: { width, height },
        blocked: blockedBoxes(fresh?.element ?? null),
        avoid: avoidBoxes(fresh?.element ?? null),
      });
      const nextAnchor = fresh?.id ?? null;
      setAnchorId((current) => (current === nextAnchor ? current : nextAnchor));
      setPlacement((current) => {
        if (
          placementSignature(current, nextAnchor, width) ===
          placementSignature(next, nextAnchor, width)
        ) {
          return current;
        }
        return next;
      });
    };
    measure();
    const onMove = (): void => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    const observer = new MutationObserver(onMove);
    observer.observe(document.body, { childList: true, subtree: true });
    const resizeObserver =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(onMove)
        : null;
    resizeObserver?.observe(document.documentElement);
    const fonts = document.fonts;
    if (fonts && typeof fonts.ready?.then === "function") {
      void fonts.ready.then(onMove);
    }
    const timer = window.setInterval(measure, 400);
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
      observer.disconnect();
      resizeObserver?.disconnect();
      window.clearInterval(timer);
    };
  }, [stepId, paperArmed, launchBusy, launchError]);

  const stepIndex = WORKSPACE_SETUP_TOUR_STEPS.indexOf(stepId);
  const isRunning = running || paperArmed;
  const copy =
    stepId === "run" && isRunning
      ? RUNNING_COPY
      : stepId === "strategy" && isRunning
        ? RUNNING_STRATEGY_COPY
        : COPY[stepId];
  const onFirst = stepIndex <= 0;
  const onLast = stepId === "run";
  const showDone = onLast && (running || paperArmed);
  const primaryLabel = launchBusy
    ? "Starting…"
    : showDone
      ? "Done"
      : onLast
        ? "Start paper run"
        : "Next";

  function handlePrimary(): void {
    if (launchBusy) {
      return;
    }
    if (!onLast) {
      onNext();
      return;
    }
    if (showDone) {
      onComplete();
      return;
    }
    onStartPaper();
  }

  const width = placement.card.width;

  return (
    <div
      className="kbot-setup-tour"
      data-testid="workspace-setup-tour"
      data-setup-step={stepId}
      data-anchor={anchorId ?? ""}
      data-anchored={placement.arrow ? "1" : "0"}
      data-paper-armed={paperArmed || running ? "1" : "0"}
    >
      {placement.spotlight ? (
        <div
          className="kbot-setup-tour__spotlight"
          data-testid="workspace-setup-tour-spotlight"
          style={{
            top: placement.spotlight.top,
            left: placement.spotlight.left,
            width: placement.spotlight.width,
            height: placement.spotlight.height,
          }}
        />
      ) : null}
      <svg
        className="kbot-setup-tour__arrow"
        data-testid="workspace-setup-tour-arrow"
        aria-hidden="true"
      >
        <defs>
          <marker
            id={markerId}
            markerWidth="10"
            markerHeight="10"
            refX="8"
            refY="5"
            orient="auto"
          >
            <path d="M0,0 L10,5 L0,10 Z" />
          </marker>
        </defs>
        {placement.arrow ? (
          <line
            x1={placement.arrow.x1}
            y1={placement.arrow.y1}
            x2={placement.arrow.x2}
            y2={placement.arrow.y2}
            markerEnd={`url(#${markerId})`}
          />
        ) : null}
      </svg>
      <section
        ref={cardRef}
        className="kbot-setup-tour__card"
        data-testid="workspace-setup-tour-card"
        aria-labelledby={titleId}
        style={{
          top: placement.card.top,
          left: placement.card.left,
          width,
        }}
      >
        <p
          className="kbot-setup-tour__progress"
          data-testid="workspace-setup-tour-progress"
        >
          {stepIndex + 1} of {WORKSPACE_SETUP_TOUR_STEPS.length}
        </p>
        <h2
          className="kbot-setup-tour__title"
          id={titleId}
          data-testid="workspace-setup-tour-title"
        >
          {copy.title}
        </h2>
        <p className="kbot-setup-tour__body">{copy.body}</p>
        {launchError ? (
          <p
            className="kbot-setup-tour__error"
            role="alert"
            data-testid="workspace-setup-tour-error"
          >
            {launchError}
          </p>
        ) : null}
        <div className="kbot-setup-tour__actions">
          <button
            type="button"
            className="kbot-setup-tour__back"
            data-testid="workspace-setup-tour-back"
            disabled={onFirst || launchBusy}
            onClick={onBack}
          >
            Back
          </button>
          <button
            type="button"
            className="kbot-setup-tour__next"
            data-testid="workspace-setup-tour-next"
            disabled={launchBusy}
            onClick={handlePrimary}
          >
            {primaryLabel}
          </button>
          <button
            type="button"
            className="kbot-setup-tour__skip"
            data-testid="workspace-setup-tour-skip"
            onClick={onDismiss}
          >
            Skip tour
          </button>
        </div>
      </section>
    </div>
  );
}

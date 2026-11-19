/**
 * App root gate (M26.4).
 *
 * Cold open with an incomplete first-run wizard mounts ONLY FirstRunWizard
 * (full viewport). WorkstationShell — brand bar, Navigation, Jobs,
 * CommandPalette, AppHome cockpit, Advanced rails — stays unmounted until
 * the wizard is completed or skipped. Deep-link query params remain in the
 * URL; the shell reads them after mount (never a half-cockpit under the
 * wizard). Choose, Start paper run, and status use the existing strategy
 * and paper clients (paper arm only — no live).
 */
import { useRef, useState, type JSX } from "react";
import {
  FirstRunWizard,
  isFirstRunWizardDismissed,
} from "./features/onboarding/FirstRunWizard";
import {
  createHttpClient as createPaperHttpClient,
  type PaperClient,
} from "./features/paper/client";
import {
  createHttpClient as createStrategyHttpClient,
  type StrategyClient,
} from "./features/strategies/client";
import { WorkstationShell } from "./shell/WorkstationShell";

export function App(): JSX.Element {
  const [wizardDismissed, setWizardDismissed] = useState(() =>
    isFirstRunWizardDismissed(),
  );
  const strategyClientRef = useRef<StrategyClient | null>(null);
  const paperClientRef = useRef<PaperClient | null>(null);
  if (strategyClientRef.current === null) {
    strategyClientRef.current = createStrategyHttpClient();
  }
  if (paperClientRef.current === null) {
    paperClientRef.current = createPaperHttpClient();
  }

  if (!wizardDismissed) {
    return (
      <FirstRunWizard
        strategyClient={strategyClientRef.current}
        paperClient={paperClientRef.current}
        onComplete={() => {
          setWizardDismissed(true);
        }}
        onSkip={() => {
          setWizardDismissed(true);
        }}
      />
    );
  }

  return <WorkstationShell />;
}

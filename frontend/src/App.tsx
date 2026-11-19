/**
 * App root gate (M26.4).
 *
 * Cold open with an incomplete first-run wizard mounts ONLY FirstRunWizard
 * (full viewport). WorkstationShell — brand bar, Navigation, Jobs,
 * CommandPalette, AppHome cockpit, Advanced rails — stays unmounted until
 * the wizard is completed or skipped. Deep-link query params remain in the
 * URL; the shell reads them after mount (never a half-cockpit under the
 * wizard). Choose, Start paper run, and status use the existing strategy
 * and paper clients (paper arm only — no live). The wizard win screen
 * is the celebration; the shell does not toast over it. The setup tour
 * arms in the same exit and is not mounted while this wizard is up.
 */
import { useRef, useState, type JSX } from "react";
import {
  FirstRunWizard,
  isFirstRunWizardDismissed,
} from "./features/onboarding/FirstRunWizard";
import { ensureLoopbackSession } from "./loopbackSession";
import { adoptLegacyFirstRunDismissal } from "./features/onboarding/legacyFirstRunMigration";
import {
  createHttpClient as createPaperHttpClient,
  type PaperClient,
} from "./features/paper/client";
import {
  createHttpClient as createStrategyHttpClient,
  type StrategyClient,
} from "./features/strategies/client";
import { armWorkspaceSetupTour } from "./features/onboarding/workspaceSetupTourPersistence";
import { WorkstationShell } from "./shell/WorkstationShell";

export function App(): JSX.Element {
  const [wizardDismissed, setWizardDismissed] = useState(() => {
    adoptLegacyFirstRunDismissal();
    return isFirstRunWizardDismissed();
  });
  const strategyClientRef = useRef<StrategyClient | null>(null);
  const paperClientRef = useRef<PaperClient | null>(null);
  const sessionReadyRef = useRef<Promise<boolean> | null>(null);
  if (sessionReadyRef.current === null) {
    sessionReadyRef.current = ensureLoopbackSession();
  }
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
        sessionReady={sessionReadyRef.current}
        onComplete={() => {
          armWorkspaceSetupTour();
          setWizardDismissed(true);
        }}
        onSkip={() => {
          armWorkspaceSetupTour();
          setWizardDismissed(true);
        }}
      />
    );
  }

  return <WorkstationShell />;
}

/**
 * App root gate (M26.4).
 *
 * Cold open with an incomplete first-run wizard mounts ONLY FirstRunWizard
 * (full viewport). WorkstationShell — brand bar, Navigation, Jobs,
 * CommandPalette, AppHome cockpit, Advanced rails — stays unmounted until
 * the wizard is completed or skipped. Deep-link query params remain in the
 * URL; the shell reads them after mount (never a half-cockpit under the
 * wizard).
 */
import { useState, type JSX } from "react";
import {
  FirstRunWizard,
  isFirstRunWizardDismissed,
} from "./features/onboarding/FirstRunWizard";
import { WorkstationShell } from "./shell/WorkstationShell";

export function App(): JSX.Element {
  const [wizardDismissed, setWizardDismissed] = useState(() =>
    isFirstRunWizardDismissed(),
  );

  if (!wizardDismissed) {
    return (
      <FirstRunWizard
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

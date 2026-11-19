/**
 * Krell character visuals for FirstRunWizard (M26.3).
 *
 * Paths match M26.2 staged assets under `frontend/src/assets/character/`
 * and PROVENANCE step mapping. Do not invent poses.
 */
import krellHero from "../../assets/character/krell-hero.webp";
import krellGuide from "../../assets/character/krell-guide.webp";
import krellWaistup from "../../assets/character/krell_waistup.png";
import krellPortrait from "../../assets/character/krell_portrait.png";
import krellSecurity from "../../assets/character/krell_security.png";
import type { FirstRunWizardStepId } from "./firstRunWizardPersistence";

export type WizardVisual = {
  src: string;
  /** Stable filename for tests / data attributes. */
  name: string;
};

export const WIZARD_STEP_VISUALS: Readonly<
  Record<FirstRunWizardStepId, WizardVisual>
> = {
  welcome: { src: krellHero, name: "krell-hero.webp" },
  choose: { src: krellGuide, name: "krell-guide.webp" },
  start_paper: { src: krellWaistup, name: "krell_waistup.png" },
  status: { src: krellPortrait, name: "krell_portrait.png" },
  win: { src: krellSecurity, name: "krell_security.png" },
};

/**
 * Krell character visuals for FirstRunWizard (KRELL-SIGNAL-20261010).
 *
 * One illustration per step, each showing the Astra Signal Krell
 * (navy-to-cyan bob, glasses, hoodie, KRELLBOT shirt, circuit tattoo,
 * cybernetic arm) with a prop that matches that step's sentence.
 * Backgrounds are transparent so the art blends on the navy canvas.
 * Filenames stay stable for wizard visual assertions.
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
  // Waving beside a local laptop with a toy bot and play-coins.
  welcome: { src: krellHero, name: "krell-hero.webp" },
  // Presenting three chart cards: moving-average cross, mean-reversion band, range breakout.
  choose: { src: krellGuide, name: "krell-guide.webp" },
  // Pressing a play switch beside a simulation gauge and play tokens.
  start_paper: { src: krellWaistup, name: "krell_waistup.png" },
  // Watching a local monitor with a seafoam pulse and a paper shield on the bezel.
  status: { src: krellPortrait, name: "krell_portrait.png" },
  // Unveiling a workspace window with a seafoam check and sparkles.
  win: { src: krellSecurity, name: "krell_security.png" },
};

/**
 * Launch pack family honesty copy — M21.2 / docs/launch-pack-family.md.
 */
import { describe, expect, it } from "vitest";
import {
  isLaunchPackFamilySku,
  LAUNCH_PACK_FAMILY_HONESTY,
  LAUNCH_PACK_FAMILY_SKU,
  launchPackFamilyCopyIsHonest,
} from "./launchPackFamily";

describe("launchPackFamily honesty", () => {
  it("pins the DCA launch SKU", () => {
    expect(LAUNCH_PACK_FAMILY_SKU).toBe("paid-launch-dca");
    expect(isLaunchPackFamilySku("paid-launch-dca")).toBe(true);
    expect(isLaunchPackFamilySku("paid-triple-stack")).toBe(false);
  });

  it("ships honest helper copy without returns promises", () => {
    expect(launchPackFamilyCopyIsHonest(LAUNCH_PACK_FAMILY_HONESTY)).toBe(true);
    expect(LAUNCH_PACK_FAMILY_HONESTY.toLowerCase()).toContain(
      "not personalized advice",
    );
    expect(LAUNCH_PACK_FAMILY_HONESTY.toLowerCase()).toMatch(/fixture/);
    expect(LAUNCH_PACK_FAMILY_HONESTY.toLowerCase()).toMatch(/backtest/);
    expect(LAUNCH_PACK_FAMILY_HONESTY.toLowerCase()).not.toMatch(
      /guaranteed\s+returns?/,
    );
  });

  it("refuses returns-promise copy", () => {
    expect(
      launchPackFamilyCopyIsHonest(
        "not personalized advice fixture backtest with guaranteed returns",
      ),
    ).toBe(false);
    expect(launchPackFamilyCopyIsHonest("tools only")).toBe(false);
  });
});

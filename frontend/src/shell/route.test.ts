/**
 * Client view routing helpers (M7.2).
 * Contract: KRELL-SIGNAL-20261010.
 */
import { afterEach, describe, expect, it } from "vitest";
import {
  SECTION_QUERY,
  VIEW_QUERY,
  buildLocationForView,
  isSettingsSection,
  isView,
  parseViewFromSearch,
  resolveSettingsSectionFromSearch,
  resolveViewFromSearch,
  syncViewToHistory,
} from "./route";

afterEach(() => {
  window.history.pushState({}, "", "/");
});

describe("route — parse and resolve", () => {
  it("recognises every shell view id and rejects unknowns", () => {
    for (const id of [
      "home",
      "workstation",
      "strategies",
      "packs",
      "settings",
      "research",
      "studio",
      "operations",
      "deployments",
    ]) {
      expect(isView(id)).toBe(true);
    }
    expect(isView("jobs")).toBe(false);
    expect(isView("")).toBe(false);
    expect(isView(null)).toBe(false);
  });

  it("resolves settings sections and falls back to keys", () => {
    for (const sec of ["keys", "safety", "trust", "privacy", "computer", "about"]) {
      expect(isSettingsSection(sec)).toBe(true);
      expect(resolveSettingsSectionFromSearch(`?view=settings&${SECTION_QUERY}=${sec}`)).toBe(sec);
    }
    expect(isSettingsSection("unknown")).toBe(false);
    expect(resolveSettingsSectionFromSearch("?view=settings")).toBe("keys");
    expect(resolveSettingsSectionFromSearch("?view=settings&section=nope")).toBe("keys");
  });

  it("parses an explicit view query param", () => {
    expect(parseViewFromSearch("?view=strategies")).toBe("strategies");
    expect(parseViewFromSearch("view=operations")).toBe("operations");
    expect(parseViewFromSearch("?view=nope")).toBeNull();
    expect(parseViewFromSearch("")).toBeNull();
  });

  it("lets explicit view win over workload deep links", () => {
    expect(resolveViewFromSearch("?view=home&workload=200")).toBe("home");
    expect(resolveViewFromSearch("?workload=200&view=research")).toBe(
      "research",
    );
  });

  it("opens Studio for workload deep links without an explicit view", () => {
    expect(resolveViewFromSearch("?workload=200")).toBe("studio");
    expect(resolveViewFromSearch("?workload=200&pack=1")).toBe("studio");
  });

  it("defaults a bare launch to Workspace home", () => {
    expect(resolveViewFromSearch("")).toBe("home");
    expect(resolveViewFromSearch("?pack=1")).toBe("home");
  });
});

describe("route — build and sync history", () => {
  it("builds a location that sets view while preserving other params", () => {
    expect(buildLocationForView("strategies", "")).toBe("/?view=strategies");
    expect(buildLocationForView("studio", "?workload=200&pack=1")).toBe(
      "/?workload=200&pack=1&view=studio",
    );
    expect(buildLocationForView("home", "?workload=200", "#frag")).toBe(
      "/?workload=200&view=home#frag",
    );
    expect(buildLocationForView("settings", "", "", "privacy")).toBe(
      "/?view=settings&section=privacy",
    );
    expect(buildLocationForView("home", "?view=settings&section=privacy")).toBe(
      "/?view=home",
    );
  });

  it("pushes a new history entry when the view changes", () => {
    const before = window.history.length;
    syncViewToHistory("workstation", "push");
    expect(window.location.search).toContain(`${VIEW_QUERY}=workstation`);
    expect(window.history.length).toBeGreaterThanOrEqual(before);
  });

  it("does not push when the URL already encodes the same view", () => {
    window.history.pushState({}, "", "/?view=research");
    const length = window.history.length;
    syncViewToHistory("research", "push");
    expect(window.history.length).toBe(length);
    expect(window.location.search).toBe("?view=research");
  });

  it("replace mode updates the URL without requiring a different view key", () => {
    window.history.pushState({}, "", "/");
    syncViewToHistory("deployments", "replace");
    expect(window.location.search).toBe("?view=deployments");
  });
});

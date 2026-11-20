/**
 * Client view routing (M7.2).
 *
 * Contract: KRELL-SIGNAL-20261010.
 *
 * URL shape: `/?view=<id>` plus any existing search params (`workload`,
 * `pack`, …). A bare `/` with no `view` is Workspace (home). Synthetic
 * studio deep links (`?workload=200`, optionally `&pack=1`) still open
 * Studio when no explicit `view` is present.
 *
 * ## Draft / selection reload policy
 *
 * - **View:** restored from the `view` query param on load and on
 *   browser back/forward (`popstate`).
 * - **Unsaved drafts, canvas node selection, library/packs open state,
 *   inspector selection:** not encoded in the URL. A full page reload
 *   clears them; the restored view opens in its empty/default state.
 * - **In-session soft navigation:** Research and Strategies Editor keep
 *   visited portal state across view switches. That is orthogonal to
 *   URL routing and is unchanged by soft navigates that do not reload.
 * - **Explicit `view` wins** over workload deep-link defaults, so
 *   `/?view=home&workload=200` reloads to Workspace, not Studio.
 */

import type { View } from "./Navigation";

export const VIEW_QUERY = "view";
export const SECTION_QUERY = "section";

export type SettingsSection =
  | "keys"
  | "safety"
  | "trust"
  | "privacy"
  | "computer"
  | "about";

export const SETTINGS_SECTIONS: ReadonlyArray<SettingsSection> = [
  "keys",
  "safety",
  "trust",
  "privacy",
  "computer",
  "about",
];

const KNOWN_SETTINGS_SECTIONS: ReadonlySet<string> = new Set(SETTINGS_SECTIONS);

export function isSettingsSection(
  value: string | null | undefined,
): value is SettingsSection {
  return typeof value === "string" && KNOWN_SETTINGS_SECTIONS.has(value);
}

export function resolveSettingsSectionFromSearch(
  search: string,
): SettingsSection {
  const raw = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(raw);
  const candidate = params.get(SECTION_QUERY);
  return isSettingsSection(candidate) ? candidate : "keys";
}

const KNOWN_VIEWS: ReadonlySet<string> = new Set([
  "home",
  "workstation",
  "strategies",
  "packs",
  "settings",
  "research",
  "studio",
  "operations",
  "deployments",
]);

export function isView(value: string | null | undefined): value is View {
  return typeof value === "string" && KNOWN_VIEWS.has(value);
}

export function parseViewFromSearch(search: string): View | null {
  const raw = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(raw);
  const candidate = params.get(VIEW_QUERY);
  return isView(candidate) ? candidate : null;
}

/**
 * Resolve which shell view a location should show.
 *
 * Priority: explicit `view` → workload deep link → Workspace.
 */
export function resolveViewFromSearch(search: string): View {
  const explicit = parseViewFromSearch(search);
  if (explicit) {
    return explicit;
  }
  const raw = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(raw);
  if (params.get("workload") === "200") {
    return "studio";
  }
  return "home";
}

/**
 * Build a same-origin path+search(+hash) that selects `view` while
 * preserving every other current search param and the hash.
 * Clears `section` when leaving `settings`.
 */
export function buildLocationForView(
  view: View,
  currentSearch: string,
  currentHash = "",
  settingsSection?: SettingsSection,
): string {
  const raw = currentSearch.startsWith("?")
    ? currentSearch.slice(1)
    : currentSearch;
  const params = new URLSearchParams(raw);
  params.set(VIEW_QUERY, view);
  if (view === "settings") {
    if (settingsSection) {
      params.set(SECTION_QUERY, settingsSection);
    } else if (!isSettingsSection(params.get(SECTION_QUERY))) {
      params.delete(SECTION_QUERY);
    }
  } else {
    params.delete(SECTION_QUERY);
  }
  const qs = params.toString();
  const hash = currentHash && !currentHash.startsWith("#")
    ? `#${currentHash}`
    : currentHash;
  return qs ? `/?${qs}${hash}` : `/${hash}`;
}

function locationKey(pathname: string, search: string, hash: string): string {
  return `${pathname}${search}${hash}`;
}

/**
 * Push or replace the history entry so the URL reflects `view`.
 * No-ops when the URL already encodes that view (avoids duplicate
 * history entries when re-activating the current tab).
 */
export function syncViewToHistory(
  view: View,
  mode: "push" | "replace" = "push",
  settingsSection?: SettingsSection,
): void {
  if (typeof window === "undefined") {
    return;
  }
  const next = buildLocationForView(
    view,
    window.location.search,
    window.location.hash,
    settingsSection,
  );
  const current = locationKey(
    window.location.pathname,
    window.location.search,
    window.location.hash,
  );
  if (current === next) {
    return;
  }
  if (mode === "replace") {
    window.history.replaceState(window.history.state, "", next);
  } else {
    window.history.pushState(window.history.state, "", next);
  }
}

/**
 * Shared Vitest setup for the frontend unit suite.
 *
 * Client routing (M7.2) writes ``?view=`` into ``window.location`` via
 * ``history.pushState``. jsdom keeps that search string across tests in
 * the same file, so a later mount would restore the previous view
 * instead of the bare ``/`` launch every existing shell test assumes.
 * Reset the location before each test; individual suites that need a
 * deep link set it themselves inside the test body.
 */
import { beforeEach } from "vitest";

beforeEach(() => {
  if (typeof window === "undefined") {
    return;
  }
  window.history.replaceState(window.history.state, "", "/");
});

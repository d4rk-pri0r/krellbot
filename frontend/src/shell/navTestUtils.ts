import { fireEvent, screen, within } from "@testing-library/react";

const MORE_LABELS = new Set([
  "Research",
  "Strategy studio",
  "Operations",
  "Deploy",
]);

/** Click a shell nav button, expanding More first when needed (M24). */
export function clickShellNav(label: string): void {
  const resolved = label === "Workstation" ? "Run" : label;
  const nav = screen.getByTestId("kbot-nav");
  if (MORE_LABELS.has(resolved)) {
    const toggle = within(nav).getByTestId("kbot-nav-more-toggle");
    if (toggle.getAttribute("aria-expanded") !== "true") {
      fireEvent.click(toggle);
    }
  }
  // Scope to the nav strip so Research's primary "Run" button cannot collide
  // with the Run destination tab when More is open.
  fireEvent.click(within(nav).getByRole("button", { name: resolved }));
}

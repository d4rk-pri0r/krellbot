import { useEffect, useState, type JSX } from "react";
import { CommandPalette } from "./CommandPalette";
import { Inspector } from "./Inspector";
import { JobsDrawer } from "./JobsDrawer";
import { Navigation } from "./Navigation";
import { StatusStrip } from "./StatusStrip";

export function WorkstationShell(): JSX.Element {
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.key.toLowerCase() === "k" &&
        (event.ctrlKey || event.metaKey)
      ) {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="kbot-shell">
      <div className="kbot-shell__topbar">
        <StatusStrip />
        <JobsDrawer />
      </div>
      <Navigation />
      <main className="kbot-shell__main">
        <h1 className="kbot-shell__heading">Paper workstation</h1>
        <Inspector />
      </main>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
      />
    </div>
  );
}

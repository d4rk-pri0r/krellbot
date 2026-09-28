import { useEffect, useMemo, useState, type JSX } from "react";
import { Editor } from "../features/strategies/Editor";
import { createHttpClient } from "../features/strategies/client";
import { CommandPalette } from "./CommandPalette";
import { Inspector } from "./Inspector";
import { JobsDrawer } from "./JobsDrawer";
import { Navigation, type View } from "./Navigation";
import { StatusStrip } from "./StatusStrip";

export function WorkstationShell(): JSX.Element {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [active, setActive] = useState<View>("workstation");
  const client = useMemo(() => createHttpClient(), []);

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
      <Navigation active={active} onChange={setActive} />
      <main className="kbot-shell__main">
        {active === "workstation" ? (
          <>
            <h1 className="kbot-shell__heading">Paper workstation</h1>
            <Inspector />
          </>
        ) : null}
        {active === "strategies" ? <Editor client={client} /> : null}
        {active === "research" ? (
          <section
            className="kbot-research"
            role="region"
            aria-label="Research"
          >
            <h1 className="kbot-shell__heading">Research</h1>
          </section>
        ) : null}
      </main>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
      />
    </div>
  );
}

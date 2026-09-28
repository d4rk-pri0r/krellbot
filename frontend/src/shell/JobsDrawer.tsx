import { useState, type JSX } from "react";

export function JobsDrawer(): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="kbot-jobs__trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="kbot-jobs-drawer"
        onClick={() => setOpen(true)}
      >
        Jobs
      </button>
      {open ? (
        <div
          id="kbot-jobs-drawer"
          className="kbot-jobs__scrim"
          role="dialog"
          aria-modal="true"
          aria-label="Jobs"
        >
          <button
            type="button"
            className="kbot-jobs__close"
            aria-label="Close jobs drawer"
            onClick={() => setOpen(false)}
          >
            Close
          </button>
          <h2 className="kbot-jobs__title">Jobs</h2>
          <p className="kbot-jobs__empty">No jobs</p>
        </div>
      ) : null}
    </>
  );
}

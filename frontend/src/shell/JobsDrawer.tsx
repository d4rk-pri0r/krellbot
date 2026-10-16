import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import { JobsDrawerCsvExport } from "../features/studio/JobsDrawerCsvExport";
import { getCsrf } from "../session";
import { summarizeJobsKind } from "./jobsKindLabel";

export type JobRow = {
  id: string;
  kind: string;
  state: string;
};

export type JobsClient = {
  list(): Promise<JobRow[]>;
};

async function listJobs(): Promise<JobRow[]> {
  const response = await fetch("/api/v1/jobs", {
    method: "GET",
    credentials: "include",
    headers: { "X-Krellbot-CSRF": getCsrf() },
  });
  if (!response.ok) {
    throw new Error(`jobs failed: ${response.status}`);
  }
  const body: unknown = await response.json();
  if (body === null || typeof body !== "object") {
    throw new Error("jobs response is not an object");
  }
  const jobs = (body as { jobs?: unknown }).jobs;
  if (!Array.isArray(jobs)) {
    throw new Error("jobs response has no jobs array");
  }
  return jobs.map((row) => {
    if (row === null || typeof row !== "object") {
      throw new Error("jobs response has a malformed row");
    }
    const item = row as { id?: unknown; kind?: unknown; state?: unknown };
    if (
      !isNonemptyString(item.id) ||
      !isNonemptyString(item.kind) ||
      !isNonemptyString(item.state)
    ) {
      throw new Error("jobs response has a malformed row");
    }
    return { id: item.id, kind: item.kind, state: item.state };
  });
}

function isNonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export type JobsDrawerProps = {
  client?: JobsClient;
};

export function JobsDrawer({ client }: JobsDrawerProps = {}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<JobRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const load = useCallback((): void => {
    const requestId = ++requestIdRef.current;
    setJobs(null);
    setError(null);
    const list = client?.list ?? listJobs;
    void list().then(
      (rows) => {
        if (requestId !== requestIdRef.current) {
          return;
        }
        setJobs(rows);
        setError(null);
      },
      (err: unknown) => {
        if (requestId !== requestIdRef.current) {
          return;
        }
        setJobs(null);
        setError(
          `Jobs are unavailable: ${
            err instanceof Error ? err.message : "the request failed"
          }`,
        );
      },
    );
  }, [client]);

  const close = useCallback((): void => {
    requestIdRef.current += 1;
    setJobs(null);
    setError(null);
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    load();
  }, [open, load]);

  useEffect(() => {
    if (!open || !dialogRef.current) {
      return;
    }
    const dialog = dialogRef.current;
    const trigger = triggerRef.current;
    const focusable = (): HTMLElement[] =>
      Array.from(dialog.querySelectorAll<HTMLElement>(
        "button, [href], input, select, textarea, [tabindex]",
      )).filter((element) =>
        element.tabIndex >= 0 && !element.matches(":disabled") &&
        !element.closest("[hidden], [inert]") &&
        getComputedStyle(element).display !== "none" &&
        getComputedStyle(element).visibility !== "hidden",
      );
    const focusFirst = (): void => {
      (focusable()[0] ?? dialog).focus();
    };
    const onFocus = (event: FocusEvent): void => {
      if (event.target instanceof Node && !dialog.contains(event.target)) {
        focusFirst();
      }
    };
    const onKey = (event: KeyboardEvent): void => {
      // Keep shell shortcuts from activating controls behind the modal.
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.key === "Tab") {
        const targets = focusable();
        const index = targets.indexOf(document.activeElement as HTMLElement);
        if (index < 0 || (event.shiftKey ? index === 0 : index === targets.length - 1)) {
          event.preventDefault();
          (event.shiftKey ? targets.at(-1) ?? dialog : targets[0] ?? dialog).focus();
        }
      } else if (!dialog.contains(event.target as Node)) {
        event.preventDefault();
        focusFirst();
      }
    };
    focusFirst();
    document.addEventListener("focusin", onFocus);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("keydown", onKey, true);
      trigger?.focus();
    };
  }, [open, close]);

  return (
    <>
      <button
        type="button"
        className="kbot-jobs__trigger"
        ref={triggerRef}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="kbot-jobs-drawer"
        onClick={() => {
          if (open) {
            return;
          }
          requestIdRef.current += 1;
          setJobs(null);
          setError(null);
          setOpen(true);
        }}
      >
        Jobs
      </button>
      {open ? (
        <div
          id="kbot-jobs-drawer"
          className="kbot-jobs__scrim"
          role="dialog"
          aria-modal="true"
          ref={dialogRef}
          tabIndex={-1}
          aria-label="Jobs"
        >
          <div className="kbot-jobs__dialog" data-testid="kbot-jobs-dialog">
            <div className="kbot-jobs__head">
              <h2 className="kbot-jobs__title">Jobs</h2>
              <button
                type="button"
                className="kbot-jobs__close"
                aria-label="Close jobs drawer"
                onClick={close}
              >
                Close
              </button>
            </div>
            <button type="button" className="kbot-jobs__refresh" onClick={load}>
              Refresh jobs
            </button>
            <JobsDrawerCsvExport jobs={jobs ?? []} />
            {error ? <p role="alert">{error}</p> : null}
            {jobs === null && !error ? (
              <p className="kbot-jobs__loading" data-testid="jobs-loading">
                Loading jobs…
              </p>
            ) : null}
            {jobs !== null && !error ? (
              jobs.length === 0 ? (
                <p className="kbot-jobs__empty">No jobs</p>
              ) : (
                <ul className="kbot-jobs__list">
                  {jobs.map((job) => (
                    <li key={job.id} className="kbot-jobs__row" data-testid="job-row">
                      <span className="kbot-jobs__id">{job.id}</span>{" "}
                      <span className="kbot-jobs__kind">
                        {summarizeJobsKind(job.kind).label}
                      </span>{" "}
                      <span className="kbot-jobs__state">({job.state})</span>
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}

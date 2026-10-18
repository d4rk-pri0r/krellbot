import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import "./JobsDrawer.signal.css";
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

const LOADING_TEXT = "Loading jobs…";
const EMPTY_TITLE = "No jobs";
const EMPTY_TEXT = "No jobs yet. Local preview only — live trading unavailable.";
const LIST_ERROR_TEXT = "Could not load jobs — check the workstation is running.";
const BLOCKED_TEXT = "Jobs blocked — local-only preview.";
const LOCAL_PREVIEW_BADGE = "Local preview";
const RETRY_TEXT = "Retry";

/**
 * A read the local loopback API refuses (HTTP 403) is a blocked read, not a
 * generic load failure: the workstation is running but this surface is
 * local-only. Every other failure keeps the "check the workstation" copy.
 */
function isBlockedRead(message: string): boolean {
  return /\b403\b|forbidden|blocked/i.test(message);
}

function failureMessage(err: unknown): string {
  return err instanceof Error ? err.message : "the request failed";
}

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
  const [error, setError] = useState<{ blocked: boolean; detail: string } | null>(null);
  const requestIdRef = useRef(0);

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
        const detail = failureMessage(err);
        setJobs(null);
        setError({ blocked: isBlockedRead(detail), detail });
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

  return (
    <div className="kbot-shell__jobs-root">
      <button
        type="button"
        className="kbot-jobs__trigger"
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
          aria-label="Jobs"
        >
          <div className="kbot-jobs__dialog" data-testid="kbot-jobs-dialog">
            <div className="kbot-jobs__head">
              <h2 className="kbot-jobs__title">Jobs</h2>
              <p className="kbot-jobs__preview-badge" data-testid="jobs-local-preview">
                {LOCAL_PREVIEW_BADGE}
              </p>
              <button
                type="button"
                className="kbot-jobs__close"
                aria-label="Close jobs drawer"
                onClick={close}
              >
                Close
              </button>
            </div>
            <div className="kbot-jobs__toolbar">
              <button
                type="button"
                className="kbot-jobs__refresh"
                data-testid="jobs-refresh"
                onClick={load}
              >
                Refresh jobs
              </button>
              <JobsDrawerCsvExport jobs={jobs ?? []} />
            </div>
            {error ? (
              <div className="kbot-jobs__row-result" role="alert" data-testid="jobs-error">
                <p className="kbot-jobs__row-result-text">
                  {error.blocked ? BLOCKED_TEXT : LIST_ERROR_TEXT}
                </p>
                <p className="kbot-jobs__row-result-detail">{error.detail}</p>
                <button type="button" className="kbot-jobs__retry" onClick={load}>
                  {RETRY_TEXT}
                </button>
              </div>
            ) : null}
            {jobs === null && !error ? (
              <p className="kbot-jobs__loading" data-testid="jobs-loading">
                {LOADING_TEXT}
              </p>
            ) : null}
            {jobs !== null && !error ? (
              jobs.length === 0 ? (
                <div className="kbot-jobs__empty" data-testid="jobs-empty">
                  <p className="kbot-jobs__empty-title">{EMPTY_TITLE}</p>
                  <p className="kbot-jobs__empty-detail">{EMPTY_TEXT}</p>
                </div>
              ) : (
                <ul className="kbot-jobs__list">
                  {jobs.map((job) => (
                    <li
                      key={job.id}
                      className="kbot-jobs__row"
                      data-testid="job-row"
                      tabIndex={0}
                    >
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
    </div>
  );
}

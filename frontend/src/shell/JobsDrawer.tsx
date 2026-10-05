import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import { getCsrf } from "../session";

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

  return (
    <>
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
          <button
            type="button"
            className="kbot-jobs__close"
            aria-label="Close jobs drawer"
            onClick={close}
          >
            Close
          </button>
          <h2 className="kbot-jobs__title">Jobs</h2>
          <button type="button" className="kbot-jobs__refresh" onClick={load}>
            Refresh jobs
          </button>
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
              <ul>
                {jobs.map((job) => (
                  <li key={job.id} data-testid="job-row">
                    {job.id} {job.kind} {job.state}
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </div>
      ) : null}
    </>
  );
}

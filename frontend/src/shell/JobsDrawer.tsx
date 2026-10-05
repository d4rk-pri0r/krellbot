import { useEffect, useState, type JSX } from "react";
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
  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    const list = client?.list ?? listJobs;
    setJobs(null);
    setError(null);
    void list().then(
      (rows) => {
        if (!cancelled) {
          setJobs(rows);
          setError(null);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setJobs(null);
          setError(err instanceof Error ? err.message : "jobs failed");
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [open, client]);

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

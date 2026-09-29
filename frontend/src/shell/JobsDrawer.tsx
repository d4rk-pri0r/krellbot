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
  const body = (await response.json()) as { jobs?: unknown };
  if (!Array.isArray(body.jobs)) {
    return [];
  }
  return body.jobs.flatMap((row) => {
    if (!row || typeof row !== "object") {
      return [];
    }
    const item = row as { id?: unknown; kind?: unknown; state?: unknown };
    if (typeof item.id !== "string" || typeof item.state !== "string") {
      return [];
    }
    return [
      {
        id: item.id,
        kind: typeof item.kind === "string" ? item.kind : "",
        state: item.state,
      },
    ];
  });
}

export type JobsDrawerProps = {
  client?: JobsClient;
};

export function JobsDrawer({ client }: JobsDrawerProps = {}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    const list = client?.list ?? listJobs;
    void list().then(
      (rows) => {
        if (!cancelled) {
          setJobs(rows);
          setError(null);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setJobs([]);
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
          {jobs.length === 0 && !error ? (
            <p className="kbot-jobs__empty">No jobs</p>
          ) : (
            <ul>
              {jobs.map((job) => (
                <li key={job.id} data-testid="job-row">
                  {job.id} {job.state}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </>
  );
}

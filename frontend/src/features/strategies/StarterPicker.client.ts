import { getCsrf } from "../../session";
import type { Pack } from "./client";

export type StarterExample = {
  id: string;
  label: string;
  description: string;
  pack: Pack;
};

export type StarterCatalogue = {
  schema_version: string;
  catalogue_version: string;
  examples: StarterExample[];
};

/** Fixed total read deadline for the catalogue request, in milliseconds. */
const STARTERS_READ_DEADLINE_MS = 10000;

function startersReadTimeout(): Error {
  return new Error(
    `starter catalogue read timed out after ${STARTERS_READ_DEADLINE_MS}ms`,
  );
}

/**
 * Fetch the shipped free starter catalogue from
 * `GET /api/v1/packs/starters` using the existing loopback session
 * (cookie + CSRF token) — the same session discipline every other
 * frontend fetch in this shell uses.
 *
 * Throws an `Error` on any non-2xx or malformed body so the picker can
 * render an explicit inline failure instead of an empty list.
 *
 * The whole read — response headers and JSON body — is bounded by one
 * fixed 10000ms deadline. A read stalled past the deadline rejects
 * with an honest read-timeout error and aborts the request this call
 * owns; a catalogue arriving late from the expired attempt can never
 * settle this promise, so the picker always leaves its Loading state.
 */
export async function fetchStarters(): Promise<StarterCatalogue> {
  const controller = new AbortController();
  let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    deadlineTimer = setTimeout(() => {
      controller.abort();
      reject(startersReadTimeout());
    }, STARTERS_READ_DEADLINE_MS);
  });
  try {
    return await Promise.race([readStarters(controller.signal), deadline]);
  } finally {
    clearTimeout(deadlineTimer);
  }
}

async function readStarters(signal: AbortSignal): Promise<StarterCatalogue> {
  let response: Response;
  try {
    response = await fetch("/api/v1/packs/starters", {
      method: "GET",
      credentials: "include",
      headers: { "X-Krellbot-CSRF": getCsrf() },
      signal,
    });
  } catch (error) {
    throw signal.aborted ? startersReadTimeout() : error;
  }
  if (!response.ok) {
    throw new Error(`starter catalogue unavailable: ${response.status}`);
  }
  let body: Partial<StarterCatalogue>;
  try {
    body = (await response.json()) as Partial<StarterCatalogue>;
  } catch (error) {
    throw signal.aborted ? startersReadTimeout() : error;
  }
  if (
    typeof body.schema_version !== "string" ||
    typeof body.catalogue_version !== "string" ||
    !Array.isArray(body.examples)
  ) {
    throw new Error("starter catalogue response malformed");
  }
  const examples: StarterExample[] = [];
  for (const row of body.examples) {
    if (!row || typeof row !== "object") {
      throw new Error("starter catalogue response malformed");
    }
    const candidate = row as Partial<StarterExample>;
    if (
      typeof candidate.id !== "string" ||
      typeof candidate.label !== "string" ||
      typeof candidate.description !== "string" ||
      !candidate.pack ||
      typeof candidate.pack !== "object" ||
      Array.isArray(candidate.pack)
    ) {
      throw new Error("starter catalogue response malformed");
    }
    examples.push({
      id: candidate.id,
      label: candidate.label,
      description: candidate.description,
      pack: candidate.pack as Pack,
    });
  }
  return {
    schema_version: body.schema_version,
    catalogue_version: body.catalogue_version,
    examples,
  };
}

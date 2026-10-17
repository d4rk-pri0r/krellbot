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

/**
 * Fetch the shipped free starter catalogue from
 * `GET /api/v1/packs/starters` using the existing loopback session
 * (cookie + CSRF token) — the same session discipline every other
 * frontend fetch in this shell uses.
 *
 * Throws an `Error` on any non-2xx or malformed body so the picker can
 * render an explicit inline failure instead of an empty list.
 */
export async function fetchStarters(): Promise<StarterCatalogue> {
  const response = await fetch("/api/v1/packs/starters", {
    method: "GET",
    credentials: "include",
    headers: { "X-Krellbot-CSRF": getCsrf() },
  });
  if (!response.ok) {
    throw new Error(`starter catalogue unavailable: ${response.status}`);
  }
  const body = (await response.json()) as Partial<StarterCatalogue>;
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

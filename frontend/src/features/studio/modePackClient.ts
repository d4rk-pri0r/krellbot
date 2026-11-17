import { getCsrf } from "../../session";
import type { Pack } from "../strategies/client";

export type ModePackRow = {
  id: string;
  label: string;
  description: string;
  pack: Pack;
};

export type ModePackCatalogue = {
  schema_version: string;
  modes: ModePackRow[];
};

const MODES_READ_DEADLINE_MS = 10000;

function modesReadTimeout(): Error {
  return new Error(
    `mode pack catalogue read timed out after ${MODES_READ_DEADLINE_MS}ms`,
  );
}

/**
 * Fetch built-in trading-mode packs from ``GET /api/v1/packs/modes``.
 * Same loopback session discipline as starters (cookie + CSRF).
 */
export async function fetchModePacks(): Promise<ModePackCatalogue> {
  const controller = new AbortController();
  let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    deadlineTimer = setTimeout(() => {
      controller.abort();
      reject(modesReadTimeout());
    }, MODES_READ_DEADLINE_MS);
  });
  try {
    const response = await Promise.race([
      fetch("/api/v1/packs/modes", {
        method: "GET",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        signal: controller.signal,
      }),
      deadline,
    ]);
    if (!response.ok) {
      throw new Error(`mode pack catalogue unavailable: ${response.status}`);
    }
    const body = (await response.json()) as Partial<ModePackCatalogue>;
    if (typeof body.schema_version !== "string" || !Array.isArray(body.modes)) {
      throw new Error("mode pack catalogue response malformed");
    }
    const modes: ModePackRow[] = [];
    for (const row of body.modes) {
      if (
        !row ||
        typeof row !== "object" ||
        typeof row.id !== "string" ||
        typeof row.label !== "string" ||
        typeof row.description !== "string" ||
        !row.pack ||
        typeof row.pack !== "object" ||
        Array.isArray(row.pack)
      ) {
        throw new Error("mode pack catalogue response malformed");
      }
      modes.push({
        id: row.id,
        label: row.label,
        description: row.description,
        pack: row.pack as Pack,
      });
    }
    return { schema_version: body.schema_version, modes };
  } finally {
    if (deadlineTimer !== undefined) {
      clearTimeout(deadlineTimer);
    }
  }
}

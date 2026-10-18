/** Record mutating browser commands and refuse live intent BEFORE sending. */
import type { Page } from "@playwright/test";

export type CommandRecord = {method: string; url: string; body?: string; classifiedLive: boolean; commandName?: string};
export type CommandLog = {records: CommandRecord[]};

function liveIntent(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(liveIntent);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).some(([key, child]) =>
    ((key === "mode" || key === "execution_mode") && child === "live") ||
    ((key === "live" || key === "enable_live") && child === true) || liveIntent(child));
}

export async function attachCommandLog(page: Page): Promise<CommandLog> {
  const log: CommandLog = {records: []};
  await page.context().route("**/api/**", async (route) => {
    const req = route.request();
    if (!["POST", "PUT", "PATCH", "DELETE"].includes(req.method())) { await route.fallback(); return; }
    const pathname = new URL(req.url()).pathname;
    let data: Record<string, unknown> = {};
    try { data = JSON.parse(req.postData() ?? "{}"); } catch { /* malformed writes remain product refusals */ }
    const commandName = typeof data.command === "string" ? data.command : "";
    const classifiedLive = liveIntent(data) || /^(live|order|trade)[.:-]/i.test(commandName) || /\/(live|orders?|trade)(\/|$)/i.test(pathname);
    if (pathname !== "/api/v1/session/bootstrap") log.records.push({method: req.method(), url: req.url(), body: req.postData() ?? "", commandName, classifiedLive});
    if (classifiedLive) await route.abort("blockedbyclient");
    else await route.fallback();
  });
  return log;
}

export function assertNoLiveOrderCommands(log: CommandLog): void {
  const refused = log.records.filter((r) => r.classifiedLive);
  if (refused.length) throw new Error(`command-log: live-order intent refused: ${JSON.stringify(refused)}`);
}

export function liveOrderFlagInArgs(argv: ReadonlyArray<string>): boolean {
  return argv.some((arg, i) => /^(--live|--place-order|--execute-live)(=|$)/i.test(arg) ||
    /^(trade|place-order|live-order)$/i.test(arg) || /^--mode=live$/i.test(arg) ||
    (arg === "--mode" && argv[i + 1] === "live"));
}

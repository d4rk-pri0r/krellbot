export type PaperCommandName = "Pause" | "Resume" | "Disarm" | string;

export type PaperRefusalSummary = {
  label: string;
  command: PaperCommandName;
  code: string | null;
  fallback: string;
  isKnownCommand: boolean;
  hasServerMessage: boolean;
};

/**
 * Pure formatter for a refused paper command result. The three refusal
 * branches in StatusPanel render `label`; the remaining fields exist so a
 * future error contract (structured `reason`, a `code` badge) can land in one
 * place instead of three.
 */
export function summarizePaperCommandRefusal(
  command: PaperCommandName,
  result: { message?: string; code?: string } | null | undefined,
): PaperRefusalSummary {
  // Empty string is treated as missing; whitespace-only is preserved as-is.
  const message = typeof result?.message === "string" ? result.message : "";
  const code =
    typeof result?.code === "string" && result.code.length > 0
      ? result.code
      : null;
  const hasServerMessage = message.length > 0;
  const fallback = `${command} refused`;

  return {
    label: hasServerMessage ? message : fallback,
    command,
    code,
    fallback,
    isKnownCommand:
      command === "Pause" || command === "Resume" || command === "Disarm",
    hasServerMessage,
  };
}

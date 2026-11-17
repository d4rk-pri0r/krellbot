import { getCsrf } from "../../session";

export type HomeExportResult = {
  blob: Blob;
  filename: string;
};

export type HomeExportClient = {
  exportHome(): Promise<HomeExportResult>;
};

function filenameFromDisposition(header: string | null): string {
  if (!header) {
    return "krellbot-home.tar.gz";
  }
  const match = /filename="([^"]+)"/i.exec(header);
  if (match && match[1]) {
    return match[1];
  }
  return "krellbot-home.tar.gz";
}

export function createHomeExportHttpClient(): HomeExportClient {
  return {
    async exportHome(): Promise<HomeExportResult> {
      const response = await fetch("/api/v1/home/export", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Krellbot-CSRF": getCsrf(),
        },
        body: "{}",
      });
      if (!response.ok) {
        let detail = "";
        try {
          const errBody = (await response.json()) as { code?: unknown; message?: unknown };
          if (typeof errBody.code === "string" && errBody.code) {
            detail = `: ${errBody.code}`;
          } else if (typeof errBody.message === "string" && errBody.message) {
            detail = `: ${errBody.message}`;
          }
        } catch {
          // ignore non-JSON error bodies
        }
        throw new Error(`home export failed: ${response.status}${detail}`);
      }
      const blob = await response.blob();
      const filename = filenameFromDisposition(
        response.headers.get("Content-Disposition"),
      );
      return { blob, filename };
    },
  };
}

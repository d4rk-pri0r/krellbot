export type Capabilities = {
  schema_version: string;
  paper_commands: string[];
  research: boolean;
  live_orders: boolean;
};

export async function fetchCapabilities(): Promise<Capabilities> {
  const response = await fetch("/api/v1/capabilities", {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`capabilities request failed: ${response.status}`);
  }
  return (await response.json()) as Capabilities;
}

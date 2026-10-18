/** Find a file by name under a directory tree (sync). */
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

export function findFileSync(root: string, filename: string): string {
  const walk = (current: string): string => {
    for (const entry of readdirSync(current)) {
      const full = join(current, entry);
      const st = statSync(full);
      if (st.isDirectory()) {
        const hit = walk(full);
        if (hit) return hit;
      } else if (entry === filename) {
        return full;
      }
    }
    return "";
  };
  const hit = walk(root);
  if (!hit) {
    throw new Error(`${filename} not found under ${root}`);
  }
  return hit;
}

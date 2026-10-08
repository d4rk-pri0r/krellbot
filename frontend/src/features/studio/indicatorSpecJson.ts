export type IndicatorSpecLike = {
  name: string;
  len: number;
};

/**
 * Serialize an indicator snapshot as pretty JSON with a trailing newline.
 * Key order is fixed (name, then len) so exports are byte-stable.
 */
export function indicatorSpecToJson(spec: IndicatorSpecLike): string {
  return `${JSON.stringify({ name: spec.name, len: spec.len }, null, 2)}\n`;
}

/**
 * Build the download filename for an indicator spec export. Non
 * ``[A-Za-z0-9_]`` characters become underscores; a fully slugged-away
 * name falls back to ``_unnamed`` so the filename is never empty.
 */
export function indicatorSpecFilename(name: string, timestamp: string): string {
  const slug = name.replace(/[^A-Za-z0-9_]/g, "_") || "_unnamed";
  return `krellbot-indicator-${slug}-${timestamp}.json`;
}

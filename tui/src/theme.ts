// Theme: "midnight forest" — deep charcoal-green surfaces, restrained borders,
// muted secondary text, one calm green accent. Inspired by btop's
// furarchy-midnight, tinted toward forest greenery. No neon, no gradients.

export const C = {
  // surfaces (deepest → most elevated)
  bg: "#0b0f0d",
  panel: "#101612",
  hover: "#16211a",
  selected: "#1b2a20",
  // lines & text
  border: "#1f2c23",
  borderActive: "#3d6a4f",
  fg: "#c2cec4",
  dim: "#6d7d71",
  dimmer: "#46524a",
  // accents
  green: "#5aab7d", // primary accent
  greenBright: "#8fd4a8", // pointers, active markers
  greenDeep: "#23402f", // selection tint
  teal: "#6fb3a8", // info
  amber: "#c9a76a", // warnings, "update available"
  red: "#c06a6a", // errors
} as const

export const GLYPH = {
  ok: "✓",
  warn: "▲",
  err: "✗",
  info: "·",
  arrow: "→",
  pointer: "❯",
  bullet: "·",
  up: "↑",
} as const

export function trunc(s: string | null | undefined, n: number): string {
  if (!s) return ""
  return s.length > n ? s.slice(0, Math.max(0, n - 1)) + "…" : s
}

export function pad(s: string, n: number): string {
  const t = trunc(s, n)
  return t + " ".repeat(Math.max(0, n - t.length))
}

export function humanSize(bytes: number | null | undefined): string {
  if (!bytes) return "?"
  const units = ["B", "KiB", "MiB", "GiB", "TiB"]
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

/** Color for an update-status string, shared by every view. */
export function statusColor(status: string | null | undefined): string {
  switch (status) {
    case "update_available":
      return C.amber
    case "up_to_date":
      return C.green
    case "no_source":
      return C.dim
    case "source_unavailable":
    case "error":
      return C.red
    default:
      return C.dim
  }
}

export function statusLabel(status: string | null | undefined): string {
  switch (status) {
    case "update_available":
      return "update available"
    case "up_to_date":
      return "up to date"
    case "no_source":
      return "no source"
    case "source_unavailable":
      return "source unreachable"
    case "error":
      return "check failed"
    case null:
    case undefined:
      return "not checked"
    default:
      return status.replace(/_/g, " ")
  }
}

export const LEVEL_COLOR: Record<string, string> = {
  ok: C.green,
  info: C.dim,
  warn: C.amber,
  error: C.red,
}

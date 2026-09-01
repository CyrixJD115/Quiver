// Design tokens. Terminal-native: no gaps between panels, dense borders.

export const C = {
  bg: "#11111b",
  panel: "#181825",
  panelAlt: "#1e1e2e",
  fg: "#cdd6f4",
  dim: "#6c7086",
  dimmer: "#45475a",
  accent: "#89b4fa",
  blue: "#89b4fa",
  teal: "#94e2d5",
  green: "#a6e3a1",
  yellow: "#f9e2af",
  red: "#f38ba8",
  mauve: "#cba6f7",
  peach: "#fab387",
  selected: "#313244",
  selectedAccent: "#1e3a5f",
  border: "#45475a",
  borderActive: "#89b4fa",
} as const

export const GLYPH = {
  ok: "✓",
  warn: "⚠",
  err: "✗",
  info: "•",
  arrow: "→",
  pointer: "❯",
  bullet: "·",
  dot: "●",
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

export const STATUS_COLORS: Record<string, string> = {
  ok: C.green,
  info: C.teal,
  warn: C.yellow,
  error: C.red,
  update_available: C.yellow,
  up_to_date: C.green,
  no_source: C.dim,
  source_unavailable: C.red,
  checked_error: C.red,
}

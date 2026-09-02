// Global reactive state (Solid signals) + the RPC session wiring.

import { createSignal } from "solid-js"
import { RpcClient, type LogEvent } from "./rpc"

export type ViewId = "apps" | "updates" | "health" | "activity" | "settings"

export interface AppRow {
  alias: string
  name: string
  version: string | null
  arch: string | null
  size: number | null
  integrated: number | boolean
  source_type: string | null
  source_repo: string | null
  update_status: string | null
  latest_version: string | null
  last_check_at: string | null
  icon_path: string | null
  autoupdate: string
  updated_at: string | null
  warnings?: string[]
}

export interface CoreInfo {
  version: string
  config_path: string
  state_dir: string
  storage_dir: string
  backup_dir: string
  icon_dir: string
  platform: string
}

export interface Toast {
  id: number
  level: "ok" | "warn" | "err" | "info"
  message: string
}

export interface Overlay {
  kind: "menu" | "help"
}

export interface ConfirmRequest {
  title: string
  detail?: string
  danger?: boolean
  action: () => Promise<void> | void
}

export const [connected, setConnected] = createSignal(false)
export const [fatalError, setFatalError] = createSignal<string | null>(null)
export const [coreInfo, setCoreInfo] = createSignal<CoreInfo | null>(null)
export const [apps, setApps] = createSignal<AppRow[]>([])
export const [health, setHealth] = createSignal<Record<string, unknown> | null>(null)
export const [logs, setLogs] = createSignal<LogEvent[]>([])
export const [busyText, setBusyText] = createSignal<string | null>(null)
export const [view, setView] = createSignal<ViewId>("apps")
export const [focusMode, setFocusMode] = createSignal<"nav" | "input">("nav")
export const [overlay, setOverlay] = createSignal<Overlay | null>(null)
export const [confirmReq, setConfirmReq] = createSignal<ConfirmRequest | null>(null)
export const [toasts, setToasts] = createSignal<Toast[]>([])
export const [selectedAlias, setSelectedAlias] = createSignal<string | null>(null)
export const [tick, setTick] = createSignal(0) // spinner clock

let rpc: RpcClient | null = null
let toastSeq = 1
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let spinnerTimer: ReturnType<typeof setInterval> | null = null

export function toast(level: Toast["level"], message: string): void {
  const id = toastSeq++
  setToasts((t) => [...t.slice(-2), { id, level, message }])
  setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000)
}

export function pushLog(level: string, message: string, alias?: string | null): void {
  const time = new Date().toISOString().slice(11, 19)
  setLogs((l) => [...l.slice(-499), { time, level, message, alias }])
}

export async function withBusy<T>(label: string, fn: () => Promise<T>): Promise<T | null> {
  setBusyText(label)
  try {
    return await fn()
  } catch (err) {
    const e = err as Error & { hint?: string }
    toast("err", e.hint ? `${e.message} — ${e.hint}` : e.message)
    pushLog("error", `${label}: ${e.message}`)
    return null
  } finally {
    setBusyText(null)
  }
}

export async function refreshApps(): Promise<void> {
  if (!rpc) return
  try {
    const rows = await rpc.call<AppRow[]>("apps.list")
    setApps(rows)
    const sel = selectedAlias()
    if (sel && !rows.some((r) => r.alias === sel)) {
      setSelectedAlias(rows[0]?.alias ?? null)
    } else if (!sel && rows.length) {
      setSelectedAlias(rows[0].alias)
    }
  } catch {
    /* transient backend hiccup; state notification will retry */
  }
}

export async function refreshCore(): Promise<void> {
  if (!rpc) return
  try {
    setCoreInfo(await rpc.call<CoreInfo>("core.info"))
  } catch {
    /* non-fatal */
  }
}

async function refreshHealth(): Promise<void> {
  if (!rpc) return
  try {
    setHealth(await rpc.call<Record<string, unknown>>("system.doctor"))
  } catch {
    /* non-fatal */
  }
}

function scheduleStateRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    void refreshApps()
    void refreshHealth()
  }, 150)
}

export function startSession(): void {
  rpc = RpcClient.fromEnv(
    (method, params) => {
      if (method === "log") {
        pushLog(
          String(params.level ?? "info"),
          String(params.message ?? ""),
          (params.alias as string | undefined) ?? null,
        )
      } else if (method === "state" && params.changed) {
        scheduleStateRefresh()
      }
    },
    (code) => {
      if (!fatalError()) {
        setFatalError(
          code === null
            ? "Could not start the quiver backend. Is `quiver` on PATH?"
            : `Backend exited (code ${code}).`,
        )
      }
      setConnected(false)
    },
  )
  rpc.start()
  void (async () => {
    await refreshCore()
    await refreshApps()
    await refreshHealth()
    setConnected(true)
    pushLog("info", "connected to backend")
  })()
}

export function getRpc(): RpcClient {
  if (!rpc) throw new Error("session not started")
  return rpc
}

export function endSession(): void {
  rpc?.dispose()
  rpc = null
  if (spinnerTimer) clearInterval(spinnerTimer)
}

export function startSpinner(): void {
  if (!spinnerTimer) spinnerTimer = setInterval(() => setTick((t) => t + 1), 120)
}

export const views: { id: ViewId; label: string; key: string }[] = [
  { id: "apps", label: "apps", key: "1" },
  { id: "updates", label: "updates", key: "2" },
  { id: "health", label: "health", key: "3" },
  { id: "activity", label: "activity", key: "4" },
  { id: "settings", label: "settings", key: "5" },
]

export function appsWithUpdates(): AppRow[] {
  return apps().filter((a) => a.update_status === "update_available")
}

export function doctorCounts(): { warn: number; error: number } {
  const h = health() as { warn?: number; error?: number } | null
  return { warn: h?.warn ?? 0, error: h?.error ?? 0 }
}

// Apps: master table + live detail pane. Filter with /, add with a.

import { createEffect, createResource, createSignal, onMount, Show } from "solid-js"
import {
  apps,
  selectedAlias,
  setFocusMode,
  setSelectedAlias,
  type AppRow,
} from "../state"
import { C, GLYPH, humanSize, pad, trunc } from "../theme"
import { onSubmitValue } from "../util"
import { Table, type Column } from "../components/Table"
import { confirm } from "../components/Overlays"
import { addApp, checkApp, detectSource, launchApp, removeApp, rollbackApp, updateApp } from "../actions"
import { registerController } from "./registry"

interface AppDetail extends AppRow {
  description: string | null
  homepage: string | null
  app_id: string | null
  path: string
  original_path: string | null
  desktop_file: string | null
  sha256: string | null
  history: { action: string; version: string | null; created_at: string }[]
  backups: { file: string; size: number; modified: string }[]
  last_check_result: Record<string, unknown> | null
}

const columns: Column[] = [
  { label: "alias", weight: 3, render: (r) => String(r.alias) },
  { label: "version", weight: 2, render: (r) => String(r.version ?? "?") },
  { label: "arch", weight: 1, render: (r) => String(r.arch ?? "?") },
  { label: "size", weight: 1, render: (r) => humanSize(r.size as number | null) },
  { label: "src", weight: 2, render: (r) => (r.source_type ? `${r.source_type}` : "-") },
  { label: "status", weight: 3, render: (r) => statusText(r as unknown as AppRow) },
  {
    label: "checked",
    weight: 2,
    render: (r) => (r.last_check_at ? String(r.last_check_at).slice(5, 10) : "never"),
  },
]

function statusText(a: AppRow): string {
  switch (a.update_status) {
    case "update_available":
      return `${GLYPH.arrow} ${a.latest_version ?? "?"}`
    case "up_to_date":
      return "ok"
    case "no_source":
      return "no src"
    case "source_unavailable":
      return "src down"
    case null:
      return "unknown"
    default:
      return String(a.update_status).replace(/_/g, " ")
  }
}

export function AppsView(): unknown {
  const [filter, setFilter] = createSignal("")
  const [filtering, setFiltering] = createSignal(false)
  const [cursor, setCursor] = createSignal(0)
  const [adding, setAdding] = createSignal(false)
  const [addPath, setAddPath] = createSignal("")

  const rows = (): AppRow[] => {
    const q = filter().toLowerCase()
    const list = q
      ? apps().filter(
          (a) => a.alias.toLowerCase().includes(q) || a.name.toLowerCase().includes(q),
        )
      : apps()
    return list
  }

  const [detail, { refetch }] = createResource(async () => {
    const alias = selectedAlias()
    if (!alias) return null
    try {
      const { getRpc } = await import("../state")
      return await getRpc().call<AppDetail>("apps.get", { alias })
    } catch {
      return null
    }
  })

  createEffect(() => {
    selectedAlias()
    void refetch()
  })

  const current = (): AppRow | undefined => {
    const list = rows()
    return list[Math.min(cursor(), list.length - 1)]
  }

  onMount(() => {
    registerController({
      id: "apps",
      move: (dir) => {
        const list = rows()
        if (!list.length) return
        setCursor((c) => Math.max(0, Math.min(list.length - 1, c + dir)))
        setSelectedAlias(current()?.alias ?? null)
      },
      jump: (first) => {
        const list = rows()
        if (!list.length) return
        setCursor(first ? 0 : list.length - 1)
        setSelectedAlias(current()?.alias ?? null)
      },
      primary: () => {
        const app = current()
        if (!app) return
        void launchApp(app.alias)
      },
      key: (name, shift) => {
        const app = current()
        switch (name) {
          case "l":
            if (app) void launchApp(app.alias)
            return true
          case "c":
            if (app) void checkApp(app.alias)
            return true
          case "u":
            if (app) void updateApp(app.alias)
            return true
          case "U":
            if (app) void updateApp(app.alias, true)
            return true
          case "b":
            if (app) void rollbackApp(app.alias)
            return true
          case "d":
            if (app) void detectSource(app.alias)
            return true
          case "x":
            if (app) {
              confirm(
                `Remove ${app.alias}?`,
                "Unregisters it and removes its desktop entry/icon.",
                () => void removeApp(app.alias, false),
              )
            }
            return true
          case "X":
            if (app) {
              confirm(
                `Remove ${app.alias} AND delete its file?`,
                humanSize(app.size ?? 0) + " — this cannot be undone.",
                () => void removeApp(app.alias, true),
              )
            }
            return true
          case "a":
            setAdding(true)
            setFocusMode("input")
            return true
          case "/":
            setFiltering(true)
            setFocusMode("input")
            return true
          default:
            return false
        }
      },
      hints: () => [
        "enter launch",
        "u update",
        "c check",
        "b rollback",
        "d detect",
        "x remove",
        "a add",
        "/ filter",
      ],
    })
  })

  const d = () => detail.latest

  return (
    <box width="100%" height="100%" flexDirection="row">
      <Show
        when={!adding()}
        fallback={
          <box flexGrow={1} borderStyle="single" borderColor={C.accent} padding={1} flexDirection="column">
            <text fg={C.accent}>ADD APPIMAGE</text>
            <box height={1} />
            <input
              placeholder="/path/to/App.AppImage"
              value={addPath()}
              onInput={setAddPath}
              onSubmit={onSubmitValue((value) => {
                if (value.trim()) {
                  setAdding(false)
                  setFocusMode("nav")
                  void addApp(value.trim())
                }
              })}
              focused={true}
              backgroundColor={C.panelAlt}
              textColor={C.fg}
            />
            <box height={1} />
            <text fg={C.dimmer}>enter add · esc cancel</text>
          </box>
        }
      >
        <box flexGrow={3} flexDirection="column" borderStyle="single" borderColor={C.border}>
          <box flexDirection="row" height={1} paddingX={1}>
            <text fg={C.accent}>APPS</text>
            <box flexGrow={1} />
            <text fg={filter() ? C.yellow : C.dimmer} wrapMode="none">
              {filter() ? `/${filter()}` : ""}
            </text>
          </box>
          <Show
            when={!filtering()}
            fallback={
              <box flexDirection="row" height={1} paddingX={1}>
                <text fg={C.yellow}>/</text>
                <input
                  placeholder="filter…"
                  value={filter()}
                  onInput={(v) => {
                    setFilter(v)
                    setCursor(0)
                  }}
                  onSubmit={onSubmitValue(() => {
                    setFiltering(false)
                    setFocusMode("nav")
                  })}
                  focused={true}
                  backgroundColor={C.panel}
                  textColor={C.fg}
                />
              </box>
            }
          >
            <box flexGrow={1} paddingX={1}>
              <Table
                columns={columns}
                rows={rows() as unknown as Record<string, unknown>[]}
                selected={Math.min(cursor(), Math.max(0, rows().length - 1))}
                emptyText="nothing managed — press a to add an AppImage"
              />
            </box>
          </Show>
        </box>
      </Show>

      <box flexGrow={2} flexDirection="column" borderStyle="single" borderColor={C.border} padding={1}>
        <Show
          when={d()}
          fallback={<text fg={C.dim}>select an app</text>}
        >
          {(detailBox) => (
            <>
              <text fg={C.blue} wrapMode="none">
                {detailBox().name}
              </text>
              <box flexDirection="row" height={1}>
                <text fg={C.dim} wrapMode="none">
                  {pad(detailBox().alias, 18)}
                </text>
                <text fg={C.fg} wrapMode="none">
                  {detailBox().version ?? "?"} · {detailBox().arch ?? "?"} ·{" "}
                  {humanSize(detailBox().size)}
                </text>
              </box>
              <text fg={C.dim} wrapMode="none">
                {trunc(detailBox().description ?? "", 48)}
              </text>
              <text fg={C.dimmer} wrapMode="none">
                {trunc(detailBox().homepage ?? detailBox().app_id ?? "", 48)}
              </text>
              <box height={1} />
              <text fg={C.dimmer} wrapMode="none">
                {trunc(detailBox().path, 48)}
              </text>
              <box flexDirection="row" height={1}>
                <box width={12}>
                  <text fg={C.dim}>sha256</text>
                </box>
                <text fg={C.dimmer} wrapMode="none">
                  {(detailBox().sha256 ?? "").slice(0, 32)}
                </text>
              </box>
              <box flexDirection="row" height={1}>
                <box width={12}>
                  <text fg={C.dim}>source</text>
                </box>
                <text fg={C.teal} wrapMode="none">
                  {detailBox().source_type
                    ? `${detailBox().source_type}:${detailBox().source_repo}`
                    : "not configured"}
                </text>
              </box>
              <box flexDirection="row" height={1}>
                <box width={12}>
                  <text fg={C.dim}>entry</text>
                </box>
                <text fg={C.fg} wrapMode="none">
                  {detailBox().integrated ? detailBox().desktop_file ?? "?" : "not integrated"}
                </text>
              </box>
              <box flexDirection="row" height={1}>
                <box width={12}>
                  <text fg={C.dim}>backups</text>
                </box>
                <text fg={C.fg}>{detailBox().backups.length}</text>
              </box>
              <box height={1} />
              <text fg={C.accent}>HISTORY</text>
              <Show when={detailBox().history.length} fallback={<text fg={C.dim}>no history</text>}>
                {detailBox()
                  .history.slice(0, 8)
                  .map((h) => (
                    <box flexDirection="row" height={1}>
                      <box width={20}>
                        <text fg={C.dim} wrapMode="none">
                          {h.created_at?.slice(0, 19)}
                        </text>
                      </box>
                      <box width={11}>
                        <text fg={C.teal} wrapMode="none">
                          {h.action}
                        </text>
                      </box>
                      <text fg={C.fg} wrapMode="none">
                        {h.version ?? ""}
                      </text>
                    </box>
                  ))}
              </Show>
            </>
          )}
        </Show>
      </box>
    </box>
  )
}

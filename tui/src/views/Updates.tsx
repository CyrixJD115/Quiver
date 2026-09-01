// Updates: check status per app, batch operations, live log tail.

import { createSignal, onMount } from "solid-js"
import { apps, logs, selectedAlias, setSelectedAlias } from "../state"
import { C, GLYPH } from "../theme"
import { Table, type Column } from "../components/Table"
import { checkAll, checkApp, rollbackApp, updateAll, updateApp } from "../actions"
import { registerController } from "./registry"

const columns: Column[] = [
  { label: "alias", weight: 3, render: (r) => String(r.alias) },
  {
    label: "current",
    weight: 2,
    render: (r) => String(r.version ?? "?"),
  },
  {
    label: "latest",
    weight: 2,
    render: (r) => String(r.latest_version ?? "—"),
    color: (r) => (r.update_status === "update_available" ? C.yellow : C.dim),
  },
  {
    label: "status",
    weight: 3,
    render: (r) => statusText(String(r.update_status ?? "unknown")),
    color: (r) =>
      r.update_status === "update_available"
        ? C.yellow
        : r.update_status === "up_to_date"
          ? C.green
          : r.update_status === "no_source"
            ? C.dim
            : C.red,
  },
  { label: "source", weight: 2, render: (r) => String(r.source_type ?? "-") },
]

function statusText(status: string): string {
  switch (status) {
    case "update_available":
      return "update available"
    case "up_to_date":
      return "up to date"
    case "no_source":
      return "no source"
    case "source_unavailable":
      return "source unreachable"
    case "checked_error":
      return "check failed"
    case "unknown":
      return "not checked yet"
    default:
      return status.replace(/_/g, " ")
  }
}

export function UpdatesView(): unknown {
  const [cursor, setCursor] = createSignal(0)
  const sorted = () =>
    apps().slice().sort((a, b) => {
      const rank = (s: string | null) => (s === "update_available" ? 0 : s ? 1 : 2)
      return rank(a.update_status) - rank(b.update_status)
    })

  const current = () => sorted()[Math.min(cursor(), sorted().length - 1)]

  onMount(() => {
    registerController({
      id: "updates",
      move: (dir) => {
        const list = sorted()
        if (!list.length) return
        setCursor((c) => Math.max(0, Math.min(list.length - 1, c + dir)))
        setSelectedAlias(current()?.alias ?? null)
      },
      jump: (first) => {
        const list = sorted()
        if (!list.length) return
        setCursor(first ? 0 : list.length - 1)
        setSelectedAlias(current()?.alias ?? null)
      },
      primary: () => {
        const app = current()
        if (app) void updateApp(app.alias)
      },
      key: (name) => {
        switch (name) {
          case "C":
            void checkAll()
            return true
          case "c":
            if (current()) void checkApp(current()!.alias)
            return true
          case "U":
            void updateAll()
            return true
          case "b":
            if (current()) void rollbackApp(current()!.alias)
            return true
          default:
            return false
        }
      },
      hints: () => ["enter update", "C check all", "U update all", "b rollback"],
    })
  })

  return (
    <box width="100%" height="100%" flexDirection="column">
      <box flexGrow={1} flexDirection="column" borderStyle="single" borderColor={C.border} paddingX={1}>
        <Table
          columns={columns}
          rows={sorted() as unknown as Record<string, unknown>[]}
          selected={Math.min(cursor(), Math.max(0, sorted().length - 1))}
          emptyText="no managed apps yet"
        />
      </box>
      <box height={8} flexDirection="column" borderStyle="single" borderColor={C.border}>
        <text fg={C.accent}> OPERATIONS LOG</text>
        {logs()
          .slice(-6)
          .map((l) => (
            <box height={1} paddingX={1}>
              <text
                fg={
                  l.level === "warn"
                    ? C.yellow
                    : l.level === "error"
                      ? C.red
                      : l.level === "ok"
                        ? C.green
                        : C.dim
                }
                wrapMode="none"
              >
                {`${GLYPH.info} ${l.message}`.slice(0, 100)}
              </text>
            </box>
          ))}
      </box>
    </box>
  )
}

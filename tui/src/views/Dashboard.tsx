// Dashboard: system overview, recent history, quick actions.

import { createMemo, createResource, For, onMount } from "solid-js"
import { getRpc, apps, appsWithUpdates, coreInfo, doctorCounts, selectedAlias, setView } from "../state"
import { C, GLYPH, humanSize, pad } from "../theme"
import { registerController } from "./registry"

interface HistoryEntry {
  alias: string
  action: string
  version: string | null
  created_at: string
}

function statusGlyph(status: string | null): [string, string] {
  switch (status) {
    case "update_available":
      return ["↑", C.yellow]
    case "up_to_date":
      return [GLYPH.ok, C.green]
    case "no_source":
      return ["?", C.dim]
    case null:
      return ["·", C.dim]
    default:
      return [GLYPH.err, C.red]
  }
}

export function DashboardView(): unknown {
  const [history] = createResource(async () => {
    try {
      return await getRpc().call<HistoryEntry[]>("history.recent", { limit: 6 })
    } catch {
      return [] as HistoryEntry[]
    }
  })

  onMount(() => {
    registerController({
      id: "dashboard",
      move: () => setView("apps"),
      jump: () => setView("apps"),
      primary: () => setView("apps"),
      key: () => false,
      hints: () => ["2 apps", "3 updates", ": palette", "? help"],
    })
  })

  const rows = createMemo(apps)
  const updates = createMemo(appsWithUpdates)
  const counts = createMemo(doctorCounts)
  const totalSize = createMemo(() => rows().reduce((acc, a) => acc + (a.size ?? 0), 0))

  return (
    <box width="100%" height="100%" flexDirection="row">
      <box flexGrow={1} flexDirection="column" borderStyle="single" borderColor={C.border}>
        <text fg={C.accent}> OVERVIEW</text>
        <box height={1} />
        <box flexDirection="row" height={1}>
          <box width={22}>
            <text fg={C.dim}>managed apps</text>
          </box>
          <text fg={C.fg}>{rows().length}</text>
        </box>
        <box flexDirection="row" height={1}>
          <box width={22}>
            <text fg={C.dim}>updates available</text>
          </box>
          <text fg={updates().length ? C.yellow : C.green}>{updates().length}</text>
        </box>
        <box flexDirection="row" height={1}>
          <box width={22}>
            <text fg={C.dim}>desktop integrated</text>
          </box>
          <text fg={C.fg}>{rows().filter((a) => a.integrated).length}</text>
        </box>
        <box flexDirection="row" height={1}>
          <box width={22}>
            <text fg={C.dim}>sources configured</text>
          </box>
          <text fg={C.fg}>{rows().filter((a) => a.source_type).length}</text>
        </box>
        <box flexDirection="row" height={1}>
          <box width={22}>
            <text fg={C.dim}>health</text>
          </box>
          <text fg={counts().error ? C.red : counts().warn ? C.yellow : C.green}>
            {counts().error} error · {counts().warn} warn
          </text>
        </box>
        <box flexDirection="row" height={1}>
          <box width={22}>
            <text fg={C.dim}>storage used</text>
          </box>
          <text fg={C.fg}>{humanSize(totalSize())}</text>
        </box>
        <box height={1} />
        <text fg={C.dim}> {coreInfo()?.storage_dir ?? ""}</text>
        <box flexGrow={1} />
        <text fg={C.dimmer}> enter: open Apps · 3: updates · 4: health</text>
      </box>

      <box flexGrow={2} flexDirection="column" borderStyle="single" borderColor={C.border}>
        <text fg={C.accent}> APPS</text>
        <For each={rows().slice(0, 12)}>
          {(a) => {
            const [glyph, color] = statusGlyph(a.update_status)
            return (
              <box flexDirection="row" height={1}>
                <box width={16}>
                  <text fg={C.blue} wrapMode="none">
                    {a.alias}
                  </text>
                </box>
                <box width={14}>
                  <text fg={C.fg} wrapMode="none">
                    {pad(a.version ?? "?", 14)}
                  </text>
                </box>
                <box width={10}>
                  <text fg={color}>{glyph} </text>
                  <text fg={C.dim} wrapMode="none">
                    {a.source_type ?? "-"}
                  </text>
                </box>
                <text fg={C.dimmer} wrapMode="none">
                  {a.source_repo ?? ""}
                </text>
              </box>
            )
          }}
        </For>
        <box flexGrow={1} />
        <text fg={C.accent}> RECENT ACTIVITY (selected)</text>
        <For each={(history.latest ?? []).slice(0, 5)}>
          {(h) => (
            <box flexDirection="row" height={1}>
              <box width={20}>
                <text fg={C.dim} wrapMode="none">
                  {h.created_at?.slice(0, 19)}
                </text>
              </box>
              <box width={12}>
                <text fg={C.teal} wrapMode="none">
                  {h.action}
                </text>
              </box>
              <text fg={C.fg} wrapMode="none">
                {h.version ?? ""}
              </text>
            </box>
          )}
        </For>
      </box>
    </box>
  )
}

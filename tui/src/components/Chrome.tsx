// App chrome: header bar, sidebar navigation, status bar.

import { createMemo, For } from "solid-js"
import { getController } from "../views/registry"
import {
  apps,
  appsWithUpdates,
  busyText,
  connected,
  coreInfo,
  doctorCounts,
  focusMode,
  overlay,
  selectedAlias,
  tick,
  view,
  views,
} from "../state"
import { C, GLYPH } from "../theme"

const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

export function Header(): unknown {
  const info = createMemo(coreInfo)
  const updates = createMemo(() => appsWithUpdates().length)
  const counts = createMemo(doctorCounts)
  return (
    <box width="100%" height={1} backgroundColor={C.panelAlt} flexDirection="row" paddingX={1}>
      <text fg={C.accent} wrapMode="none">
        ⚡ QUIVER
      </text>
      <text fg={C.dimmer}> {info() ? `v${info()!.version}` : ""} </text>
      <box flexGrow={1} />
      <text fg={updates() ? C.yellow : C.dim} wrapMode="none">
        {apps().length} apps{updates() ? ` · ${updates()} update${updates() > 1 ? "s" : ""}` : ""}
        {counts().error ? ` · ${counts().error} error${counts().error > 1 ? "s" : ""}` : ""}
        {counts().warn && !counts().error ? ` · ${counts().warn} warn` : ""}
      </text>
    </box>
  )
}

export function Sidebar(): unknown {
  const updates = createMemo(() => appsWithUpdates().length)
  const counts = createMemo(doctorCounts)
  return (
    <box
      width={20}
      height="100%"
      flexDirection="column"
      borderStyle="single"
      borderColor={C.border}
      backgroundColor={C.panel}
    >
      <For each={views}>
        {(v) => {
          const active = v.id === view()
          const badge =
            v.id === "updates" && updates()
              ? updates().toString()
              : v.id === "health" && counts().error + counts().warn
                ? (counts().error + counts().warn).toString()
                : ""
          return (
            <box flexDirection="row" height={1} backgroundColor={active ? C.selectedAccent : undefined}>
              <text fg={active ? C.accent : C.dimmer}> {v.key} </text>
              <text fg={active ? C.fg : C.dim} wrapMode="none">
                {v.label}
              </text>
              <box flexGrow={1} />
              {badge ? <text fg={v.id === "updates" ? C.yellow : C.red}>{badge} </text> : null}
            </box>
          )
        }}
      </For>
      <box height={1} />
      <box flexDirection="row" height={1}>
        <text fg={C.dimmer}> {GLYPH.pointer} </text>
        <text fg={C.dim} wrapMode="none">
          {selectedAlias() ? selectedAlias()!.slice(0, 14) : "—"}
        </text>
      </box>
      <box flexGrow={1} />
      <box height={1} paddingX={1}>
        <text fg={C.dimmer} wrapMode="none">
          {focusMode() === "input" ? "TEXT INPUT" : connected() ? "backend ok" : "no backend"}
        </text>
      </box>
    </box>
  )
}

export function StatusBar(): unknown {
  return (
    <box width="100%" height={1} backgroundColor={C.panelAlt} flexDirection="row" paddingX={1}>
      <text fg={C.dim} wrapMode="none">
        {statusHints().join("   ")}
      </text>
      <box flexGrow={1} />
      {busyText() ? (
        <text fg={C.accent} wrapMode="none">
          {SPINNER[tick() % SPINNER.length]} {busyText()}
        </text>
      ) : (
        <text fg={connected() ? C.green : C.red} wrapMode="none">
          {connected() ? "ready" : "disconnected"}
        </text>
      )}
      {overlay() ? <text fg={C.mauve}> esc</text> : null}
    </box>
  )
}

function statusHints(): string[] {
  return getController(view())?.hints() ?? [": palette", "? help"]
}

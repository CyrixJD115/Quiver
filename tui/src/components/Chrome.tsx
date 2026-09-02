// App chrome: title bar with view tabs (top) and contextual status bar
// (bottom). Everything is clickable; five tabs carry the whole hierarchy.

import { createMemo, createSignal, For } from "solid-js"
import {
  appsWithUpdates,
  busyText,
  connected,
  coreInfo,
  doctorCounts,
  overlay,
  setView,
  tick,
  view,
  views,
} from "../state"
import { C } from "../theme"
import { getController, type ViewHint } from "../views/registry"
import { Clickable, Hint, Span } from "./ui"

const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

export function TitleBar(): unknown {
  const updates = createMemo(() => appsWithUpdates().length)
  const problems = createMemo(() => {
    const c = doctorCounts()
    return c.error + c.warn
  })
  return (
    <box width="100%" height={1} backgroundColor={C.panel} flexDirection="row" alignItems="center">
      <box width={1} />
      <text fg={C.green}>quiver</text>
      <text fg={C.dimmer}> {coreInfo() ? `v${coreInfo()!.version}` : ""} </text>
      <For each={views}>
        {(v) => {
          const badge = () =>
            v.id === "updates" && updates()
              ? ` ${updates()}`
              : v.id === "health" && problems()
                ? ` ${problems()}`
                : ""
          return <TabButton active={v.id === view()} label={`${v.key} ${v.label}${badge()}`} id={v.id} />
        }}
      </For>
      <box flexGrow={1} />
      {updates() ? (
        <text fg={C.amber}>↑{updates()} update{updates() > 1 ? "s" : ""} </text>
      ) : null}
      {busyText() ? (
        <text fg={C.green}>{SPINNER[tick() % SPINNER.length]} {busyText()}</text>
      ) : (
        <text fg={connected() ? C.dimmer : C.red}>{connected() ? "connected" : "offline"}</text>
      )}
      <box width={1} />
    </box>
  )
}

function TabButton(props: { active: boolean; label: string; id: string }): unknown {
  const [hover, setHover] = createSignal(false)
  return (
    <Clickable onClick={() => setView(props.id as never)}>
      <box
        onMouseOver={() => setHover(true)}
        onMouseOut={() => setHover(false)}
        height={1}
        backgroundColor={props.active ? C.greenDeep : hover() ? C.hover : undefined}
        alignItems="center"
      >
        <text>
          <Span fg={props.active ? C.greenBright : C.border}>▎</Span>
          <Span fg={props.active ? C.green : hover() ? C.fg : C.dim}>{props.label} </Span>
        </text>
      </box>
    </Clickable>
  )
}

export function StatusBar(props: { onMenu: () => void; onHelp: () => void; onQuit: () => void }): unknown {
  const hints = createMemo(() => getController(view())?.hints() ?? [])
  const cycle = () => {
    const idx = views.findIndex((v) => v.id === view())
    setView(views[(idx + 1) % views.length].id)
  }
  return (
    <box width="100%" height={1} backgroundColor={C.panel} flexDirection="row" alignItems="center">
      <box width={1} />
      <Hint key="tab" label="views" onClick={cycle} />
      <For each={hints()}>{(h) => <Hint key={h.key} label={h.label} onClick={h.run} />}</For>
      <Hint key=":" label="menu" onClick={props.onMenu} />
      <Hint key="?" label="help" onClick={props.onHelp} />
      <box flexGrow={1} />
      {overlay() ? <text fg={C.dimmer}>esc back  </text> : null}
      <Hint key="q" label="quit" onClick={props.onQuit} />
      <box width={1} />
    </box>
  )
}

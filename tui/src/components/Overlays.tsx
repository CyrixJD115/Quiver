// Overlays: command palette, help sheet, confirm dialog, toasts.
// Rendered absolutely over the main area; only one overlay is active at a time.

import { createSignal, For } from "solid-js"
import { C } from "../theme"
import { onSubmitValue } from "../util"
import {
  confirmReq,
  setConfirmReq,
  setFocusMode,
  setOverlay,
  toasts as toastsSignal,
  view,
} from "../state"

export interface Command {
  id: string
  label: string
  detail?: string
  run: () => void
}

const PALETTE_KEYS: Record<string, string> = {
  "1": "dashboard",
  "2": "apps",
  "3": "updates",
  "4": "health",
  "5": "activity",
  "6": "settings",
}

export function Palette(props: { commands: Command[] }): unknown {
  const [query, setQuery] = createSignal("")
  const [index, setIndex] = createSignal(0)
  const filtered = () => {
    const q = query().toLowerCase()
    const list = q
      ? props.commands.filter(
          (c) => c.label.toLowerCase().includes(q) || (c.detail ?? "").toLowerCase().includes(q),
        )
      : props.commands
    return list
  }
  // jump to the target view as the user types a digit
  const onInput = (value: string) => {
    setQuery(value)
    setIndex(0)
    if (PALETTE_KEYS[value]) {
      const target = filtered().find((c) => c.id === `go:${PALETTE_KEYS[value]}`)
      if (target) {
        close()
        target.run()
      }
    }
  }
  const close = () => {
    setOverlay(null)
    setFocusMode("nav")
  }
  const submit = onSubmitValue((value: string) => {
    const list = filtered()
    if (value === "" && list.length) {
      close()
      list[0].run()
      return
    }
    const chosen = list[Math.min(index(), list.length - 1)]
    if (chosen) {
      close()
      chosen.run()
    }
  })
  return (
    <box
      position="absolute"
      top={1}
      left={8}
      right={8}
      flexDirection="column"
      borderStyle="single"
      borderColor={C.accent}
      backgroundColor={C.panel}
      maxHeight="70%"
    >
      <input
        placeholder="Run a command…"
        value={query()}
        onInput={onInput}
        onSubmit={submit}
        focused={true}
        backgroundColor={C.panelAlt}
        textColor={C.fg}
      />
      <box flexDirection="column" maxHeight="60%" overflow="hidden">
        <For each={filtered().slice(0, 12)}>
          {(cmd, i) => (
            <box flexDirection="row" height={1} backgroundColor={i() === index() ? C.selectedAccent : undefined}>
              <text fg={i() === index() ? C.accent : C.dim}> {i() === index() ? "❯" : " "} </text>
              <text fg={i() === index() ? C.fg : C.fg} wrapMode="none">
                {cmd.label}
              </text>
              <box flexGrow={1} />
              <text fg={C.dimmer} wrapMode="none">
                {truncRight(cmd.detail ?? "")}
              </text>
            </box>
          )}
        </For>
      </box>
      <box height={1} paddingX={1}>
        <text fg={C.dimmer}>enter run · up/down choose · esc close</text>
      </box>
    </box>
  )
}

function truncRight(s: string): string {
  return s.length > 34 ? s.slice(0, 33) + "…" : s
}

export function HelpSheet(): unknown {
  const rows: [string, string][] = [
    ["1 … 6", "switch view (dashboard … settings)"],
    ["tab", "next view"],
    ["j / k  ↑ / ↓", "move selection"],
    ["g / G", "jump to first / last row"],
    ["enter", "open / primary action"],
    ["/", "filter rows (Apps)"],
    [":", "command palette"],
    ["?", "this help"],
    ["r", "refresh data from the backend"],
    ["a", "add an AppImage (Apps view)"],
    ["l", "launch selected app"],
    ["c / C", "check selected / check all"],
    ["u / U", "update selected / update all"],
    ["b", "rollback selected app"],
    ["d", "detect update source"],
    ["x", "remove selected app"],
    ["e", "refresh metadata (self-updated apps)"],
    ["f", "fix integrations"],
    ["n", "clean leftovers"],
    ["i", "import found AppImages"],
    ["s", "scan system"],
    ["q", "quit"],
  ]
  return (
    <box
      position="absolute"
      top={2}
      left={10}
      right={10}
      borderStyle="single"
      borderColor={C.mauve}
      backgroundColor={C.panel}
      padding={1}
      flexDirection="column"
    >
      <text fg={C.mauve}>KEYBOARD</text>
      <box height={1} />
      <For each={rows}>
        {(row) => (
          <box flexDirection="row" height={1}>
            <box width={16}>
              <text fg={C.accent} wrapMode="none">
                {row[0]}
              </text>
            </box>
            <text fg={C.fg} wrapMode="none">
              {row[1]}
            </text>
          </box>
        )}
      </For>
      <box height={1} />
      <text fg={C.dimmer}>view: {view()} — press q, esc or ? to close</text>
    </box>
  )
}

export function ConfirmBox(): unknown {
  const req = confirmReq()
  if (!req) return null
  const accept = () => {
    setConfirmReq(null)
    void req.action()
  }
  const cancel = () => setConfirmReq(null)
  return (
    <box
      position="absolute"
      top={4}
      left={14}
      right={14}
      borderStyle="single"
      borderColor={C.yellow}
      backgroundColor={C.panel}
      padding={1}
      flexDirection="column"
    >
      <text fg={C.yellow} wrapMode="none">
        {req.title}
      </text>
      {req.detail ? (
        <box height={1}>
          <text fg={C.dim} wrapMode="none">
            {req.detail}
          </text>
        </box>
      ) : null}
      <box height={1} />
      <text fg={C.dim}>y confirm · esc cancel</text>
    </box>
  )
}

export function confirm(title: string, detail: string | undefined, action: () => void): void {
  setConfirmReq({ title, detail, action })
}

const TOAST_COLOR: Record<string, string> = {
  ok: C.green,
  warn: C.yellow,
  err: C.red,
  info: C.teal,
}

export function Toasts(): unknown {
  const toasts = toastsSignal
  return (
    <box position="absolute" bottom={2} right={2} flexDirection="column">
      <For each={toasts().slice(-3)}>
        {(t) => (
          <box borderStyle="single" borderColor={TOAST_COLOR[t.level]} backgroundColor={C.panel} paddingX={1}>
            <text fg={TOAST_COLOR[t.level]} wrapMode="none">
              {t.message.slice(0, 60)}
            </text>
          </box>
        )}
      </For>
    </box>
  )
}


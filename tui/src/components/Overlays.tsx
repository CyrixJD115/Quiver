// Dialogs: the command menu (OpenCode-style, filter + sections + mouse),
// help sheet, confirm dialog and toasts. One dialog open at a time.

import { createMemo, createSignal, For } from "solid-js"
import { useTerminalDimensions } from "@opentui/solid"
import type { InputRenderable } from "@opentui/core"
import { C, LEVEL_COLOR } from "../theme"
import { confirmReq, setConfirmReq, setFocusMode, setOverlay, toasts } from "../state"
import { Button, Dialog, Span } from "./ui"
import { onSubmitValue } from "../util"

export interface Command {
  id: string
  section: string
  label: string
  detail?: string
  key?: string
  danger?: boolean
  run: () => void
}

export function CommandMenu(props: { commands: Command[] }): unknown {
  const [query, setQuery] = createSignal("")
  const [cursor, setCursor] = createSignal(0)
  // The key that opened this menu can leak into the freshly focused input
  // within the same event dispatch - ignore input until the next tick, then
  // clear whatever leaked into the renderable.
  const [armed, setArmed] = createSignal(false)
  let inputRef: InputRenderable | undefined
  setTimeout(() => {
    setArmed(true)
    if (inputRef) inputRef.value = ""
  }, 30)

  type Entry = { kind: "header"; text: string } | { kind: "cmd"; cmd: Command }

  // One flat column of fixed-height rows: header rows interleaved with
  // command rows. No nested auto-height sections to miscompute.
  const entries = createMemo<Entry[]>(() => {
    const q = query().trim().toLowerCase()
    const match = (c: Command) =>
      !q ||
      c.label.toLowerCase().includes(q) ||
      c.section.toLowerCase().includes(q) ||
      (c.detail ?? "").toLowerCase().includes(q)
    const out: Entry[] = []
    let section = ""
    let rowsThisSection = 0
    for (const cmd of props.commands.filter(match)) {
      if (cmd.section !== section) {
        section = cmd.section
        rowsThisSection = 0
        out.push({ kind: "header", text: section.toUpperCase() })
      }
      if (rowsThisSection >= 5) continue
      rowsThisSection++
      out.push({ kind: "cmd", cmd })
      if (out.length > 14) break
    }
    return out.slice(0, 15)
  })

  const flat = createMemo(() =>
    entries().flatMap((e) => (e.kind === "cmd" ? [e.cmd] : [])),
  )

  const close = () => {
    setOverlay(null)
    setFocusMode("nav")
  }
  const run = (cmd: Command | undefined) => {
    if (!cmd) return
    close()
    cmd.run()
  }

  return (
    <Dialog title=" menu " width={60}>
      <box height={1} paddingX={1} backgroundColor={C.bg}>
        <input
          ref={inputRef}
          placeholder="Type to filter commands…"
          onInput={(v: string) => {
            if (!armed()) return
            setQuery(v)
            setCursor(0)
          }}
          onSubmit={onSubmitValue(() => run(flat()[cursor()]))}
          focused={true}
          backgroundColor={C.bg}
          textColor={C.fg}
        />
      </box>
      {/* Fixed height keeps every cell position stable while filtering;
          shrinking lists leave stale cells in the diff otherwise. */}
      <box flexDirection="column" height={16} overflow="hidden">
        <For each={entries()}>
          {(entry) =>
            entry.kind === "header" ? (
              <box height={1} paddingX={1} backgroundColor={C.bg}>
                <text fg={C.dimmer}>{entry.text}</text>
              </box>
            ) : (
              <MenuRow
                cmd={entry.cmd}
                active={flat().indexOf(entry.cmd) === cursor()}
                onSelect={() => run(entry.kind === "cmd" ? entry.cmd : undefined)}
                onHover={() => {
                  if (entry.kind === "cmd") setCursor(flat().indexOf(entry.cmd))
                }}
              />
            )
          }
        </For>
      </box>
      <box height={1} paddingX={1}>
        <text fg={C.dimmer}>enter run · j/k choose · esc close</text>
      </box>
    </Dialog>
  )
}

function MenuRow(props: { cmd: Command; active: boolean; onSelect: () => void; onHover: () => void }): unknown {
  const label = props.cmd.label
  const keyHint = props.cmd.key
  const danger = props.cmd.danger
  const [hover, setHover] = createSignal(false)
  return (
    <box
      flexDirection="row"
      height={1}
      paddingX={1}
      backgroundColor={props.active ? C.greenDeep : hover() ? C.hover : undefined}
      onMouseOver={() => {
        setHover(true)
        props.onHover()
      }}
      onMouseOut={() => setHover(false)}
      onMouseDown={(e: { button: number }) => {
        if (e.button === 0) props.onSelect()
      }}
    >
      <text>
        <Span fg={props.active ? C.greenBright : C.border}>▎</Span>
        <Span fg={danger ? C.red : props.active ? C.fg : C.dim}> {label}</Span>
      </text>
      <box flexGrow={1} />
      {keyHint ? <text fg={C.dimmer}>[{keyHint}] </text> : null}
      {props.cmd.detail ? <text fg={C.dimmer}>{props.cmd.detail}</text> : null}
    </box>
  )
}

export function HelpDialog(): unknown {
  const rows: [string, string][] = [
    ["tab / 1-5", "switch view (click the tabs too)"],
    ["j / k  ↑ ↓  wheel", "move selection"],
    ["g / G", "first / last row"],
    ["enter", "open · launch · run (contextual)"],
    ["/", "filter the current list"],
    [":", "command menu — every action lives here"],
    ["?", "this help"],
    ["esc", "close dialog · leave filter"],
    ["q", "quit"],
    ["", ""],
    ["mouse", "click rows, tabs, buttons and hints; wheel scrolls"],
  ]
  return (
    <Dialog title=" help " width={58}>
      <box padding={1} flexDirection="column">
        <For each={rows}>
          {(row) => (
            <box flexDirection="row" height={1}>
              <box width={20}>
                <text fg={C.green} wrapMode="none">
                  {row[0]}
                </text>
              </box>
              <text fg={C.fg} wrapMode="none">
                {row[1]}
              </text>
            </box>
          )}
        </For>
      </box>
    </Dialog>
  )
}

export function ConfirmDialog(): unknown {
  const req = confirmReq()
  if (!req) return null
  const accept = () => {
    setConfirmReq(null)
    void req.action()
  }
  const cancel = () => setConfirmReq(null)
  return (
    <Dialog title=" confirm " width={54}>
      <box padding={1} flexDirection="column">
        <text fg={C.fg} wrapMode="none">
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
        <box flexDirection="row">
          <Button label="confirm" danger={req.danger ?? false} onClick={accept} />
          <box width={2} />
          <Button label="cancel" onClick={cancel} />
        </box>
      </box>
    </Dialog>
  )
}


export function confirm(title: string, detail: string | undefined, action: () => void, danger = false): void {
  setConfirmReq({ title, detail, action, danger })
}

export function Toasts(): unknown {
  return (
    <box position="absolute" bottom={2} right={2} flexDirection="column">
      <For each={toasts().slice(-3)}>
        {(t) => (
          <box borderStyle="rounded" borderColor={LEVEL_COLOR[t.level] ?? C.dim} backgroundColor={C.panel} paddingX={1}>
            <text fg={LEVEL_COLOR[t.level] ?? C.fg} wrapMode="none">
              {t.message.slice(0, 64)}
            </text>
          </box>
        )}
      </For>
    </box>
  )
}

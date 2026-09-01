// Dense terminal table: fixed header, selectable rows, no inter-panel gaps.
// Columns get proportional widths so the table scales with the terminal.

import { C } from "../theme"
import { For } from "solid-js"

export interface Column {
  label: string
  weight: number // relative width share
  render?: (row: Record<string, unknown>) => string
  color?: (row: Record<string, unknown>) => string | undefined
}

export function Table(props: {
  columns: Column[]
  rows: Record<string, unknown>[]
  selected: number
  emptyText?: string
}): unknown {
  const total = () => props.columns.reduce((a, c) => a + c.weight, 0) || 1
  const pct = (w: number) => `${Math.floor((w / total()) * 100)}%` as `${number}%`
  const cell = (text: string) => (text.length ? " " + text : "")

  return (
    <box flexDirection="column" width="100%" height="100%">
      <box flexDirection="row" width="100%" height={1} backgroundColor={C.panelAlt}>
        <box width={2} />
        <For each={props.columns}>
          {(col) => (
            <box width={pct(col.weight)} minWidth={0} flexShrink={1}>
              <text fg={C.dim} wrapMode="none">
                {cell(col.label.toUpperCase())}
              </text>
            </box>
          )}
        </For>
      </box>
      {props.rows.length === 0 && props.emptyText ? (
        <box paddingX={1} flexGrow={1}>
          <text fg={C.dim}>{props.emptyText}</text>
        </box>
      ) : (
        <For each={props.rows}>
          {(row, i) => {
            const active = () => i() === props.selected
            return (
              <box
                flexDirection="row"
                width="100%"
                height={1}
                backgroundColor={active() ? C.selectedAccent : undefined}
              >
                <box width={2}>
                  <text fg={active() ? C.accent : C.dimmer}>{active() ? "❯" : " "}</text>
                </box>
                <For each={props.columns}>
                  {(col) => (
                    <box width={pct(col.weight)} minWidth={0} flexShrink={1}>
                      <text
                        fg={active() ? C.fg : (col.color?.(row) ?? C.fg)}
                        wrapMode="none"
                      >
                        {cell(col.render ? col.render(row) : String(row[col.label] ?? ""))}
                      </text>
                    </box>
                  )}
                </For>
              </box>
            )
          }}
        </For>
      )}
    </box>
  )
}

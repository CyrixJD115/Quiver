// Updates: statuses sorted available-first, action buttons up top, live log
// tail at the bottom. Same interaction model as Apps: click, hover, j/k.

import { createSignal, onMount, Show } from "solid-js"
import { apps, logs, selectedAlias, setSelectedAlias, type AppRow } from "../state"
import { C, GLYPH, humanSize, statusColor, statusLabel, LEVEL_COLOR } from "../theme"
import { Button, EmptyState, Span } from "../components/ui"
import { confirm } from "../components/Overlays"
import { checkAll, checkApp, rollbackApp, updateAll, updateApp } from "../actions"
import { registerController } from "./registry"

export function UpdatesView(): unknown {
  const [cursor, setCursor] = createSignal(0)

  const sorted = (): AppRow[] =>
    apps()
      .slice()
      .sort((a, b) => {
        const rank = (s: string | null) =>
          s === "update_available" ? 0 : s === null ? 2 : s === "up_to_date" ? 1 : 3
        return rank(a.update_status) - rank(b.update_status)
      })

  const current = () => sorted()[cursor()]
  const select = (i: number) => {
    const list = sorted()
    if (!list.length) return
    const clamped = Math.max(0, Math.min(list.length - 1, i))
    setCursor(clamped)
    setSelectedAlias(list[clamped]?.alias ?? null)
  }

  onMount(() => {
    registerController({
      id: "updates",
      move: (dir, steps = 1) => select(cursor() + dir * steps),
      jump: (first) => select(first ? 0 : sorted().length - 1),
      primary: () => {
        const app = current()
        if (app) void updateApp(app.alias)
      },
      hints: () => [
        { key: "enter", label: "update", run: () => current() && void updateApp(current()!.alias) },
      ],
    })
  })

  return (
    <box width="100%" height="100%" flexDirection="column">
      <box flexGrow={1} flexDirection="column" borderStyle="single" borderColor={C.border}>
        <box height={1} paddingX={1}>
          <text fg={C.dimmer}>UPDATES</text>
        </box>
        <Show
          when={sorted().length}
          fallback={<EmptyState glyph="◇" title="no managed apps yet" hint="add some in the apps view" />}
        >
          {sorted().map((app, i) => (
            <UpdateRow
              app={app}
              active={i === cursor()}
              onSelect={() => select(i)}
              onOpen={() => void updateApp(app.alias)}
            />
          ))}
        </Show>
      </box>
      <box height={3} flexDirection="row" borderStyle="single" borderColor={C.border} alignItems="center" paddingX={1}>
        <Button label="Check all" onClick={() => void checkAll()} />
        <box width={1} />
        <Button
          label="Update all"
          onClick={() =>
            confirm("Update every app with a source?", "Each update is verified and backed up first.", () =>
              void updateAll(),
            )
          }
        />
        <box flexGrow={1} />
        <text fg={C.dimmer}>
          {current() ? `enter updates ${current()!.alias}` : ""}
        </text>
      </box>
      <box height={7} flexDirection="column" borderStyle="single" borderColor={C.border}>
        <box height={1} paddingX={1}>
          <text fg={C.dimmer}>OPERATIONS</text>
        </box>
        {logs()
          .slice(-5)
          .map((l) => (
            <box height={1} paddingX={1}>
              <text fg={LEVEL_COLOR[l.level] ?? C.dim} wrapMode="none">
                {`${GLYPH.info} ${l.message}`.slice(0, 100)}
              </text>
            </box>
          ))}
      </box>
    </box>
  )
}

function UpdateRow(props: { app: AppRow; active: boolean; onSelect: () => void; onOpen: () => void }): unknown {
  const [hover, setHover] = createSignal(false)
  return (
    <box
      flexDirection="row"
      height={1}
      onMouseOver={() => setHover(true)}
      onMouseOut={() => setHover(false)}
      onMouseDown={(e: { button: number }) => {
        if (e.button === 0) {
          props.onSelect()
          if (props.active) props.onOpen()
        }
      }}
      backgroundColor={props.active ? C.greenDeep : hover() ? C.hover : undefined}
    >
      <text>
        <Span fg={props.active ? C.greenBright : C.border}>▎</Span>
        <Span fg={props.active ? C.green : C.dimmer}> {props.app.alias.slice(0, 15).padEnd(16)}</Span>
        <Span fg={C.dim}>{truncPad(props.app.version ?? "?", 13)}</Span>
        <Span fg={C.dim}>{truncPad(props.app.latest_version ?? "—", 13)}</Span>
        <Span fg={statusColor(props.app.update_status)}>
          {statusLabel(props.app.update_status).slice(0, 18)}
        </Span>
      </text>
    </box>
  )
}

function truncPad(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s.padEnd(n)
}

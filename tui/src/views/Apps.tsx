// Apps: the hub. List on the left (click/hover/keyboard), detail + action
// buttons on the right. Every action is a visible button or a menu entry -
// no hidden letter keys.

import { createEffect, createResource, createSignal, onMount, Show } from "solid-js"
import { apps, selectedAlias, setFocusMode, setSelectedAlias, type AppRow } from "../state"
import { C, GLYPH, humanSize, statusColor, statusLabel, trunc } from "../theme"
import { useTerminalDimensions } from "@opentui/solid"
import { Button, EmptyState, Span } from "../components/ui"
import { confirm } from "../components/Overlays"
import {
  addApp,
  checkApp,
  detectSource,
  launchApp,
  refreshMetadata,
  removeApp,
  rollbackApp,
  updateApp,
} from "../actions"
import { registerController } from "./registry"

interface AppDetail extends AppRow {
  description: string | null
  homepage: string | null
  app_id: string | null
  path: string
  desktop_file: string | null
  sha256: string | null
  history: { action: string; version: string | null; created_at: string }[]
  backups: { file: string; size: number }[]
}

// module-level state so the menu's "Add AppImage…" can open the form
const [adding, setAdding] = createSignal(false)
export function promptAddApp(): void {
  setAdding(true)
}

export function AppsView(): unknown {
  const [cursor, setCursor] = createSignal(0)

  const rows = (): AppRow[] => apps()

  const current = (): AppRow | undefined => rows()[cursor()]

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

  const select = (i: number) => {
    const list = rows()
    if (!list.length) return
    const clamped = Math.max(0, Math.min(list.length - 1, i))
    setCursor(clamped)
    setSelectedAlias(list[clamped]?.alias ?? null)
  }

  onMount(() => {
    registerController({
      id: "apps",
      move: (dir, steps = 1) => select(cursor() + dir * steps),
      jump: (first) => select(first ? 0 : rows().length - 1),
      primary: () => {
        const app = current()
        if (app) void launchApp(app.alias)
      },
      hints: () => [
        { key: "enter", label: "launch", run: () => current() && void launchApp(current()!.alias) },
        { key: "/", label: "filter" },
      ],
      startFilter: () => {
        setFiltering(true)
        setFocusMode("input")
      },
    })
  })

  return (
    <box width="100%" height="100%" flexDirection="row">
      <ListPane
        rows={rows()}
        cursor={cursor()}
        onSelect={select}
        filter={{ get: filterValue, set: setFilterValue }}
        filtering={filtering()}
        onStopFiltering={() => {
          setFiltering(false)
          setFocusMode("nav")
        }}
      />
      <DetailPane detail={() => detail.latest} loading={detail.loading} />
      <Show when={adding()}>
        <AddDialog onClose={() => setAdding(false)} />
      </Show>
    </box>
  )
}

// ---- list (filter state lives at module level so it survives view switches) -------

const [filterValue, setFilterValue] = createSignal("")
const [filtering, setFiltering] = createSignal(false)

function ListPane(props: {
  rows: AppRow[]
  cursor: number
  onSelect: (i: number) => void
  filter: { get: () => string; set: (v: string) => void }
  filtering: boolean
  onStopFiltering: () => void
}): unknown {
  const visible = () => {
    const q = props.filter.get().toLowerCase()
    if (!q) return props.rows
    return props.rows.filter(
      (a) => a.alias.toLowerCase().includes(q) || a.name.toLowerCase().includes(q),
    )
  }
  return (
    <box flexGrow={3} flexDirection="column" borderStyle="single" borderColor={C.border}>
      <Show
        when={!props.filtering}
        fallback={
          <box flexDirection="row" height={1} paddingX={1}>
            <text fg={C.green}>/ </text>
            <input
              placeholder="filter apps…"
              value={props.filter.get()}
              onInput={(v: string) => props.filter.set(v)}
              onSubmit={() => props.onStopFiltering()}
              focused={true}
              backgroundColor={C.bg}
              textColor={C.fg}
            />
          </box>
        }
      >
        <box height={1} paddingX={1}>
          <text fg={C.dimmer}>
            APPS {visible().length ? `(${visible().length})` : ""}{" "}
            {props.filter.get() ? ` filter: ${props.filter.get()}` : ""}
          </text>
        </box>
        <Show
          when={visible().length}
          fallback={
            props.rows.length ? (
              <EmptyState glyph="🔍" title="no apps match the filter" hint="esc clears it" />
            ) : (
              <EmptyState
                glyph="◇"
                title="no apps yet"
                hint="add one or import from your collection dirs"
                action={{ label: "Add AppImage", onClick: () => promptAddApp() }}
              />
            )
          }
        >
          {visible().map((app, i) => (
            <AppRowView
              app={app}
              active={i === props.cursor}
              onSelect={() => props.onSelect(i)}
              onOpen={() => void launchApp(app.alias)}
            />
          ))}
        </Show>
      </Show>
    </box>
  )
}

function AppRowView(props: { app: AppRow; active: boolean; onSelect: () => void; onOpen: () => void }): unknown {
  const [hover, setHover] = createSignal(false)
  return (
    <box
      flexDirection="row"
      height={1}
      onMouseOver={() => setHover(true)}
      onMouseOut={() => setHover(false)}
      onMouseDown={(e: { button: number }) => {
        if (e.button === 0) props.onSelect()
      }}
      backgroundColor={props.active ? C.greenDeep : hover() ? C.hover : undefined}
    >
      <text>
        <Span fg={props.active ? C.greenBright : C.border}>▎</Span>
        <Span fg={props.active ? C.green : C.dimmer}> {props.app.alias.slice(0, 15).padEnd(16)}</Span>
        <Span fg={props.active ? C.fg : C.dim}>
          {trunc(props.app.version ?? "?", 12).padEnd(13)}
        </Span>
        <Span fg={statusColor(props.app.update_status)}>
          {statusLabel(props.app.update_status).slice(0, 18).padEnd(19)}
        </Span>
        <Span fg={C.dimmer}>{props.app.source_type ?? "-"}</Span>
      </text>
    </box>
  )
}

// ---- detail ------------------------------------------------------------------------

function DetailPane(props: { detail: () => AppDetail | null | undefined; loading: boolean }): unknown {
  const d = props.detail
  return (
    <box flexGrow={2} flexDirection="column" borderStyle="single" borderColor={C.border}>
      <Show when={!d()} fallback={<DetailBody app={d()} />}>
        <Show
          when={!props.loading}
          fallback={<box padding={1}><text fg={C.dimmer}>loading…</text></box>}
        >
          <EmptyState glyph="◇" title="select an app" hint="click a row or move with j/k" />
        </Show>
      </Show>
    </box>
  )
}

function DetailBody(props: { app: AppDetail | null | undefined }): unknown {
  const app = props.app
  if (!app) return null
  const alias = app.alias
  return (
    <box flexDirection="column" flexGrow={1} padding={1}>
      <text>
        <Span fg={C.green}>{app.name}</Span>
        <Span fg={C.dimmer}> {app.version ?? "?"} · {app.arch ?? "?"} · {humanSize(app.size)}</Span>
      </text>
      {app.description ? (
        <text fg={C.dim} wrapMode="none">{trunc(app.description, 48)}</text>
      ) : null}
      <box height={1} />
      <Field label="source" value={app.source_type ? `${app.source_type}:${app.source_repo}` : "not configured"} />
      <Field label="entry" value={app.integrated ? (app.desktop_file ?? "?") : "not integrated"} />
      <Field label="backups" value={String(app.backups.length)} />
      <Field label="file" value={trunc(app.path.split("/").pop() ?? "", 40)} />
      <Field label="sha256" value={(app.sha256 ?? "").slice(0, 24)} />
      <box height={1} />
      <text fg={C.dimmer}>HISTORY</text>
      {app.history.slice(0, 5).map((h) => (
        <box flexDirection="row" height={1}>
          <box width={12}>
            <text fg={C.dimmer} wrapMode="none">{h.created_at?.slice(5, 10)}</text>
          </box>
          <box width={11}>
            <text fg={C.teal} wrapMode="none">{h.action}</text>
          </box>
          <text fg={C.dim} wrapMode="none">{h.version ?? ""}</text>
        </box>
      ))}
      <box flexGrow={1} />
      <box flexDirection="row">
        <Button label="Launch" onClick={() => void launchApp(alias)} />
        <box width={1} />
        <Button label="Update" onClick={() => void updateApp(alias)} />
        <box width={1} />
        <Button label="Check" onClick={() => void checkApp(alias)} />
        <box width={1} />
        <Button label="Source" onClick={() => void detectSource(alias)} />
        <box width={1} />
        <Button label="Rollback" onClick={() => void rollbackApp(alias)} />
        <box width={1} />
        <Button label="Refresh" onClick={() => void refreshMetadata(alias)} />
        <box width={1} />
        <Button label="Remove" danger={true} onClick={() =>
          confirm(
            `Remove ${alias} from quiver?`,
            "Unregisters it and removes its desktop entry and icon.",
            () => void removeApp(alias, false),
            true,
          )
        } />
      </box>
    </box>
  )
}

function Field(props: { label: string; value: string }): unknown {
  return (
    <box flexDirection="row" height={1}>
      <box width={10}>
        <text fg={C.dimmer}>{props.label}</text>
      </box>
      <text fg={C.dim} wrapMode="none">{props.value}</text>
    </box>
  )
}

// ---- add dialog ---------------------------------------------------------------------

function AddDialog(props: { onClose: () => void }): unknown {
  const [path, setPath] = createSignal("")
  const dims = useTerminalDimensions()
  return (
    <box position="absolute" top={3} left={Math.max(0, Math.floor((dims().width - 48) / 2))} width={48}>
      <box flexDirection="column" borderStyle="single" borderColor={C.borderActive} backgroundColor={C.panel}>
        <box height={1} backgroundColor={C.bg} paddingX={1}>
          <text fg={C.green}> add appimage </text>
        </box>
        <box paddingX={1}>
          <input
            placeholder="/path/to/App.AppImage"
            value={path()}
            onInput={setPath}
            onSubmit={(v: string | object) => {
              const value = typeof v === "string" ? v : path()
              props.onClose()
              if (value.trim()) void addApp(value.trim())
            }}
            focused={true}
            backgroundColor={C.bg}
            textColor={C.fg}
          />
        </box>
        <box height={1} paddingX={1}>
          <text fg={C.dimmer}>enter add · esc cancel</text>
        </box>
      </box>
    </box>
  )
}

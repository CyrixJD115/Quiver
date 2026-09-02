// Settings: config values (click a row to edit in place), paths and timer.
// Saving goes through config.set; values reload after.

import { createResource, createSignal, onMount, Show } from "solid-js"
import { getRpc, setFocusMode, toast, withBusy } from "../state"
import { C, trunc } from "../theme"
import { Button, EmptyState, Span } from "../components/ui"
import { registerController } from "./registry"

export function SettingsView(): unknown {
  const [config, { refetch }] = createResource(async () => {
    try {
      return await getRpc().call<Record<string, unknown>>("config.list")
    } catch {
      return {}
    }
  })
  const [timer, { refetch: refetchTimer }] = createResource(async () => {
    try {
      return await getRpc().call<{ status: string }>("timer.status")
    } catch {
      return { status: "unknown" }
    }
  })
  const [info] = createResource(async () => {
    try {
      return await getRpc().call<Record<string, string>>("core.info")
    } catch {
      return null
    }
  })
  const [editing, setEditing] = createSignal<string | null>(null)
  const [editValue, setEditValue] = createSignal("")
  const [cursor, setCursor] = createSignal(0)

  const flatConfig = (): [string, unknown][] => {
    const out: [string, unknown][] = []
    for (const [key, value] of Object.entries(config.latest ?? {})) {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        for (const [sub, v] of Object.entries(value as Record<string, unknown>)) {
          out.push([`${key}.${sub}`, v])
        }
      } else {
        out.push([key, value])
      }
    }
    return out
  }

  const startEdit = (index: number) => {
    const row = flatConfig()[index]
    if (!row) return
    setEditing(row[0])
    setEditValue(String(row[1] ?? ""))
    setFocusMode("input")
  }

  const save = async (key: string, value: string) => {
    await withBusy(`setting ${key}`, async () => {
      await getRpc().call("config.set", { key, value })
      toast("ok", `${key} saved`)
    })
    void refetch()
  }

  onMount(() => {
    registerController({
      id: "settings",
      move: (dir) => {
        const list = flatConfig()
        if (list.length) setCursor((c) => Math.max(0, Math.min(list.length - 1, c + dir)))
      },
      jump: (first) => {
        const list = flatConfig()
        if (list.length) setCursor(first ? 0 : list.length - 1)
      },
      primary: () => startEdit(cursor()),
      hints: () => [{ key: "enter", label: "edit" }],
    })
  })

  return (
    <box width="100%" height="100%" flexDirection="row">
      <box flexGrow={3} flexDirection="column" borderStyle="single" borderColor={C.border}>
        <box height={1} paddingX={1}>
          <text fg={C.dimmer}>CONFIGURATION — click or press enter to edit</text>
        </box>
        <Show
          when={editing() === null}
          fallback={
            <box paddingX={1} flexDirection="column">
              <text fg={C.green} wrapMode="none">
                set {editing()}
              </text>
              <box height={1} />
              <input
                placeholder="new value"
                value={editValue()}
                onInput={setEditValue}
                onSubmit={(v: string | object) => {
                  const value = typeof v === "string" ? v : editValue()
                  const key = editing()!
                  setEditing(null)
                  setFocusMode("nav")
                  if (value.trim()) void save(key, value.trim())
                }}
                focused={true}
                backgroundColor={C.bg}
                textColor={C.fg}
              />
              <box height={1} />
              <text fg={C.dimmer}>enter save · esc cancel</text>
            </box>
          }
        >
          <Show
            when={flatConfig().length}
            fallback={<EmptyState glyph="◇" title="no configuration" />}
          >
            {flatConfig().map(([key, value], i) => (
              <box
                flexDirection="row"
                height={1}
                backgroundColor={i === cursor() ? C.greenDeep : undefined}
                onMouseDown={(e: { button: number }) => {
                  if (e.button === 0) {
                    setCursor(i)
                    startEdit(i)
                  }
                }}
                onMouseOver={undefined}
              >
                <text>
                  <Span fg={i === cursor() ? C.greenBright : C.border}>▎</Span>
                  <Span fg={i === cursor() ? C.green : C.teal}> {key.padEnd(24).slice(0, 24)}</Span>
                  <Span fg={C.dim}>{String(value)}</Span>
                </text>
              </box>
            ))}
          </Show>
        </Show>
      </box>
      <box flexGrow={2} flexDirection="column" borderStyle="single" borderColor={C.border} padding={1}>
        <text fg={C.dimmer}>PATHS</text>
        {["config_path", "state_dir", "storage_dir", "backup_dir", "icon_dir"].map((key) => (
          <box flexDirection="row" height={1}>
            <box width={13}>
              <text fg={C.dimmer}>{key.replace("_", " ")}</text>
            </box>
            <text fg={C.dim} wrapMode="none">
              {trunc(String(info.latest?.[key] ?? "…"), 34)}
            </text>
          </box>
        ))}
        <box height={1} />
        <text fg={C.dimmer}>SYSTEMD TIMER</text>
        <text fg={C.dim} wrapMode="none">
          {trunc(String(timer.latest?.status ?? "…"), 40)}
        </text>
        <box height={1} />
        <Button
          label="Install timer"
          onClick={() =>
            void (async () => {
              await withBusy("installing timer", async () => {
                await getRpc().call("timer.install", {})
                toast("ok", "systemd timer installed")
              })
              void refetchTimer()
            })()
          }
        />
        <box flexGrow={1} />
        <text fg={C.dimmer} wrapMode="none">
          github token (raises rate limits):
        </text>
        <text fg={C.dimmer} wrapMode="none">
          quiver config set github.token TOKEN
        </text>
      </box>
    </box>
  )
}

// Settings: paths, config values (edit via palette-style input), systemd timer.

import { createResource, onMount, createSignal } from "solid-js"
import { getRpc, setFocusMode, toast, withBusy } from "../state"
import { C } from "../theme"
import { onSubmitValue } from "../util"
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
      primary: () => startEdit(),
      key: (name) => {
        if (name === "R") {
          void refetch()
          void refetchTimer()
          return true
        }
        if (name === "t") {
          void withBusy("installing timer", async () => {
            await getRpc().call("timer.install", {})
            toast("ok", "systemd timer installed")
          })
          void refetchTimer()
          return true
        }
        return false
      },
      hints: () => ["enter edit value", "t install timer", "R reload"],
    })
  })

  const startEdit = () => {
    const row = flatConfig()[cursor()]
    if (!row) return
    setEditing(row[0])
    setEditValue(String(row[1] ?? ""))
    setFocusMode("input")
  }

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

  const save = async (key: string, value: string) => {
    await withBusy(`setting ${key}`, async () => {
      await getRpc().call("config.set", { key, value })
      toast("ok", `${key} saved`)
    })
    void refetch()
  }

  return (
    <box width="100%" height="100%" flexDirection="row">
      <box flexGrow={3} flexDirection="column" borderStyle="single" borderColor={C.border} paddingX={1}>
        <text fg={C.accent}>CONFIGURATION</text>
        <box height={1} />
        {editing() === null
          ? flatConfig().map(([key, value], i) => (
              <box flexDirection="row" height={1} backgroundColor={i === cursor() ? C.selectedAccent : undefined}>
                <box width={2}>
                  <text fg={i === cursor() ? C.accent : C.dimmer}>{i === cursor() ? "❯" : " "}</text>
                </box>
                <box width={26}>
                  <text fg={C.blue} wrapMode="none">
                    {key}
                  </text>
                </box>
                <text fg={C.fg} wrapMode="none">
                  {String(value)}
                </text>
              </box>
            ))
          : (
              <box flexDirection="column">
                <text fg={C.yellow} wrapMode="none">
                  set {editing()}
                </text>
                <box height={1} />
                <input
                  placeholder="new value"
                  value={editValue()}
                  onInput={setEditValue}
                  onSubmit={onSubmitValue((value) => {
                    const key = editing()!
                    setEditing(null)
                    setFocusMode("nav")
                    if (value.trim()) void save(key, value.trim())
                  })}
                  focused={true}
                  backgroundColor={C.panelAlt}
                  textColor={C.fg}
                />
                <box height={1} />
                <text fg={C.dimmer}>enter save · esc cancel</text>
              </box>
            )}
      </box>
      <box flexGrow={2} flexDirection="column" borderStyle="single" borderColor={C.border} padding={1}>
        <text fg={C.accent}>PATHS</text>
        <box height={1} />
        {["config_path", "state_dir", "storage_dir", "backup_dir", "icon_dir"].map((key) => (
          <box flexDirection="row" height={1}>
            <box width={14}>
              <text fg={C.dim}>{key.replace("_", " ")}</text>
            </box>
            <text fg={C.dimmer} wrapMode="none">
              {String(info.latest?.[key] ?? "…").slice(0, 40)}
            </text>
          </box>
        ))}
        <box height={1} />
        <text fg={C.accent}>SYSTEMD TIMER</text>
        <box height={1} />
        <text fg={C.fg} wrapMode="none">
          {String(timer.latest?.status ?? "…").slice(0, 46)}
        </text>
        <box height={1} />
        <text fg={C.dimmer}>install from the CLI:</text>
        <text fg={C.dimmer} wrapMode="none">
          quiver timer install
        </text>
        <box flexGrow={1} />
        <text fg={C.dimmer} wrapMode="none">
          github token: quiver config set github.token TOKEN
        </text>
      </box>
    </box>
  )
}

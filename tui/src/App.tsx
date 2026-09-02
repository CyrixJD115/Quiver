// App shell: title bar with tabs, active view, status bar, dialogs.
// Keyboard model is deliberately small - everything else lives in the
// command menu (:) and on clickable buttons.

import { onCleanup, onMount, Show } from "solid-js"
import { useKeyboard, useRenderer } from "@opentui/solid"
import {
  busyText,
  confirmReq,
  fatalError,
  focusMode,
  overlay,
  refreshApps,
  selectedAlias,
  setConfirmReq,
  setFocusMode,
  setOverlay,
  setView,
  view,
  views,
} from "./state"
import { StatusBar, TitleBar } from "./components/Chrome"
import { CommandMenu, ConfirmDialog, HelpDialog, Toasts, type Command } from "./components/Overlays"
import { AppsView } from "./views/Apps"
import { UpdatesView } from "./views/Updates"
import { HealthView } from "./views/Health"
import { ActivityView } from "./views/Activity"
import { SettingsView } from "./views/Settings"
import { getController } from "./views/registry"
import * as actions from "./actions"
import { installMouseShim } from "./mouse-shim"
import { toast } from "./state"

function buildCommands(): Command[] {
  const alias = selectedAlias()
  const nav: Command[] = views.map((v) => ({
    id: `go:${v.id}`,
    section: "navigate",
    label: `Go to ${v.label}`,
    key: v.key,
    run: () => setView(v.id),
  }))
  const selected: Command[] = alias
    ? [
        { id: "sel:launch", section: `app: ${alias}`, label: "Launch", key: "enter", run: () => void actions.launchApp(alias) },
        { id: "sel:update", section: `app: ${alias}`, label: "Update to latest", run: () => void actions.updateApp(alias) },
        { id: "sel:check", section: `app: ${alias}`, label: "Check for update", run: () => void actions.checkApp(alias) },
        { id: "sel:rollback", section: `app: ${alias}`, label: "Rollback to previous version", run: () => void actions.rollbackApp(alias) },
        { id: "sel:detect", section: `app: ${alias}`, label: "Detect update source", run: () => void actions.detectSource(alias) },
        { id: "sel:refresh", section: `app: ${alias}`, label: "Re-read metadata (self-updated)", run: () => void actions.refreshMetadata(alias) },
        { id: "sel:remove", section: `app: ${alias}`, label: "Remove from quiver", danger: true, run: () => void actions.removeApp(alias, false) },
        { id: "sel:purge", section: `app: ${alias}`, label: "Remove and delete file", danger: true, run: () => void actions.removeApp(alias, true) },
      ]
    : []
  return [
    ...selected,
    ...nav,
    {
      id: "app:add",
      section: "library",
      label: "Add AppImage…",
      run: () => import("./views/Apps").then((m) => m.promptAddApp()),
    },
    { id: "lib:check", section: "library", label: "Check all apps for updates", run: () => void actions.checkAll() },
    { id: "lib:update", section: "library", label: "Update all apps", run: () => void actions.updateAll() },
    { id: "lib:refresh", section: "library", label: "Refresh all metadata", run: () => void actions.refreshMetadata() },
    { id: "lib:detect", section: "library", label: "Detect missing sources", run: () => void actions.detectSource() },
    { id: "lib:import", section: "library", label: "Import found AppImages", run: () => void actions.importApps() },
    { id: "maint:fix", section: "maintenance", label: "Fix integrations (exec bits, entries, icons)", run: () => void actions.fixAll() },
    { id: "maint:clean", section: "maintenance", label: "Clean leftovers (backups, temp, stale icons)", run: () => void actions.cleanSystem() },
    { id: "maint:scan", section: "maintenance", label: "Scan system", run: () => void actions.scanSystem() },
    { id: "sys:reload", section: "system", label: "Reload data from backend", key: "r", run: () => void refreshApps() },
    { id: "sys:help", section: "system", label: "Keyboard help", key: "?", run: () => setOverlay({ kind: "help" }) },
    { id: "sys:quit", section: "system", label: "Quit quiver", key: "q", danger: true, run: () => quit() },
  ]
}

export let quit: () => void = () => undefined

export function App(): unknown {
  const renderer = useRenderer()
  quit = () => renderer.destroy()

  onMount(() => {
    installMouseShim(renderer as unknown as Parameters<typeof installMouseShim>[0])
  })

  onCleanup(() => {
    import("./state").then((m) => m.endSession())
  })

  useKeyboard((key: { name?: string; shift?: boolean; ctrl?: boolean }) => {
    const name = key.name ?? ""

    if (fatalError()) {
      renderer.destroy()
      return
    }

    // While a dialog input has focus, only esc/enter are global.
    if (focusMode() === "input") {
      if (name === "escape") {
        setFocusMode("nav")
        setOverlay(null)
      }
      return
    }

    // Dialogs intercept everything except their own keys.
    if (overlay()) {
      if (name === "escape") setOverlay(null)
      return
    }
    const conf = confirmReq()
    if (conf) {
      if (name === "enter" || name === "y") {
        setConfirmReq(null)
        void conf.action()
      } else if (name === "escape" || name === "n") {
        setConfirmReq(null)
      }
      return
    }

    switch (name) {
      case "tab":
        cycle(key.shift === true ? -1 : 1)
        return
      case ":":
      case "p":
        if (name === "p" && key.ctrl !== true) return
        setOverlay({ kind: "menu" })
        setFocusMode("input")
        return
      case "?":
        setOverlay({ kind: "help" })
        return
      case "/": {
        const c = getController(view())
        if (c && "startFilter" in c) (c as unknown as { startFilter(): void }).startFilter()
        return
      }
      case "r":
        void refreshApps()
        return
      case "q":
        if (busyText()) {
          toast("info", "still working - hold on a second")
          return
        }
        renderer.destroy()
        return
    }

    if (/^[1-5]$/.test(name)) {
      const target = views.find((v) => v.key === name)
      if (target) setView(target.id)
      return
    }

    const controller = getController(view())
    if (!controller) return
    switch (name) {
      case "down":
      case "j":
        controller.move(1)
        return
      case "up":
      case "k":
        controller.move(-1)
        return
      case "pagedown":
        controller.move(1, 8)
        return
      case "pageup":
        controller.move(-1, 8)
        return
      case "g":
        controller.jump(true)
        return
      case "G":
        controller.jump(false)
        return
      case "enter":
        controller.primary()
        return
    }
  })

  function cycle(dir: number): void {
    const idx = views.findIndex((v) => v.id === view())
    setView(views[(idx + dir + views.length) % views.length].id)
  }

  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor={C_BG}>
      <Show when={fatalError()} fallback={<MainLayout />}>
        <ErrorScreen message={fatalError()!} />
      </Show>
    </box>
  )
}

const C_BG = "#0b0f0d"

function ErrorScreen(props: { message: string }): unknown {
  return (
    <box flexGrow={1} flexDirection="column" justifyContent="center" alignItems="center">
      <text fg="#c06a6a">backend unavailable</text>
      <text fg="#6d7d71">{props.message}</text>
      <text fg="#46524a">press any key to exit</text>
    </box>
  )
}

function MainLayout(): unknown {
  return (
    <>
      <TitleBar />
      <box flexDirection="row" flexGrow={1}>
        <Show when={view() === "apps"}>
          <AppsView />
        </Show>
        <Show when={view() === "updates"}>
          <UpdatesView />
        </Show>
        <Show when={view() === "health"}>
          <HealthView />
        </Show>
        <Show when={view() === "activity"}>
          <ActivityView />
        </Show>
        <Show when={view() === "settings"}>
          <SettingsView />
        </Show>
      </box>
      <StatusBar
        onMenu={() => {
          setOverlay({ kind: "menu" })
          setFocusMode("input")
        }}
        onHelp={() => setOverlay({ kind: "help" })}
        onQuit={() => quit()}
      />
      <Show when={overlay()?.kind === "menu"}>
        <CommandMenu commands={buildCommands()} />
      </Show>
      <Show when={overlay()?.kind === "help"}>
        <HelpDialog />
      </Show>
      <Show when={confirmReq()}>
        <ConfirmDialog />
      </Show>
      <Toasts />
    </>
  )
}

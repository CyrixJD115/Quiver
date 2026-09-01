// App shell: layout chrome, view routing, the single global keyboard owner.

import { createEffect, on, onCleanup, onMount, Show } from "solid-js"
import { useKeyboard, useRenderer } from "@opentui/solid"
import {
  busyText,
  confirmReq,
  fatalError,
  focusMode,
  overlay,
  refreshApps,
  setConfirmReq,
  setFocusMode,
  setOverlay,
  setView,
  view,
  views,
} from "./state"
import { Header, Sidebar, StatusBar } from "./components/Chrome"
import { ConfirmBox, HelpSheet, Palette, Toasts, type Command } from "./components/Overlays"
import { DashboardView } from "./views/Dashboard"
import { AppsView } from "./views/Apps"
import { UpdatesView } from "./views/Updates"
import { HealthView } from "./views/Health"
import { ActivityView } from "./views/Activity"
import { SettingsView } from "./views/Settings"
import { getController } from "./views/registry"
import * as actions from "./actions"

function buildCommands(): Command[] {
  const nav: Command[] = views.map((v) => ({
    id: `go:${v.id}`,
    label: `Go to ${v.label}`,
    detail: `view ${v.key}`,
    run: () => setView(v.id),
  }))
  return [
    ...nav,
    { id: "check:all", label: "Check all apps for updates", detail: "updates.check", run: () => void actions.checkAll() },
    { id: "update:all", label: "Update all apps", detail: "updates.applyAll", run: () => void actions.updateAll() },
    { id: "fix", label: "Fix integrations", detail: "exec bits, entries, icons", run: () => void actions.fixAll() },
    { id: "clean", label: "Clean leftovers", detail: "owned files only", run: () => void actions.cleanSystem() },
    { id: "scan", label: "Scan system", detail: "read-only report", run: () => void actions.scanSystem() },
    { id: "import", label: "Import found AppImages", detail: "collection dirs", run: () => void actions.importApps() },
    { id: "detect", label: "Detect missing sources", detail: "github search", run: () => void actions.detectSource() },
    { id: "refresh", label: "Refresh metadata", detail: "self-updated apps", run: () => void actions.refreshMetadata() },
    { id: "reload", label: "Reload data", detail: "apps + doctor", run: () => void refreshApps() },
    { id: "help", label: "Show keyboard help", detail: "?", run: () => setOverlay({ kind: "help" }) },
  ]
}

const commands = buildCommands()

export function App(): unknown {
  const renderer = useRenderer()

  onCleanup(() => {
    import("./state").then((m) => m.endSession())
  })

  useKeyboard((key: { name: string; shift: boolean | undefined }) => {
    const name = key.name ?? ""
    const shift = key.shift === true

    // Fatal error screen: any key quits.
    if (fatalError()) {
      renderer.destroy()
      return
    }

    // Text-input mode: components own printable keys; escape returns to nav.
    if (focusMode() === "input") {
      if (name === "escape") {
        setFocusMode("nav")
        // leave overlays that were capturing text
        if (overlay()?.kind === "palette") setOverlay(null)
      }
      return
    }

    // Overlays capture navigation keys.
    const ov = overlay()
    if (ov) {
      if (name === "escape" || (name === "q" && ov.kind === "help")) setOverlay(null)
      return
    }

    const conf = confirmReq()
    if (conf) {
      if (name === "y" || name === "enter") {
        setConfirmReq(null)
        void conf.action()
      } else if (name === "escape" || name === "n" || name === "q") {
        setConfirmReq(null)
      }
      return
    }

    // Global keys
    if (/^[1-6]$/.test(name)) {
      const target = views.find((v) => v.key === name)
      if (target) setView(target.id)
      return
    }
    switch (name) {
      case "tab": {
        const idx = views.findIndex((v) => v.id === view())
        setView(views[(idx + 1) % views.length].id)
        return
      }
      case ":":
        setOverlay({ kind: "palette" })
        setFocusMode("input")
        return
      case "?":
        setOverlay({ kind: "help" })
        return
      case "r":
        void refreshApps()
        return
      case "q":
        if (busyText()) return // don't quit mid-operation without asking
        renderer.destroy()
        return
    }

    // View-scoped navigation
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
      case "g":
        controller.jump(true)
        return
      case "G":
        controller.jump(false)
        return
      case "enter":
        controller.primary()
        return
      default:
        controller.key(name, shift || key.shift === true)
    }
  })

  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#11111b">
      <Show when={fatalError()} fallback={<MainLayout />}>
        <box flexGrow={1} flexDirection="column" justifyContent="center" alignItems="center">
          <text fg="#f38ba8">backend unavailable</text>
          <text fg="#6c7086">{fatalError()}</text>
          <text fg="#45475a">press any key to exit</text>
        </box>
      </Show>
    </box>
  )
}

function MainLayout(): unknown {
  return (
    <>
      <Header />
      <box flexDirection="row" flexGrow={1}>
        <Sidebar />
        <Show when={view() === "dashboard"}>
          <DashboardView />
        </Show>
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
      <StatusBar />
      <Show when={overlay()?.kind === "palette"}>
        <Palette commands={commands} />
      </Show>
      <Show when={overlay()?.kind === "help"}>
        <HelpSheet />
      </Show>
      <Show when={confirmReq()}>
        <ConfirmBox />
      </Show>
      <Toasts />
    </>
  )
}

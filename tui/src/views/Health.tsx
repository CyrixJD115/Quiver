// Health: doctor diagnostics, scan summary, destructive actions with confirm.

import { createResource, onMount } from "solid-js"
import { getRpc, setView } from "../state"
import { C } from "../theme"
import { confirm } from "../components/Overlays"
import { cleanSystem, fixAll, importApps, scanSystem } from "../actions"
import { registerController } from "./registry"

interface Diagnostic {
  level: string
  area: string
  message: string
  hint: string | null
}

export function HealthView(): unknown {
  const [doctor, { refetch }] = createResource(async () => {
    try {
      return await getRpc().call<{
        diagnostics: Diagnostic[]
        ok: number
        info: number
        warn: number
        error: number
      }>("system.doctor")
    } catch {
      return null
    }
  })

  onMount(() => {
    registerController({
      id: "health",
      move: () => undefined,
      jump: () => undefined,
      primary: () => void refetch(),
      key: (name) => {
        switch (name) {
          case "f":
            void fixAll()
            return true
          case "n":
            confirm(
              "Remove leftovers?",
              "Partial downloads, old backups, stale entries and unreferenced icons.",
              () => void cleanSystem(),
            )
            return true
          case "s":
            void scanSystem()
            return true
          case "i":
            confirm(
              "Import AppImages from collection dirs?",
              "Adopts everything found without asking.",
              () => void importApps(),
            )
            return true
          case "R":
            void refetch()
            return true
          default:
            return false
        }
      },
      hints: () => ["enter rerun doctor", "f fix", "n clean", "s scan", "i import"],
    })
  })

  const color = (level: string) =>
    level === "error" ? C.red : level === "warn" ? C.yellow : level === "info" ? C.teal : C.green

  return (
    <box width="100%" height="100%" flexDirection="row">
      <box flexGrow={3} flexDirection="column" borderStyle="single" borderColor={C.border} paddingX={1}>
        <box flexDirection="row" height={1}>
          <text fg={C.accent}>DOCTOR</text>
          <box flexGrow={1} />
          <text fg={C.dim}>
            {doctor.latest
              ? `${doctor.latest.ok} ok · ${doctor.latest.info} info · ${doctor.latest.warn} warn · ${doctor.latest.error} error`
              : "…"}
          </text>
        </box>
        <box height={1} />
        {(doctor.latest?.diagnostics ?? [])
          .filter((d) => d.level !== "ok")
          .map((d) => (
            <box flexDirection="column">
              <box flexDirection="row" height={1}>
                <box width={7}>
                  <text fg={color(d.level)}>{d.level === "error" ? "✗" : d.level === "warn" ? "⚠" : "•"}</text>
                  <text fg={C.dimmer} wrapMode="none">
                    {` ${d.area}`}
                  </text>
                </box>
                <text fg={C.fg} wrapMode="none">
                  {d.message.slice(0, 70)}
                </text>
              </box>
              {d.hint ? (
                <box flexDirection="row" height={1}>
                  <box width={9} />
                  <text fg={C.dimmer} wrapMode="none">
                    {`↳ ${d.hint.slice(0, 68)}`}
                  </text>
                </box>
              ) : null}
            </box>
          ))}
        {(doctor.latest?.diagnostics ?? []).every((d) => d.level === "ok") && doctor.latest ? (
          <text fg={C.green}>all clear — nothing to report</text>
        ) : null}
      </box>
      <box flexGrow={2} flexDirection="column" borderStyle="single" borderColor={C.border} padding={1}>
        <text fg={C.accent}>MAINTENANCE</text>
        <box height={1} />
        <text fg={C.fg}>f — repair integrations</text>
        <text fg={C.dim}>  exec bits, desktop entries, icons, markers</text>
        <box height={1} />
        <text fg={C.fg}>n — clean leftovers</text>
        <text fg={C.dim}>  previews first, removes only owned files</text>
        <box height={1} />
        <text fg={C.fg}>s — scan system</text>
        <text fg={C.dim}>  AppImages, entries, icons, duplicates</text>
        <box height={1} />
        <text fg={C.fg}>i — import found AppImages</text>
        <text fg={C.dim}>  adopts from configured collection dirs</text>
        <box flexGrow={1} />
        <text fg={C.dimmer}>destructive actions always confirm first</text>
        <box height={1} />
        <text fg={C.dimmer}>5 — activity view for the full log</text>
      </box>
    </box>
  )
}
